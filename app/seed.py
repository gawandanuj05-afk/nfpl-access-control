"""Deterministic sample data. Run:  python -m app.seed
Every person is deliberate: each one exists to exercise an edge case."""
import json, random, sys
from .db import init_db

NOW = "2026-10-16"   # "today" for the sample world

BRANCHES = [("MUM","Mumbai"),("DEL","Delhi"),("CHE","Chennai"),
            ("KOL","Kolkata"),("AMD","Ahmedabad")]
CLIENTS = [("C01","Sunrise Textiles"),("C02","Bharat Pharma"),("C03","Orion Auto Parts"),
           ("C04","Kaveri Foods"),("C05","Delta Electronics"),("C06","Himalaya Handicrafts"),
           ("C07","Pioneer Chemicals"),("C08","Lotus Gems"),("C09","Zenith Steel"),
           ("C10","Coastal Seafoods")]

# role -> actions (data, not code: Q12)
ROLE_ACTIONS = {
  "viewer":        ["view"],
  "client_viewer": ["view"],
  "maker":         ["view","prepare"],
  "checker":       ["view","check"],
  "filer":         ["view","file"],
  "controller":    ["view","cancel","reopen"],   # high authority (Q6)
  "admin":         ["view","manage_grants"],     # manages access, does not do job work (Q8)
  "parser":        ["view","create","update"],   # system identity (Q9)
}

# id, name, kind, absent_from, absent_until
USERS = [
  ("asha",   "Asha Kulkarni",  "staff", None, None),   # admin
  ("vikram", "Vikram Rao",     "staff", None, None),   # controller
  ("ravi",   "Ravi Menon",     "staff", None, None),   # Maker everywhere, Checker for 3 clients
  ("neha",   "Neha Shah",      "staff", None, None),   # Checker: C01 + MUM + import only
  ("imran",  "Imran Qureshi",  "staff", "2026-10-12", "2026-10-23"),  # ABSENT owner
  ("sunita", "Sunita Patil",   "staff", None, None),   # covers Imran
  ("karan",  "Karan Joshi",    "staff", None, None),   # responsibilities changed
  ("deepa",  "Deepa Nair",     "staff", None, None),   # Chennai maker + checker
  ("arjun",  "Arjun Bose",     "staff", None, None),   # Kolkata checker
  ("farah",  "Farah Khan",     "staff", None, None),   # filer everywhere
  ("tushar", "Tushar Desai",   "staff", None, None),   # filer Mumbai
  ("lata",   "Lata Iyer",      "staff", None, None),   # Maker AND Checker same scope (Q3)
  ("manoj",  "Manoj Verma",    "staff", None, None),   # read-only, sees all
  ("pooja",  "Pooja Singh",    "staff", None, None),   # maker, air only
  ("rohit",  "Rohit Das",      "staff", None, None),   # checker, export only
  ("sneha",  "Sneha Kulkarni", "staff", None, None),   # filer Delhi + Chennai
  ("anil",   "Anil Mehta",     "client", None, None),  # client-side, C01
  ("zoya",   "Zoya Ali",       "client", None, None),  # client-side, C05
  ("parser", "Overnight Parser","system", None, None), # automated
  ("kiran",  "Kiran Pillai",   "staff", None, None),   # new joiner, NO grants
]

# user, role, client, branch, direction, mode, valid_from, valid_to, reason
G = [
 ("asha","admin",None,None,None,None,"2025-01-01",None,"Platform admin"),
 ("vikram","controller",None,None,None,None,"2025-01-01",None,"Head of operations"),
 ("ravi","maker",None,None,None,None,"2025-01-01",None,"Maker for every client"),
 ("ravi","checker","C01",None,None,None,"2025-06-01",None,"Checker for select clients"),
 ("ravi","checker","C02",None,None,None,"2025-06-01",None,"Checker for select clients"),
 ("ravi","checker","C03",None,None,None,"2025-06-01",None,"Checker for select clients"),
 ("neha","checker","C01","MUM","import",None,"2025-03-01",None,"Narrow checker"),
 ("imran","maker",None,"MUM",None,None,"2025-01-01",None,"Mumbai maker"),
 ("sunita","maker",None,"MUM",None,None,"2025-01-01",None,"Mumbai maker"),
 ("karan","maker",None,"DEL",None,None,"2025-01-01","2026-09-30","Was Delhi maker, all modes"),
 ("karan","maker",None,"DEL",None,"air","2026-10-01",None,"Narrowed to Delhi air only"),
 ("deepa","maker",None,"CHE",None,None,"2025-01-01",None,"Chennai maker"),
 ("deepa","checker",None,"CHE",None,None,"2025-01-01",None,"Chennai checker"),
 ("arjun","checker",None,"KOL",None,None,"2025-01-01",None,"Kolkata checker"),
 ("farah","filer",None,None,None,None,"2025-01-01",None,"Filer everywhere"),
 ("tushar","filer",None,"MUM",None,None,"2025-01-01",None,"Mumbai filer"),
 ("lata","maker",None,"AMD",None,None,"2025-01-01",None,"Ahmedabad maker"),
 ("lata","checker",None,"AMD",None,None,"2025-01-01",None,"Ahmedabad checker (conflict case)"),
 ("manoj","viewer",None,None,None,None,"2025-01-01",None,"Read-only oversight"),
 ("pooja","maker",None,None,None,"air","2025-01-01",None,"Air maker, all branches"),
 ("rohit","checker",None,None,"export",None,"2025-01-01",None,"Export checker"),
 ("sneha","filer",None,"DEL",None,None,"2025-01-01",None,"Delhi filer"),
 ("sneha","filer",None,"CHE",None,None,"2025-01-01",None,"Chennai filer"),
 ("anil","client_viewer","C01",None,None,None,"2025-01-01",None,"Sunrise Textiles employee"),
 ("zoya","client_viewer","C05",None,None,None,"2025-01-01",None,"Delta Electronics employee"),
 ("parser","parser",None,None,None,None,"2025-01-01",None,"Overnight job feed"),
]

