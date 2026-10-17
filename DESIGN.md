# Design Document: NFPL Access Control Service

## 1. The model in one page

**Three separate questions, kept separate.**
1. *Who is this person?* (`users`: staff, client-side, or system; active/disabled; an optional absence date range.)
2. *What authority do they hold, and where?* (`grants`: one role in one scope.)
3. *What may happen to this job right now?* (the workflow: stage rules in code.)

An action is allowed only when all three agree. Keeping them apart is what makes each rule easy to explain.

**Grants.** One grant = one role over a scope of `client, branch, direction, mode`; an empty field means "all". A person has several grants.
Every grant carries `valid_from`, an optional `valid_to`, who created it and why. Grants are never deleted or overwritten: revoking sets the end date to yesterday, so access stops immediately and the row stays as history.
Access is **additive only**: there are no "deny" grants, so a person's authority is always the plain union of what they were given.

**Roles are data.** `role_actions` maps role to actions (`maker: prepare`, `checker: check`, `filer: file`, `controller: cancel, reopen`, `parser: create, update`, ...).
**Workflow is code.** `STAGE_RULES` says which stage permits which action (prepare on Confirmed/Reopened, check on Prepared, file on Checked, and so on).

**The decision** (`can`) runs checks in a fixed order and stops at the first failure: user active, action known, job exists, absence, client-side read-only, grant (or delegation) covering the job, stage, maker-checker, written reason where required.
It returns `allowed`, a plain-English reason, the grant that matched, and every check it ran. Every decision, allowed or denied, is appended to an **append-only audit log** (database triggers reject updates and deletes).

**Principles.** Deny by default. Nothing is cached, so a change applies on the very next request. One rule, many views: the same rule drives the decision, the explanation, the waiting list and the history.

## 2. Answers to the questions

**1. Should everyone see everything?** No. Seeing and acting are different. *Seeing* needs any valid grant whose scope covers the job (every role includes `view`), so a Mumbai maker does not see Chennai jobs, and a client-side user sees only their own client. *Acting* additionally needs a role that contains the action, the right job stage, and passing the rules below. Someone can therefore see a job they may not touch.

**2. Maker for every client but Checker for few; Checker for one client, one branch, imports only.** These are just grants, no special cases. Ravi has one `maker` grant with every field empty, plus three `checker` grants (C01, C02, C03). Neha has one `checker` grant: client C01, branch MUM, direction import. The README writes each person out as "Person has role R for client, branch, direction, mode", generated from the data. Trade-off: many narrow grants are verbose to read; the plain-English printout is the mitigation.

**3. The preparer is also qualified to approve.** Qualification is not enough: nobody may check a job they prepared (maker-checker, hard rule, no override in v1). Lata holds both roles and is blocked on her own work, while Neha can check it. Reopening a job clears who prepared and checked it, so the rule starts fresh. Assumption: one person may check and then file the same job; only prepare-then-check is separated (easy to tighten).

**4. The responsible person is absent.** Absence is a date range, so it ends by itself. An absent person cannot act (they can still look). The `owner` is a marker of responsibility, not a lock: anyone else holding the role in scope can still act. For explicit cover, an admin records a *delegation*: the delegate may act on jobs owned by the absent person for a window. Delegation widens **which jobs**, never **which roles**: Karan (Delhi air maker) can cover Imran's Mumbai job only for actions his own roles allow. Gap: no automatic alert listing jobs whose owner is absent.

**5. A person's responsibilities change mid-way.** Narrowing a grant ends the old one and adds a new one (Karan: Delhi all modes until 30 Sep, Delhi air-only from 1 Oct). The effect is immediate: those jobs leave his waiting list and he can no longer act on them, while work already stamped on a job stays valid and in the history. Anyone else holding the role picks the jobs up. Gap: no dedicated "needs reassignment" view; owners are not auto-changed.

