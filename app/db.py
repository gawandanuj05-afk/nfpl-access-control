"""Database layer: schema + connection helper (SQLite, stdlib only)."""
import os, sqlite3

DB_PATH = os.environ.get("NFPL_DB", "nfpl.db")

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE branches (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE clients  (id TEXT PRIMARY KEY, name TEXT NOT NULL);

-- kind: staff | client (client-side employee) | system (e.g. parser)
-- status: active | disabled. Absence is a date range, not a status, so it
-- expires by itself and nobody has to remember to flip a flag back.
CREATE TABLE users (
  id TEXT PRIMARY KEY, name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('staff','client','system')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  absent_from TEXT, absent_until TEXT
);

-- owner_id = the person responsible for the job (Q4).
-- prepared_by / checked_by are stamped by the engine when those actions
-- happen; they drive the maker-checker rule (Q3).
CREATE TABLE jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE NOT NULL,
  client_id TEXT NOT NULL REFERENCES clients(id),
  branch_id TEXT NOT NULL REFERENCES branches(id),
  direction TEXT NOT NULL CHECK (direction IN ('import','export')),
  mode TEXT NOT NULL CHECK (mode IN ('air','fcl','lcl')),
  stage TEXT NOT NULL CHECK (stage IN
    ('confirmed','prepared','checked','filed','cancelled','reopened')),
  owner_id TEXT REFERENCES users(id),
  prepared_by TEXT, checked_by TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

-- Role -> actions lives in DATA, so a new role next quarter is an INSERT,
-- not a deploy (Q12).
CREATE TABLE role_actions (role TEXT NOT NULL, action TEXT NOT NULL,
                           PRIMARY KEY (role, action));

-- One grant = one role in one scope. NULL in a scope column means "all".
-- Grants are never overwritten or deleted: revoking sets valid_to, so we can
-- reconstruct who held what on any past date (Q11).
CREATE TABLE grants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL REFERENCES users(id),
  role TEXT NOT NULL,
  client_id TEXT REFERENCES clients(id),
  branch_id TEXT REFERENCES branches(id),
  direction TEXT CHECK (direction IN ('import','export')),
  mode TEXT CHECK (mode IN ('air','fcl','lcl')),
  valid_from TEXT NOT NULL, valid_to TEXT,        -- valid_to NULL = open-ended
  created_by TEXT NOT NULL, reason TEXT,
  revoked_by TEXT
);

-- Temporary cover for an absent person: delegate may act on jobs OWNED by
-- from_user inside the window, but only with roles they already hold.
CREATE TABLE delegations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_user TEXT NOT NULL REFERENCES users(id),
  to_user   TEXT NOT NULL REFERENCES users(id),
  valid_from TEXT NOT NULL, valid_to TEXT NOT NULL,
  created_by TEXT NOT NULL, reason TEXT
);

-- Append-only: every decision (allowed OR denied) and every change.
CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, actor TEXT NOT NULL,
  event TEXT NOT NULL,          -- decision | job_action | grant_change | delegation | ...
  job_id INTEGER, action TEXT, allowed INTEGER,
  reason TEXT, detail TEXT      -- detail = JSON
);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log
  BEGIN SELECT RAISE(ABORT,'audit_log is append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log
  BEGIN SELECT RAISE(ABORT,'audit_log is append-only'); END;

-- Indexes for the 200k-job case: the "waiting for me" list filters on
-- stage + scope columns, so index those.
CREATE INDEX ix_jobs_stage_scope ON jobs(stage, client_id, branch_id, direction, mode);
CREATE INDEX ix_jobs_owner   ON jobs(owner_id);
CREATE INDEX ix_jobs_client  ON jobs(client_id);
CREATE INDEX ix_grants_user  ON grants(user_id, valid_from, valid_to);
CREATE INDEX ix_audit_job    ON audit_log(job_id, ts);
CREATE INDEX ix_audit_actor  ON audit_log(actor, ts);
"""

def connect(path=None):
    con = sqlite3.connect(path or DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def init_db(path=None):
    p = path or DB_PATH
    if p != ":memory:" and os.path.exists(p):
        os.remove(p)
    con = connect(p)
    con.executescript(SCHEMA)
    return con
