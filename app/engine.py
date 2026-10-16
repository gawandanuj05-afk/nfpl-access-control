"""The decision engine. Everything about "who may do what on which job" lives here.

Public functions:
  can(...)          -> decision dict {allowed, reason, matched_grant, via, checks}
  explain_diff(...) -> compare two people on the same action + job (Q10)
  perform(...)      -> run an action: can() first, then change the job
  grant_role / revoke_grant -> manage who has what (admin only, Q8)

Principles: deny by default; every decision (allowed or denied) is audited;
nothing is cached, so access changes apply on the very next call.
"""
import json
from datetime import date, datetime, timedelta

# Which job stages permit which action (the workflow itself, separate from roles).
STAGE_RULES = {
    "prepare": {"confirmed", "reopened"},
    "check":   {"prepared"},
    "file":    {"checked"},
    "cancel":  {"confirmed", "prepared", "checked", "filed", "reopened"},
    "reopen":  {"filed", "cancelled"},
    "update":  {"confirmed", "prepared", "checked", "reopened"},  # parser edits: never filed/cancelled
}
NEXT_STAGE = {"prepare": "prepared", "check": "checked", "file": "filed",
              "cancel": "cancelled", "reopen": "reopened"}
# Actions that need a written reason (Q6): cancelling a filed job, any reopen.
def _needs_reason(action, job):
    return action == "reopen" or (action == "cancel" and job["stage"] == "filed")

def _today(today): return today or date.today().isoformat()
def _now(): return datetime.now().isoformat(timespec="seconds")

