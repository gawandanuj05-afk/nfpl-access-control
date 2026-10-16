"""One test per edge case in the brief. Dates are pinned so tests never depend on the clock."""
import pytest
from app import engine
from app.seed import seed

TODAY = "2026-10-16"

@pytest.fixture
def con():
    return seed(":memory:")

def jid(con, ref): return con.execute("SELECT id FROM jobs WHERE ref=?", (ref,)).fetchone()[0]
def can(con, user, action, ref, **kw):
    kw.setdefault("today", TODAY)
    return engine.can(con, user, action, jid(con, ref), **kw)
def stage(con, ref): return con.execute("SELECT stage FROM jobs WHERE ref=?", (ref,)).fetchone()[0]
def new_job(con, ref, stage, client="C01", branch="MUM", direction="import", mode="fcl", prep=None, owner="sunita"):
    con.execute("""INSERT INTO jobs(ref,client_id,branch_id,direction,mode,stage,owner_id,prepared_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,'2026-10-01','2026-10-01')""", (ref, client, branch, direction, mode, stage, owner, prep))

# --- Q2: scoped roles -------------------------------------------------------
def test_maker_everywhere(con):
    assert can(con, "ravi", "prepare", "DEMO-C05")["allowed"]        # any client, any branch

def test_checker_only_for_a_few_clients(con):
    new_job(con, "T1", "prepared", client="C01")
    new_job(con, "T2", "prepared", client="C05")
    assert can(con, "ravi", "check", "T1")["allowed"]                # C01 is one of his
    r = can(con, "ravi", "check", "T2")
    assert not r["allowed"] and "C01" in r["reason"]                 # near-miss is explained

def test_narrow_checker_client_branch_direction(con):
    assert can(con, "neha", "check", "DEMO-NARROW-OK")["allowed"]
    r = can(con, "neha", "check", "DEMO-NARROW-NO")                  # export job
    assert not r["allowed"] and "import" in r["reason"]
    new_job(con, "T3", "prepared", branch="DEL")                     # wrong branch
    assert not can(con, "neha", "check", "T3")["allowed"]

# --- Q3: maker/checker ------------------------------------------------------
def test_maker_cannot_check_own_work(con):
    r = can(con, "ravi", "check", "DEMO-MC-CONFLICT")                # Ravi prepared it AND is C01 checker
    assert not r["allowed"] and "maker-checker" in r["reason"]
    assert can(con, "neha", "check", "DEMO-MC-CONFLICT")["allowed"]  # someone else can
    assert not can(con, "lata", "check", "DEMO-LATA")["allowed"]     # maker+checker same scope

# --- Q4: absent owner -------------------------------------------------------
def test_absent_user_cannot_act_but_can_view(con):
    r = can(con, "imran", "prepare", "DEMO-ABSENT")
    assert not r["allowed"] and "absent" in r["reason"]
    assert can(con, "imran", "view", "DEMO-ABSENT")["allowed"]

def test_delegation_widens_jobs_not_roles(con):
    assert not can(con, "karan", "prepare", "DEMO-ABSENT")["allowed"]   # Karan: Delhi air only
    con.execute("INSERT INTO delegations(from_user,to_user,valid_from,valid_to,created_by) VALUES ('imran','karan','2026-10-12','2026-10-23','asha')")
    r = can(con, "karan", "prepare", "DEMO-ABSENT")
    assert r["allowed"] and "delegation" in r["via"]
    assert not can(con, "karan", "file", "DEMO-ABSENT")["allowed"]      # still no filer role
    assert not engine.can(con, "karan", "prepare", jid(con, "DEMO-ABSENT"), today="2026-10-30")["allowed"]  # expired

# --- Q5: responsibilities change -------------------------------------------
def test_changed_responsibility_uses_the_date(con):
    new_job(con, "D1", "confirmed", branch="DEL", mode="fcl", owner="karan")
    assert engine.can(con, "karan", "prepare", jid(con, "D1"), today="2026-09-15")["allowed"]      # old grant: all modes
    r = engine.can(con, "karan", "prepare", jid(con, "D1"), today=TODAY)                            # now: air only
    assert not r["allowed"]
    # work already stamped before the change stays on the job
    new_job(con, "D2", "prepared", branch="DEL", mode="fcl", prep="karan", owner="karan")
    assert con.execute("SELECT prepared_by FROM jobs WHERE ref='D2'").fetchone()[0] == "karan"

# --- Q6: filed-job cancel / reopen -----------------------------------------
def test_filed_cancel_and_reopen(con):
    assert not can(con, "farah", "cancel", "DEMO-FILED", reason="x")["allowed"]   # filer is not controller
    assert not can(con, "vikram", "cancel", "DEMO-FILED")["allowed"]               # no reason
    r = engine.perform(con, "vikram", "cancel", jid(con, "DEMO-FILED"), reason="Client withdrew", today=TODAY)
    assert r["allowed"] and stage(con, "DEMO-FILED") == "cancelled"
    assert not can(con, "vikram", "reopen", "DEMO-FILED")["allowed"]               # reopen needs reason too
    engine.perform(con, "vikram", "reopen", jid(con, "DEMO-FILED"), reason="Filed in error", today=TODAY)
    assert stage(con, "DEMO-FILED") == "reopened"
    assert tuple(con.execute("SELECT prepared_by, checked_by FROM jobs WHERE ref='DEMO-FILED'").fetchone()) == (None, None)
    assert con.execute("SELECT COUNT(*) FROM audit_log WHERE event='job_action' AND job_id=?", (jid(con, "DEMO-FILED"),)).fetchone()[0] == 2

