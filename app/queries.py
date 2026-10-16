"""Read-side questions: 'jobs waiting for me', a job's history, 'who could have changed it on date X'.

KEY IDEA (Q13): 'waiting for me' uses the SAME rule shape as engine.can() -- grant valid today,
role includes the action, scope covers the job, stage fits, maker-checker, absence, delegation --
but expressed as one SQL query so it stays fast on 200k jobs. A test asserts the two never drift.
"""
import json
from .engine import _today

# The next step each stage is waiting for. (Reopened jobs need preparing again.)
STAGE_TO_ACTION = {"confirmed": "prepare", "reopened": "prepare", "prepared": "check", "checked": "file"}

_SCOPE = """(g.client_id IS NULL OR g.client_id = j.client_id)
        AND (g.branch_id IS NULL OR g.branch_id = j.branch_id)
        AND (g.direction IS NULL OR g.direction = j.direction)
        AND (g.mode IS NULL OR g.mode = j.mode)"""
_VALID = "g.valid_from <= :today AND (g.valid_to IS NULL OR g.valid_to >= :today)"

def _can_do(action):
    """SQL fragment: user holds a valid grant for `action` covering job j, OR covers an owner via delegation."""
    return f"""(
      EXISTS (SELECT 1 FROM grants g JOIN role_actions ra ON ra.role=g.role
              WHERE g.user_id=:u AND ra.action='{action}' AND {_VALID} AND {_SCOPE})
      OR (j.owner_id IN (SELECT d.from_user FROM delegations d
                         WHERE d.to_user=:u AND d.valid_from<=:today AND d.valid_to>=:today)
          AND EXISTS (SELECT 1 FROM grants g JOIN role_actions ra ON ra.role=g.role
                      WHERE g.user_id=:u AND ra.action='{action}' AND {_VALID}))
    )"""

_WAITING_WHERE = f"""(
   (j.stage IN ('confirmed','reopened') AND {_can_do('prepare')})
OR (j.stage = 'prepared' AND j.prepared_by IS NOT :u AND {_can_do('check')})
OR (j.stage = 'checked'  AND {_can_do('file')})
)"""

def waiting_for_me(con, user_id, *, today=None, limit=50, offset=0):
    """Jobs this person could act on right now. Returns {count, jobs}."""
    today = _today(today)
    u = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    # Same early exits as can(): unknown / disabled / client-side / absent => nothing waiting.
    if (not u or u["status"] != "active" or u["kind"] != "staff"
            or (u["absent_from"] and u["absent_from"] <= today <= (u["absent_until"] or "9999"))):
        return {"count": 0, "jobs": []}
    p = {"u": user_id, "today": today}
    count = con.execute(f"SELECT COUNT(*) FROM jobs j WHERE {_WAITING_WHERE}", p).fetchone()[0]
    rows = con.execute(f"""SELECT j.id, j.ref, j.client_id, j.branch_id, j.direction, j.mode,
                                  j.stage, j.owner_id FROM jobs j WHERE {_WAITING_WHERE}
                           ORDER BY j.id LIMIT :limit OFFSET :offset""",
                       {**p, "limit": limit, "offset": offset}).fetchall()
    jobs = [{**dict(r), "waiting_for": STAGE_TO_ACTION[r["stage"]]} for r in rows]
    return {"count": count, "jobs": jobs}

def job_history(con, job_id, *, decisions=True):
    """Everything recorded about a job, oldest first. decisions=False => only things that changed it."""
    q = "SELECT * FROM audit_log WHERE job_id=?" + ("" if decisions else " AND event='job_action'") + " ORDER BY id"
    return [{**dict(r), "detail": json.loads(r["detail"] or "{}")} for r in con.execute(q, (job_id,))]

MUTATING = ("prepare", "check", "file", "cancel", "reopen", "update")

def who_could_change(con, job_id, on_date):
    """Q11: who COULD have changed this job on `on_date`? Built from dated grants (never overwritten),
    delegations and absences -- not from today's state. 'Could' = held authority, not 'did'.
    Stage on that date is not filtered: it lists who held authority over the job's scope.
    Known limit: absences are stored as one range per person, so only the current range is known."""
    job = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job: return None
    acts = ",".join("?" * len(MUTATING))
    rows = con.execute(f"""
      SELECT g.id AS grant_id, g.user_id, u.name, g.role, ra.action, g.valid_from, g.valid_to,
             u.absent_from, u.absent_until
      FROM grants g JOIN role_actions ra ON ra.role=g.role JOIN users u ON u.id=g.user_id
      WHERE ra.action IN ({acts}) AND g.valid_from <= ? AND (g.valid_to IS NULL OR g.valid_to >= ?)
        AND (g.client_id IS NULL OR g.client_id=?) AND (g.branch_id IS NULL OR g.branch_id=?)
        AND (g.direction IS NULL OR g.direction=?) AND (g.mode IS NULL OR g.mode=?)
        AND u.kind='staff' ORDER BY u.name, g.id""",
      (*MUTATING, on_date, on_date, job["client_id"], job["branch_id"], job["direction"], job["mode"])).fetchall()
    people = {}
    for r in rows:
        if r["absent_from"] and r["absent_from"] <= on_date <= (r["absent_until"] or "9999"): continue
        p = people.setdefault(r["user_id"], {"user": r["user_id"], "name": r["name"], "via": "grant",
                                             "actions": set(), "grant_ids": set()})
        p["actions"].add(r["action"]); p["grant_ids"].add(r["grant_id"])
    for d in con.execute("SELECT * FROM delegations WHERE from_user=? AND valid_from<=? AND valid_to>=?",
                         (job["owner_id"], on_date, on_date)):
        p = people.setdefault(d["to_user"], {"user": d["to_user"], "name": d["to_user"], "via": "delegation",
                                             "actions": set(), "grant_ids": set()})
        p["via"] = "grant" if p["grant_ids"] else f"delegation #{d['id']}"
    out = [{**p, "actions": sorted(p["actions"]), "grant_ids": sorted(p["grant_ids"])} for p in people.values()]
    return {"job": job["ref"], "date": on_date, "people": out,
            "actual_actions": [h for h in job_history(con, job_id, decisions=False) if h["ts"][:10] <= on_date]}