**6. Cancel a filed job or reopen a closed one.** Only the `controller` role, which holds nothing else that does job work. Cancelling a filed job and any reopen need a written reason, and every use is audited. A reopen sends the job back to preparation. Trade-off: one controller plus a reason is lighter than two-person approval; a second approver is the obvious next control (cut for time).

**7. A client's own employee follows their shipments.** `client_viewer` role, tied to exactly one client (the grant is rejected otherwise), view only. Even if given other grants, the engine refuses any action from a client-side user. Anil sees C01 jobs and nothing else.

**8. Admin fixes a stuck job / admin makes themselves more powerful.** The admin manages access but holds no job-work roles, so they cannot prepare, cancel or file. A stuck job goes to a controller with a reason, which keeps the audit trail clean. An admin **cannot grant, revoke or change their own access** (another admin must), every grant needs a reason, and every attempt, including refused ones, is logged. Residual risk: two admins could collude, and an admin can create another admin; the log makes that visible but does not prevent it.

**9. The overnight parser.** A `system` user holding a `parser` role: create and update only, and only on jobs that are not filed or cancelled. It cannot prepare, check, file, cancel or reopen, and it cannot hold any other role. Each call is audited under its own identity. Gap: the decision and tests exist, but the job-ingest endpoint itself is not built.

**10. "Why can she do this and he can't?"** `explain` runs the same decision for both people and shows every check side by side. A refusal names the near miss: "Rohit holds [checker, export only] but this job is C01, MUM, import."

**11. "Who could have changed this job on the 3rd?"** Because grants are dated and never overwritten, the service rebuilds who held authority over the job's scope on any date, minus people absent that day, plus delegates, alongside the actions actually recorded. "Could" means held authority, not "did". Limit: only each person's current absence range is stored.

**12. A new role next quarter while engineering is busy.** Roles are rows in `role_actions`; an admin can then grant them through the normal API with an audit trail. No deploy for a new *combination of existing actions*. A brand-new *action* or stage rule does need code. This is the honest boundary of the design.

**13. "Jobs waiting for me" matches what they can do.** The waiting list is the decision rule written as one SQL query (grant valid today, role includes the stage's next action, scope covers the job, maker-checker, absence, delegation). A test compares it with `can()` for **every user against every job** and fails on any difference. Trade-off: the rule exists twice (Python and SQL), kept in step by that test instead of by a single source.

**14. When the system is unsure.** Deny, explain, and log: unknown user, disabled user, unknown action, missing job, incomplete data, an error inside the API. Never guess in favour of access.

## 3. Questions I added

**15. Can someone be given broad access minus a few exceptions?** Not in v1. Additive-only grants are easy to reason about, and "who can do X" is the union of grants. Exceptions would need deny rules and an order of precedence. If needed, the workaround is several narrower grants.

**16. Who may read the audit log and history?** In this build, anyone who reaches the API, because there is no login (see below). In production these endpoints should be limited to admins and controllers.

**17. A person leaves the company.** Disable the user: every decision denies at once, and their grants and history stay for investigation.

## 4. Key trade-offs and what was cut

- **Standard library HTTP server and SQLite** instead of a framework and Postgres: zero dependencies, runs anywhere. Measured on the scale case (500 users, 200,000 jobs): "waiting for me" median 64 ms, p95 82 ms. A framework and a server database are the next step for concurrency.
- **No authentication.** The caller is the `X-User` header. Authenticating people is a separate concern; a gateway would set that header.
- **Cut:** a grants-management screen (the API does it and is tested), two-person approval for filed cancels, owner-absent alerts, the parser's job-ingest endpoint, and persistence on the free demo host (data resets on restart).

## 5. Testing

23 automated tests: scoped roles, narrow checker, maker-checker, absent user, delegation, changed responsibility by date, filed cancel and reopen, client-side user, admin self-escalation, grant validation, parser limits, deny-by-default, audit append-only, history, who-could-change, and the waiting list matching `can()` for all users.
