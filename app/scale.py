"""Scale case: 500 users, 200,000 jobs.   python -m app.scale   (writes scale.db, prints timings)"""
import os, random, sys, time
from .db import init_db, connect
from .seed import BRANCHES, ROLE_ACTIONS
from .queries import waiting_for_me

def build(path="scale.db", n_users=500, n_jobs=200_000, seed=7):
    rnd = random.Random(seed)
    con = init_db(path)
    clients = [(f"C{i:03d}", f"Client {i}") for i in range(1, 41)]
    con.executemany("INSERT INTO branches VALUES (?,?)", BRANCHES)
    con.executemany("INSERT INTO clients VALUES (?,?)", clients)
    con.executemany("INSERT INTO role_actions VALUES (?,?)", [(r, a) for r, acts in ROLE_ACTIONS.items() for a in acts])
    users, grants = [("admin", "Admin", "staff"), ("controller", "Controller", "staff"), ("parser", "Parser", "system")], []
    grants += [("admin", "admin", None, None, None, None), ("controller", "controller", None, None, None, None),
               ("parser", "parser", None, None, None, None)]
    staff = []
    for i in range(1, n_users - 3 + 1):
        uid = f"u{i:03d}"
        kind = "client" if i % 10 == 0 else "staff"
        users.append((uid, f"User {i}", kind))
        if kind == "client":
            grants.append((uid, "client_viewer", rnd.choice(clients)[0], None, None, None)); continue
        staff.append(uid)
        for _ in range(rnd.randint(1, 3)):   # 1-3 scoped grants each
            grants.append((uid, rnd.choice(["maker", "checker", "filer"]),
                           rnd.choice([None, rnd.choice(clients)[0]]), rnd.choice([None, rnd.choice(BRANCHES)[0]]),
                           rnd.choice([None, "import", "export"]), rnd.choice([None, "air", "fcl", "lcl"])))
    con.executemany("INSERT INTO users(id,name,kind) VALUES (?,?,?)", users)
    con.executemany("""INSERT INTO grants(user_id,role,client_id,branch_id,direction,mode,valid_from,created_by,reason)
                       VALUES (?,?,?,?,?,?,'2025-01-01','admin','scale data')""", grants)
    stages = ["confirmed"] * 30 + ["prepared"] * 25 + ["checked"] * 20 + ["filed"] * 18 + ["cancelled"] * 4 + ["reopened"] * 3
    rows = []
    for i in range(1, n_jobs + 1):
        st = rnd.choice(stages); prep = rnd.choice(staff) if st in ("prepared", "checked", "filed") else None
        chk = rnd.choice(staff) if st in ("checked", "filed") else None
        rows.append((f"SC-{i:06d}", rnd.choice(clients)[0], rnd.choice(BRANCHES)[0], rnd.choice(["import", "export"]),
                     rnd.choice(["air", "fcl", "lcl"]), st, rnd.choice(staff), prep, chk, "2026-09-15", "2026-09-15"))
    con.executemany("""INSERT INTO jobs(ref,client_id,branch_id,direction,mode,stage,owner_id,prepared_by,checked_by,
                       created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""", rows)
    con.commit(); con.execute("ANALYZE"); con.commit()
    return con

def benchmark(con, today="2026-10-16", sample=25):
    rnd = random.Random(1)
    ids = [r[0] for r in con.execute("SELECT id FROM users WHERE kind='staff' AND id LIKE 'u%'")]
    times = []
    for uid in rnd.sample(ids, sample):
        t = time.perf_counter(); waiting_for_me(con, uid, today=today); times.append((time.perf_counter() - t) * 1000)
    times.sort()
    return {"queries": sample, "median_ms": round(times[len(times) // 2], 1), "p95_ms": round(times[int(len(times) * .95) - 1], 1), "max_ms": round(times[-1], 1)}

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "scale.db"
    t = time.time(); c = build(path)
    u, j = (c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("users", "jobs"))
    g = c.execute("SELECT COUNT(*) FROM grants").fetchone()[0]
    print(f"Built {u} users, {g} grants, {j} jobs in {time.time() - t:.1f}s -> {path}")
    print("waiting_for_me timings:", benchmark(c))