def seed(path=None, n_jobs=300):
    con = init_db(path)
    con.executemany("INSERT INTO branches VALUES (?,?)", BRANCHES)
    con.executemany("INSERT INTO clients VALUES (?,?)", CLIENTS)
    con.executemany("INSERT INTO role_actions VALUES (?,?)",
        [(r, a) for r, acts in ROLE_ACTIONS.items() for a in acts])
    con.executemany("INSERT INTO users(id,name,kind,absent_from,absent_until) VALUES (?,?,?,?,?)", USERS)
    for g in G:
        con.execute("""INSERT INTO grants(user_id,role,client_id,branch_id,direction,mode,
                       valid_from,valid_to,created_by,reason) VALUES (?,?,?,?,?,?,?,?,'asha',?)""",
                    (*g[:6], g[6], g[7], g[8]))
    con.execute("""INSERT INTO delegations(from_user,to_user,valid_from,valid_to,created_by,reason)
                   VALUES ('imran','sunita','2026-10-12','2026-10-23','asha','Imran on leave')""")

    rnd = random.Random(42)
    owners = {"MUM":["imran","sunita"],"DEL":["karan"],"CHE":["deepa"],
              "KOL":["arjun"],"AMD":["lata"]}
    stages = ["confirmed"]*30 + ["prepared"]*25 + ["checked"]*20 + ["filed"]*18 + ["cancelled"]*4 + ["reopened"]*3
    makers = ["ravi","sunita","imran","karan","deepa","lata","pooja"]
    checkers = ["ravi","neha","deepa","arjun","lata","rohit"]
    for i in range(1, n_jobs + 1):
        br = rnd.choice([b for b,_ in BRANCHES]); cl = rnd.choice([c for c,_ in CLIENTS])
        st = rnd.choice(stages)
        prep = rnd.choice(makers) if st in ("prepared","checked","filed") else None
        chk = rnd.choice([c for c in checkers if c != prep]) if st in ("checked","filed") else None
        day = f"2026-09-{rnd.randint(1,28):02d}"
        con.execute("""INSERT INTO jobs(ref,client_id,branch_id,direction,mode,stage,owner_id,
                       prepared_by,checked_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (f"NFPL-{i:05d}", cl, br, rnd.choice(["import","export"]), rnd.choice(["air","fcl","lcl"]),
             st, rnd.choice(owners[br]), prep, chk, day, day))
    # Hand-placed jobs so every edge case has a known target for tests + demo
    def J(ref, cl, br, d, m, st, owner, prep=None, chk=None):
        con.execute("""INSERT INTO jobs(ref,client_id,branch_id,direction,mode,stage,owner_id,
            prepared_by,checked_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,'2026-10-01','2026-10-01')""",
            (ref,cl,br,d,m,st,owner,prep,chk))
    J("DEMO-MC-CONFLICT","C01","MUM","import","fcl","prepared","sunita",prep="ravi")   # Ravi prepared it, is also C01 checker
    J("DEMO-NARROW-OK",  "C01","MUM","import","air","prepared","sunita",prep="sunita") # Neha may check
    J("DEMO-NARROW-NO",  "C01","MUM","export","air","prepared","sunita",prep="sunita") # Neha may NOT (export)
    J("DEMO-ABSENT",     "C02","MUM","import","fcl","confirmed","imran")              # owner absent
    J("DEMO-FILED",      "C01","MUM","import","fcl","filed","sunita","sunita","neha") # filed: cancel/reopen
    J("DEMO-LATA",       "C03","AMD","export","lcl","prepared","lata",prep="lata")    # same person maker+checker
    J("DEMO-C05",        "C05","DEL","import","air","confirmed","karan")              # Zoya's client
    con.execute("""INSERT INTO audit_log(ts,actor,event,detail,reason) VALUES
        (?,?,?,?,?)""", (NOW+"T09:00:00","system","seed",json.dumps({"jobs":n_jobs+7}),"Initial sample data load"))
    con.commit()
    return con

if __name__ == "__main__":
    c = seed(sys.argv[1] if len(sys.argv) > 1 else None)
    n = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    print(f"Seeded: {len(BRANCHES)} branches, {len(CLIENTS)} clients, {len(USERS)} users, {n} jobs")