# --- Q7: client-side user ---------------------------------------------------
def test_client_user_sees_only_own_client_and_cannot_act(con):
    assert can(con, "anil", "view", "DEMO-FILED")["allowed"]          # C01
    assert not can(con, "anil", "view", "DEMO-C05")["allowed"]        # other client
    assert not can(con, "anil", "prepare", "DEMO-ABSENT")["allowed"]
    assert not can(con, "anil", "cancel", "DEMO-FILED", reason="please")["allowed"]

# --- Q8: admin --------------------------------------------------------------
def test_admin_cannot_escalate_self(con):
    r = engine.grant_role(con, "asha", "asha", "controller", reason="mine", today=TODAY)
    assert not r["ok"] and "own access" in r["reason"]
    g = con.execute("SELECT id FROM grants WHERE user_id='asha'").fetchone()[0]
    assert not engine.revoke_grant(con, "asha", g, reason="x", today=TODAY)["ok"]

def test_admin_manages_others_and_it_takes_effect_immediately(con):
    assert not can(con, "kiran", "prepare", "DEMO-ABSENT")["allowed"]            # no grants: deny by default
    assert engine.grant_role(con, "asha", "kiran", "maker", branch_id="MUM", reason="joined MUM team", today=TODAY)["ok"]
    assert can(con, "kiran", "prepare", "DEMO-ABSENT")["allowed"]               # same day, no delay
    gid = con.execute("SELECT id FROM grants WHERE user_id='kiran'").fetchone()[0]
    assert engine.revoke_grant(con, "asha", gid, reason="moved", today=TODAY)["ok"]
    assert not can(con, "kiran", "prepare", "DEMO-ABSENT")["allowed"]
    assert con.execute("SELECT COUNT(*) FROM grants WHERE id=?", (gid,)).fetchone()[0] == 1  # kept for history

def test_non_admin_cannot_grant_and_admin_has_no_job_powers(con):
    assert not engine.grant_role(con, "ravi", "kiran", "maker", reason="x", today=TODAY)["ok"]
    assert not can(con, "asha", "prepare", "DEMO-ABSENT")["allowed"]
    assert not can(con, "asha", "cancel", "DEMO-FILED", reason="fix")["allowed"]

def test_grant_validation(con):
    assert not engine.grant_role(con, "asha", "kiran", "maker", today=TODAY)["ok"]                      # no reason
    assert not engine.grant_role(con, "asha", "anil", "maker", reason="x", today=TODAY)["ok"]           # client user, wrong role
    assert not engine.grant_role(con, "asha", "parser", "maker", reason="x", today=TODAY)["ok"]         # system user

# --- Q9: parser -------------------------------------------------------------
def test_parser_limits(con):
    scope = dict(client_id="C01", branch_id="MUM", direction="import", mode="air")
    assert engine.can(con, "parser", "create", new_job=scope, today=TODAY)["allowed"]
    assert can(con, "parser", "update", "DEMO-ABSENT")["allowed"]               # confirmed job
    assert not can(con, "parser", "update", "DEMO-FILED")["allowed"]            # filed: hands off
    assert not can(con, "parser", "check", "DEMO-NARROW-OK")["allowed"]
    assert not can(con, "parser", "cancel", "DEMO-FILED", reason="x")["allowed"]

# --- Q10 / Q14 --------------------------------------------------------------
def test_why_she_can_and_he_cant(con):
    d = engine.explain_diff(con, "neha", "rohit", "check", jid(con, "DEMO-NARROW-OK"), today=TODAY)
    assert d["a"]["allowed"] and not d["b"]["allowed"]
    assert "import" in d["b"]["reason"] or "export" in d["b"]["reason"]

def test_deny_by_default_when_unsure(con):
    assert not can(con, "kiran", "view", "DEMO-FILED")["allowed"]               # no grants
    assert not engine.can(con, "ghost", "view", 1, today=TODAY)["allowed"]       # unknown user
    assert not engine.can(con, "ravi", "teleport", 1, today=TODAY)["allowed"]    # unknown action
    assert not engine.can(con, "ravi", "view", 999999, today=TODAY)["allowed"]   # unknown job
    con.execute("UPDATE users SET status='disabled' WHERE id='ravi'")
    assert not can(con, "ravi", "view", "DEMO-FILED")["allowed"]                 # disabled user

# --- audit ------------------------------------------------------------------
def test_every_decision_is_logged_including_denials(con):
    before = con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    can(con, "kiran", "prepare", "DEMO-ABSENT"); can(con, "ravi", "prepare", "DEMO-ABSENT")
    rows = con.execute("SELECT allowed FROM audit_log WHERE id > ?", (before,)).fetchall()
    assert [r[0] for r in rows] == [0, 1]

def test_audit_log_is_append_only(con):
    with pytest.raises(Exception): con.execute("UPDATE audit_log SET reason='tampered'")
    with pytest.raises(Exception): con.execute("DELETE FROM audit_log")
