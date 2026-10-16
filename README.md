# NFPL Access Control Service

Decides **who may do what on which job**, explains every answer, and keeps a history that answers
"who could have changed this job on the 3rd?". Built for the Nagarkot take-home assignment.

- **Live demo:** _add your hosted link here_
- **Design document:** [DESIGN.md](DESIGN.md)  |  **Decision log:** [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md)

No dependencies: Python 3.10+ standard library only (SQLite included). `pytest` is needed only to run tests.

## Run it locally

```bash
python3 -m app.seed                                # load sample data (5 branches, 10 clients, 20 users, 307 jobs)
NFPL_TODAY=2026-10-16 python3 -m app.api           # start the service
```
Open **http://localhost:8000** for the web page, or **http://localhost:8000/api** for the endpoint list.
`NFPL_TODAY` pins "today" so the sample absence (Imran, 12 to 23 Oct 2026) behaves as documented. Without it the real date is used.

```bash
pip3 install pytest && python3 -m pytest -q        # 23 tests
python3 -m app.scale                               # scale case: 500 users, 200,000 jobs, prints timings
python3 -m app.describe                            # prints the access list below, generated from the data
```

## Try it in 2 minutes

Use the web page: pick a person, open `DEMO-NARROW-OK`, then compare **Neha Shah vs Rohit Das** on `check`.
Or use the API (job ids: `DEMO-MC-CONFLICT`=301, `DEMO-NARROW-OK`=302, `DEMO-NARROW-NO`=303, `DEMO-ABSENT`=304, `DEMO-FILED`=305, `DEMO-LATA`=306, `DEMO-C05`=307):

```bash
# May Neha check job 302 (import)? And 303 (export)? The answer comes with a reason.
curl "localhost:8000/api/can?user=neha&action=check&job=302"
curl "localhost:8000/api/can?user=neha&action=check&job=303"

# Why can she and he can't?
curl "localhost:8000/api/explain?a=neha&b=rohit&action=check&job=302"

# Jobs waiting for a person (same rules as can())
curl "localhost:8000/api/waiting?user=ravi&limit=5"

# Do something (caller identified by the X-User header). Filed-job cancel needs a reason:
curl -X POST -H "X-User: vikram" -d '{"reason":"Client withdrew"}' localhost:8000/api/jobs/305/actions/cancel

# History of a job, and who could have changed it on a given date:
curl "localhost:8000/api/jobs/305/history"
curl "localhost:8000/api/jobs/305/who-could-change?date=2026-10-10"

# Admin: grant access (admin cannot change their own):
curl -X POST -H "X-User: asha" -d '{"user":"kiran","role":"maker","branch":"MUM","reason":"Joined Mumbai team"}' localhost:8000/api/grants
curl -X POST -H "X-User: asha" -d '{"user":"asha","role":"controller","reason":"me"}' localhost:8000/api/grants   # refused
```

## How a decision is made

`can(user, action, job)` runs these checks in order and stops at the first failure, returning the reason and every check it ran:
user active, action known, job exists, absence, client-side users read-only, a valid grant whose role includes the action and whose scope
(client, branch, direction, mode) covers the job (or delegation from an absent owner), the job's stage allows the action,
maker-checker separation, and a written reason for cancel-of-filed and reopen. Anything unclear is **denied**. Every decision, allowed or denied, is written to an append-only audit log.

## Who has what (sample data)

"Person has role R for client, branch, direction, mode" -- "all" means no restriction. Roles: `maker` prepares, `checker` checks,
`filer` files, `controller` may cancel/reopen, `viewer`/`client_viewer` read only, `admin` manages access (no job work), `parser` is the overnight system user.

**Asha Kulkarni** (staff)
  - Has role **admin** for all clients, all branches, both directions, all modes (since 2025-01-01).
**Vikram Rao** (staff)
  - Has role **controller** for all clients, all branches, both directions, all modes (since 2025-01-01).
**Ravi Menon** (staff)
  - Has role **checker** for client Sunrise Textiles, all branches, both directions, all modes (since 2025-06-01).
  - Has role **checker** for client Bharat Pharma, all branches, both directions, all modes (since 2025-06-01).
  - Has role **checker** for client Orion Auto Parts, all branches, both directions, all modes (since 2025-06-01).
  - Has role **maker** for all clients, all branches, both directions, all modes (since 2025-01-01).
**Neha Shah** (staff)
  - Has role **checker** for client Sunrise Textiles, branch Mumbai, imports only, all modes (since 2025-03-01).
**Imran Qureshi** (staff) — absent 2026-10-12 to 2026-10-23
  - Has role **maker** for all clients, branch Mumbai, both directions, all modes (since 2025-01-01).
**Sunita Patil** (staff)
  - Has role **maker** for all clients, branch Mumbai, both directions, all modes (since 2025-01-01).
