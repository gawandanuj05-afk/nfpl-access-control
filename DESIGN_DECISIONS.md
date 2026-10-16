# Design decisions (locked Friday night)

Read these. In the follow-up call, every one of them is a "why did you choose that?" question.

## Core model
- **One grant = one role in one scope** (client, branch, direction, mode). NULL = "all".
  Covers "Maker everywhere, Checker for 3 clients" (Ravi) and "Checker for one client, one branch,
  imports only" (Neha) with no special cases. Several grants per person are normal.
- **Roles map to actions in a table** (`role_actions`). New role next quarter = INSERT rows (Q12).
- **Deny by default.** No matching grant, missing data, unknown action, disabled user => DENY, with a reason (Q14).
- **Grants are never deleted.** Revoking sets `valid_to`. History is therefore reconstructable (Q11).
- **Audit log is append-only**, enforced by DB triggers. Denied attempts are logged too.

## Decision order inside `can(user, action, job)` (to build next)
1. User exists and is active, job exists, action is known.
2. Is there a grant, valid today, whose role includes the action AND whose scope matches the job?
   (Delegation can widen the *jobs* a person may act on, never the *roles* they hold.)
3. Does the job's stage allow this action?
   prepare: confirmed/reopened | check: prepared | file: checked
   cancel: any open stage, or filed | reopen: filed/cancelled
4. Separation of duties: nobody may check a job they prepared; nobody may file a job they checked? (see Assumptions)
5. Special rules: filed cancel/reopen needs controller + written reason; parser cannot touch filed jobs;
   client users are read-only and only their own client.
6. Return `{allowed, reason, matched_grant, failed_checks}` and write an audit row.

## Answers in brief (full text goes in the 2-4 page design doc)
| Q | Decision |
|---|---|
| 1 | Seeing and acting are separate. View = any matching grant in scope. Act = role + scope + stage. |
| 2 | Scope columns on grants (see Core model). |
| 3 | Maker may not check own preparation. Hard rule, no override in v1. Lata is the test case. |
| 4 | Absence is a date range. A delegation lets a named cover person act on the absent owner's jobs, only with roles they already hold. Expires by itself. |
| 5 | Narrowing a grant does not strand jobs: the job stays visible to its owner as "needs reassignment"; actions already stamped stay valid. Karan is the test case. |
| 6 | Only `controller`. Filed jobs additionally need a written reason. Every use is audited. |
| 7 | `client_viewer` role, client_id mandatory, view only. |
| 8 | Admin manages grants but has no job-action roles. Admin cannot grant or widen their own access. Fixing a stuck job goes through a controller with a reason. |
| 9 | Parser is a `system` user with create/update only, never on filed jobs, every call audited under its own identity. |
| 10 | Run `can` for both people and diff the failed checks. |
| 11 | Query grants whose validity window covers that date, then filter by scope + stage as it was. |
| 12 | Insert into `role_actions`. No code change. |
| 13 | "Waiting for me" is built from the same matching function as `can`. A test asserts counts are equal. |
| 14 | Deny and explain. Never guess in favour of access. |

## Assumptions (write these in the README)
- "Reopened" behaves like Confirmed: the job needs preparing again.
- A person can file a job they checked (only prepare->check separation enforced). Say so; easy to tighten.
- Access changes take effect immediately: every decision reads the DB, no cache, so no stale permissions.
- Absence uses calendar dates, not times.
- Admin has `view` so they can audit, but no work actions.

## Cut list (tell the reviewers)
- No real login. The API takes a `X-User` header (user id). Authentication is out of scope for an access-decision service.
- SQLite instead of Postgres. Fine for 200k jobs with the indexes above.
