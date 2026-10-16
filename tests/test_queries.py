"""Q13 (waiting list == what can() allows), Q11 (who could have changed it), history."""
import pytest
from app import engine, queries
from app.seed import seed

TODAY = "2026-10-16"

@pytest.fixture
def con():
    return seed(":memory:")

def jid(con, ref): return con.execute("SELECT id FROM jobs WHERE ref=?", (ref,)).fetchone()[0]

def test_waiting_list_matches_can_for_every_user(con):
    """The core Q13 guarantee: for EVERY user, the jobs listed as 'waiting' are exactly
    the jobs where can() allows the stage's next action. Run on all 20 users x all jobs."""
    jobs = con.execute("SELECT id, stage FROM jobs").fetchall()
    for u in [r[0] for r in con.execute("SELECT id FROM users")]:
        listed = queries.waiting_for_me(con, u, today=TODAY, limit=10**6)
        listed_ids = {j["id"] for j in listed["jobs"]}
        expected = set()
        for j in jobs:
            act = queries.STAGE_TO_ACTION.get(j["stage"])
            if act and engine.can(con, u, act, j["id"], today=TODAY, log=False)["allowed"]:
                expected.add(j["id"])
        assert listed_ids == expected, f"drift for {u}: {listed_ids ^ expected}"
        assert listed["count"] == len(expected)

def test_waiting_list_respects_awkward_cases(con):
    neha = {j["ref"] for j in queries.waiting_for_me(con, "neha", today=TODAY, limit=10**6)["jobs"]}
    assert "DEMO-NARROW-OK" in neha and "DEMO-NARROW-NO" not in neha
    ravi = {j["ref"] for j in queries.waiting_for_me(con, "ravi", today=TODAY, limit=10**6)["jobs"]}
    assert "DEMO-MC-CONFLICT" not in ravi                                  # he prepared it
    assert queries.waiting_for_me(con, "imran", today=TODAY)["count"] == 0   # absent
    assert queries.waiting_for_me(con, "anil", today=TODAY)["count"] == 0    # client-side
    assert queries.waiting_for_me(con, "kiran", today=TODAY)["count"] == 0   # no grants

def test_waiting_list_changes_the_moment_access_changes(con):
    before = queries.waiting_for_me(con, "kiran", today=TODAY)["count"]
    engine.grant_role(con, "asha", "kiran", "maker", branch_id="MUM", reason="joined", today=TODAY)
    assert queries.waiting_for_me(con, "kiran", today=TODAY)["count"] > before

def test_history_records_decisions_and_actions(con):
    j = jid(con, "DEMO-ABSENT")
    engine.can(con, "kiran", "prepare", j, today=TODAY)                      # denied
    engine.perform(con, "ravi", "prepare", j, today=TODAY)                   # allowed
    allh = queries.job_history(con, j)
    assert [h["allowed"] for h in allh] == [0, 1, 1]                         # 2 decisions + 1 action
    changes = queries.job_history(con, j, decisions=False)
    assert len(changes) == 1 and changes[0]["actor"] == "ravi" and changes[0]["detail"]["to"] == "prepared"

def test_who_could_have_changed_it_on_a_past_date(con):
    j = jid(con, "DEMO-FILED")                                               # C01, MUM, import, FCL
    on_oct = {p["user"] for p in queries.who_could_change(con, j, "2026-10-10")["people"]}
    assert {"ravi", "neha", "sunita", "farah", "tushar", "vikram"} <= on_oct
    assert "kiran" not in on_oct and "anil" not in on_oct and "asha" not in on_oct
    # Imran was not yet absent on 10 Oct (absence starts 12 Oct) so he COULD have; on 13 Oct he could not.
    assert "imran" not in {p["user"] for p in queries.who_could_change(con, j, "2026-10-13")["people"]}
    # Karan's old Delhi grant ended 30 Sep: he never had authority over a Mumbai job anyway
    j2 = con.execute("INSERT INTO jobs(ref,client_id,branch_id,direction,mode,stage,owner_id,created_at,updated_at) "
                     "VALUES ('D9','C01','DEL','import','fcl','confirmed','karan','2026-09-01','2026-09-01')").lastrowid
    assert "karan" in {p["user"] for p in queries.who_could_change(con, j2, "2026-09-15")["people"]}   # old all-modes grant
    assert "karan" not in {p["user"] for p in queries.who_could_change(con, j2, "2026-10-16")["people"]}  # narrowed to air