def _log(con, actor, event, job_id=None, action=None, allowed=None, reason=None, detail=None):
    con.execute("""INSERT INTO audit_log(ts,actor,event,job_id,action,allowed,reason,detail)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (_now(), actor, event, job_id, action,
                 None if allowed is None else int(allowed), reason, json.dumps(detail or {})))

def _scope_text(client, branch, direction, mode):
    return f"client {client or 'any'}, branch {branch or 'any'}, " \
           f"{direction or 'any direction'}, {mode or 'any mode'}"

def _matching_grants(con, user_id, action, job, today):
    """Grants valid today whose role includes `action` AND whose scope covers the job.
    A NULL scope column means 'all'. This same query shape powers 'waiting for me'."""
    return con.execute("""
      SELECT g.* FROM grants g JOIN role_actions ra ON ra.role = g.role
      WHERE g.user_id=? AND ra.action=?
        AND g.valid_from <= ? AND (g.valid_to IS NULL OR g.valid_to >= ?)
        AND (g.client_id  IS NULL OR g.client_id  = ?)
        AND (g.branch_id  IS NULL OR g.branch_id  = ?)
        AND (g.direction  IS NULL OR g.direction  = ?)
        AND (g.mode       IS NULL OR g.mode       = ?)
      ORDER BY g.id""", (user_id, action, today, today, job["client_id"],
                         job["branch_id"], job["direction"], job["mode"])).fetchall()

def _delegation_cover(con, user_id, action, job, today):
    """Cover for an absent owner: user acts on jobs OWNED by the delegator, but only
    with a role they already hold (any scope). Delegation widens WHICH jobs, never WHICH roles."""
    if not job["owner_id"]: return None
    d = con.execute("""SELECT * FROM delegations WHERE from_user=? AND to_user=?
                       AND valid_from<=? AND valid_to>=?""",
                    (job["owner_id"], user_id, today, today)).fetchone()
    if not d: return None
    g = con.execute("""SELECT g.* FROM grants g JOIN role_actions ra ON ra.role=g.role
                       WHERE g.user_id=? AND ra.action=? AND g.valid_from<=?
                       AND (g.valid_to IS NULL OR g.valid_to>=?)""",
                    (user_id, action, today, today)).fetchone()
    return (d, g) if g else None

def can(con, user_id, action, job_id=None, *, new_job=None, reason=None, today=None, log=True):
    """May `user_id` do `action` on job `job_id`? (`new_job` = scope dict, for 'create'.)"""
    today = _today(today)
    checks = []
    def step(name, ok, detail): checks.append({"check": name, "ok": ok, "detail": detail}); return ok
    def done(allowed, why, grant=None, via=None):
        res = {"allowed": allowed, "reason": why, "user": user_id, "action": action,
               "job_id": job_id, "matched_grant": dict(grant) if grant else None,
               "via": via, "checks": checks}
        if log:
            _log(con, user_id, "decision", job_id, action, allowed, why,
                 {"checks": checks, "grant_id": grant["id"] if grant else None, "via": via})
            con.commit()
        return res

    # 1. Who is asking? (unknown/disabled => deny)
    user = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user: step("user", False, "unknown user"); return done(False, "Unknown user.")
    if user["status"] != "active":
        step("user", False, "user is disabled"); return done(False, f"{user['name']} is disabled.")
    step("user", True, f"{user['name']} is active")

    # 2. Is the action real?
    known = {r[0] for r in con.execute("SELECT DISTINCT action FROM role_actions")}
    if action not in known:
        step("action", False, f"'{action}' is not a known action")
        return done(False, f"Unknown action '{action}'. Denied by default.")

    # 3. Which job?
    if action == "create":
        job = dict(new_job or {}, stage="new", owner_id=None, id=None)
        if not all(job.get(k) for k in ("client_id", "branch_id", "direction", "mode")):
            step("job", False, "new job scope incomplete"); return done(False, "Cannot decide: incomplete job scope.")
    else:
        job = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone() if job_id else None
        if not job: step("job", False, "job not found"); return done(False, "Job not found. Denied by default.")
    step("job", True, f"job {job['ref'] if action != 'create' else '(new)'} stage={job['stage']}")

    # 4. Absence (Q4): an absent person cannot ACT (they can still look).
    if action != "view" and user["absent_from"] and user["absent_from"] <= today <= (user["absent_until"] or "9999"):
        step("absence", False, f"absent {user['absent_from']} to {user['absent_until']}")
        return done(False, f"{user['name']} is absent until {user['absent_until']}; "
                           f"a delegate or another holder of the role must act.")

    # 5. Client-side staff are read-only, whatever grants they hold (Q7).
    if user["kind"] == "client" and action != "view":
        step("client_user", False, "client-side users are read-only")
        return done(False, "Client-side users can only view their own shipments.")

    # 6. Role + scope.
    grants = _matching_grants(con, user_id, action, job, today)
    grant, via = (grants[0], "grant") if grants else (None, None)
    if not grant and action != "create":
        cover = _delegation_cover(con, user_id, action, job, today)
        if cover:
            d, grant = cover; via = f"delegation from {d['from_user']} (#{d['id']})"
    if not grant:
        # Explain the near-miss: does the user hold a role for this action in some OTHER scope?
        near = con.execute("""SELECT g.* FROM grants g JOIN role_actions ra ON ra.role=g.role
              WHERE g.user_id=? AND ra.action=? AND g.valid_from<=? AND (g.valid_to IS NULL OR g.valid_to>=?)""",
              (user_id, action, today, today)).fetchall()
        if near:
            held = "; ".join(f"{g['role']} for " + _scope_text(g['client_id'], g['branch_id'], g['direction'], g['mode']) for g in near)
            msg = (f"{user['name']} holds [{held}] but this job is "
                   + _scope_text(job['client_id'], job['branch_id'], job['direction'], job['mode']) + ".")
        else:
            msg = f"{user['name']} has no role that allows '{action}'."
        step("role_scope", False, msg); return done(False, msg)
    step("role_scope", True, f"grant #{grant['id']} ({grant['role']}) via {via}")

    # 7. Does the workflow stage allow it?
    if action in STAGE_RULES and job["stage"] not in STAGE_RULES[action]:
        msg = f"'{action}' is not allowed while the job is {job['stage']}."
        step("stage", False, msg); return done(False, msg, grant, via)
    step("stage", True, "stage permits action")

    # 8. Maker-checker (Q3): nobody checks what they prepared.
    if action == "check" and job["prepared_by"] == user_id:
        msg = f"{user['name']} prepared this job and cannot also check it (maker-checker rule)."
        step("separation_of_duties", False, msg); return done(False, msg, grant, via)
    step("separation_of_duties", True, "no conflict")

    # 9. Written reason for the dangerous ones (Q6).
    if _needs_reason(action, job) and not (reason and reason.strip()):
        msg = f"'{action}' on a {job['stage']} job needs a written reason."
        step("reason", False, msg); return done(False, msg, grant, via)
    step("reason", True, "not required or provided")

    return done(True, f"Allowed: {grant['role']} grant #{grant['id']} covers this job via {via}.", grant, via)

def explain_diff(con, user_a, user_b, action, job_id, today=None):
    """Q10: 'why can she do this and he can't?' = two unlogged decisions side by side."""
    a = can(con, user_a, action, job_id, today=today, log=False)
    b = can(con, user_b, action, job_id, today=today, log=False)
    return {"a": a, "b": b, "summary": f"{user_a}: {'ALLOWED' if a['allowed'] else 'DENIED'} — {a['reason']}  |  "
                                      f"{user_b}: {'ALLOWED' if b['allowed'] else 'DENIED'} — {b['reason']}"}

def perform(con, user_id, action, job_id, *, reason=None, today=None):
    """Do the action. Decision first; the job changes only if allowed."""
    res = can(con, user_id, action, job_id, reason=reason, today=today)
    if not res["allowed"]: return res
    job = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    before = job["stage"]; now = _now()
    if action == "prepare":
        con.execute("UPDATE jobs SET stage='prepared', prepared_by=?, updated_at=? WHERE id=?", (user_id, now, job_id))
    elif action == "check":
        con.execute("UPDATE jobs SET stage='checked', checked_by=?, updated_at=? WHERE id=?", (user_id, now, job_id))
    elif action == "reopen":   # fresh cycle: maker-checker starts over
        con.execute("UPDATE jobs SET stage='reopened', prepared_by=NULL, checked_by=NULL, updated_at=? WHERE id=?", (now, job_id))
    elif action in NEXT_STAGE:
        con.execute("UPDATE jobs SET stage=?, updated_at=? WHERE id=?", (NEXT_STAGE[action], now, job_id))
    else:
        con.execute("UPDATE jobs SET updated_at=? WHERE id=?", (now, job_id))
    _log(con, user_id, "job_action", job_id, action, True, reason,
         {"from": before, "to": NEXT_STAGE.get(action, before), "grant_id": res["matched_grant"]["id"], "via": res["via"]})
    con.commit()
    return res

# ---------- managing who has what (Q8) ----------
def _admin_check(con, actor, today):
    g = con.execute("""SELECT g.id FROM grants g JOIN role_actions ra ON ra.role=g.role
        WHERE g.user_id=? AND ra.action='manage_grants' AND g.valid_from<=?
        AND (g.valid_to IS NULL OR g.valid_to>=?)""", (actor, today, today)).fetchone()
    return bool(g)

def _deny_grant(con, actor, event, why, detail):
    _log(con, actor, event, allowed=False, reason=why, detail=detail); con.commit()
    return {"ok": False, "reason": why}

def grant_role(con, actor, target, role, *, client_id=None, branch_id=None, direction=None,
               mode=None, reason=None, today=None):
    today = _today(today)
    detail = {"target": target, "role": role, "client": client_id, "branch": branch_id,
              "direction": direction, "mode": mode}
    if not _admin_check(con, actor, today):
        return _deny_grant(con, actor, "grant_change", f"{actor} may not manage grants.", detail)
    if actor == target:   # nobody changes their own access
        return _deny_grant(con, actor, "grant_change", "You cannot change your own access; another admin must.", detail)
    if not reason or not reason.strip():
        return _deny_grant(con, actor, "grant_change", "A reason is required for every grant.", detail)
    if not con.execute("SELECT 1 FROM role_actions WHERE role=?", (role,)).fetchone():
        return _deny_grant(con, actor, "grant_change", f"Unknown role '{role}'.", detail)
    u = con.execute("SELECT * FROM users WHERE id=?", (target,)).fetchone()
    if not u: return _deny_grant(con, actor, "grant_change", "Unknown target user.", detail)
    if u["kind"] == "client" and (role != "client_viewer" or not client_id):
        return _deny_grant(con, actor, "grant_change", "Client-side users may only get client_viewer, tied to one client.", detail)
    if u["kind"] != "client" and role == "client_viewer":
        return _deny_grant(con, actor, "grant_change", "client_viewer is for client-side users only.", detail)
    if u["kind"] == "system" and role != "parser":
        return _deny_grant(con, actor, "grant_change", "System users may only hold the parser role.", detail)
    cur = con.execute("""INSERT INTO grants(user_id,role,client_id,branch_id,direction,mode,
        valid_from,created_by,reason) VALUES (?,?,?,?,?,?,?,?,?)""",
        (target, role, client_id, branch_id, direction, mode, today, actor, reason))
    _log(con, actor, "grant_change", allowed=True, reason=reason, detail={**detail, "grant_id": cur.lastrowid, "op": "grant"})
    con.commit()
    return {"ok": True, "grant_id": cur.lastrowid}

def revoke_grant(con, actor, grant_id, *, reason=None, today=None):
    """Revoking never deletes: valid_to becomes yesterday, so it ends immediately but history stays."""
    today = _today(today)
    g = con.execute("SELECT * FROM grants WHERE id=?", (grant_id,)).fetchone()
    detail = {"grant_id": grant_id, "op": "revoke"}
    if not _admin_check(con, actor, today):
        return _deny_grant(con, actor, "grant_change", f"{actor} may not manage grants.", detail)
    if not g: return _deny_grant(con, actor, "grant_change", "No such grant.", detail)
    if g["user_id"] == actor:
        return _deny_grant(con, actor, "grant_change", "You cannot change your own access; another admin must.", detail)
    if not reason or not reason.strip():
        return _deny_grant(con, actor, "grant_change", "A reason is required.", detail)
    yday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    con.execute("UPDATE grants SET valid_to=?, revoked_by=? WHERE id=?", (yday, actor, grant_id))
    _log(con, actor, "grant_change", allowed=True, reason=reason, detail={**detail, "target": g["user_id"], "role": g["role"]})
    con.commit()
    return {"ok": True}