**Karan Joshi** (staff)
  - Has role **maker** for all clients, branch Delhi, both directions, all modes (since 2025-01-01, ended 2026-09-30).
  - Has role **maker** for all clients, branch Delhi, both directions, AIR only (since 2026-10-01).
**Deepa Nair** (staff)
  - Has role **checker** for all clients, branch Chennai, both directions, all modes (since 2025-01-01).
  - Has role **maker** for all clients, branch Chennai, both directions, all modes (since 2025-01-01).
**Arjun Bose** (staff)
  - Has role **checker** for all clients, branch Kolkata, both directions, all modes (since 2025-01-01).
**Farah Khan** (staff)
  - Has role **filer** for all clients, all branches, both directions, all modes (since 2025-01-01).
**Tushar Desai** (staff)
  - Has role **filer** for all clients, branch Mumbai, both directions, all modes (since 2025-01-01).
**Lata Iyer** (staff)
  - Has role **checker** for all clients, branch Ahmedabad, both directions, all modes (since 2025-01-01).
  - Has role **maker** for all clients, branch Ahmedabad, both directions, all modes (since 2025-01-01).
**Manoj Verma** (staff)
  - Has role **viewer** for all clients, all branches, both directions, all modes (since 2025-01-01).
**Pooja Singh** (staff)
  - Has role **maker** for all clients, all branches, both directions, AIR only (since 2025-01-01).
**Rohit Das** (staff)
  - Has role **checker** for all clients, all branches, exports only, all modes (since 2025-01-01).
**Sneha Kulkarni** (staff)
  - Has role **filer** for all clients, branch Delhi, both directions, all modes (since 2025-01-01).
  - Has role **filer** for all clients, branch Chennai, both directions, all modes (since 2025-01-01).
**Anil Mehta** (client)
  - Has role **client_viewer** for client Sunrise Textiles, all branches, both directions, all modes (since 2025-01-01).
**Zoya Ali** (client)
  - Has role **client_viewer** for client Delta Electronics, all branches, both directions, all modes (since 2025-01-01).
**Overnight Parser** (system)
  - Has role **parser** for all clients, all branches, both directions, all modes (since 2025-01-01).
**Kiran Pillai** (staff)
  - No grants: can do nothing (deny by default).

Delegation: sunita covers jobs owned by imran from 2026-10-12 to 2026-10-23.

Awkward cases built on purpose: **Ravi** (Maker everywhere, Checker for only C01 to C03), **Neha** (Checker for one client, one branch, imports only),
**Imran** (absent, covered by Sunita), **Karan** (responsibilities narrowed on 1 Oct), **Lata** (Maker and Checker in the same scope),
**Anil / Zoya** (client-side), **Asha** (admin), **Overnight Parser** (system), **Kiran** (no grants).

## Scale

`python3 -m app.scale` builds 500 users, ~967 grants and 200,000 jobs (about 1.4 s on a MacBook Air) and times "jobs waiting for me" for 25 users:
**median 64 ms, p95 82 ms, max 101 ms.** Speed comes from one indexed SQL query over `jobs(stage, client, branch, direction, mode)` instead of calling the decision engine per job.

## Assumptions (where the brief was silent)

- **No login.** Acting endpoints trust the `X-User` header. Authentication is out of scope for an access-decision service; behind real login a gateway would set it.
- **Reopened** jobs behave like Confirmed: they must be prepared again, and who prepared/checked is cleared so maker-checker starts fresh.
- A person **may file a job they checked**; only prepare-then-check by the same person is blocked. Easy to tighten.
- The **admin has no job-work roles**. Stuck jobs are fixed by a controller with a written reason.
- **Absence** is a date range (calendar days). An absent person cannot act but can still view.
- **Delegation** widens which jobs someone may act on (jobs owned by the absent person), never which roles they hold.
- **Access changes apply immediately**: nothing is cached; revoking sets the grant's end date to yesterday and keeps the row for history.
- "Who could have changed it" reports who **held authority**, not who acted; it knows only each person's current absence range.

## What I cut, and why

- Real authentication/sessions (out of scope, see above).
- A UI for managing grants (the API does it, and is tested); the page focuses on the decision, waiting list and history.
- Multi-step approvals (for example two controllers for a filed cancel): a written reason plus the audit trail is the v1 control.
- Postgres and caching: SQLite with indexes handles 200,000 jobs in tens of milliseconds.
- On the free host the database is re-seeded on each restart, so changes made on the live demo do not persist.

## Layout

```
app/db.py       schema (grants with validity dates, append-only audit log, indexes)
app/seed.py     sample data      app/describe.py  plain-English access list
app/engine.py   can(), perform(), grant_role(), revoke_grant()
app/queries.py  waiting list, job history, who-could-change
app/api.py      HTTP API + serves app/static/index.html
app/scale.py    500-user / 200k-job generator + benchmark
tests/          23 tests: maker/checker, absent owner, changed responsibility, filed cancel/reopen,
                admin self-escalation, parser, client user, deny-by-default, waiting list == can() for every user
```
