# Home OS Assistant Operator — Design

## Intent
Give the authenticated Home OS assistant bounded, typed tools for reading and modifying current household data through validated domain services. The operator is for household owners and members; it must not bypass the signed-in user's role or tenant boundary.

## Goals
- Cover finance, shopping/products, inventory, chores, and household information through the same server-side tool loop.
- Execute clear ordinary writes directly, with transactional idempotency and audit.
- Require exact preview and explicit confirmation for deletions, bulk changes, access changes, household archival, and account deactivation.
- Preserve financial and audit history. No physical deletion of financial/audit rows.
- When a household is archived, all existing members retain read-only access to retained data; no new mutations, members, invitations, or purchases.
- Block account deactivation while the user remains an owner of an active household; require ownership transfer or archive first. Support both assistant-proposed and separate security-settings flows, sharing the same backend service.
- Deactivate/anonymize the account while retaining finance and audit records.

## Non-goals
- Arbitrary SQL/ORM or model-generated API URLs.
- Banking transfers, credentials, passwords, provider tokens, or authentication factors in assistant messages/tools.
- Production or `main` deployment.
- Claiming full coverage when a route/action remains unsupported.

## Approaches considered
1. Expose general HTTP/ORM capabilities to the model: rejected because the model could cross household boundaries, invoke unvalidated mutations, or bypass audit.
2. Keep the assistant text-only: rejected because the user explicitly authorized a platform operator.
3. Use a typed allowlist that calls validated services, with persisted confirmation proposals for sensitive actions: selected because it preserves server authorization and domain invariants while enabling the requested operations.

## Architecture
A server-side Responses API function-call loop exposes only typed tools. The server derives actor/household from the authenticated request; each handler checks membership/role, uses bounded validated domain services, writes audit events transactionally, and uses a request-bound idempotency key. Sensitive operations create actor-bound, household-bound, expiring proposals containing a preview and exact revalidation snapshot. Confirmation rechecks permission and snapshot under lock before the mutation. The frontend renders proposal previews and accessible confirm/cancel controls. Household archival and account deactivation use dedicated domain services exposed through both the assistant and security UI.

## Constraints and decisions
- User selected read-only retained access for all remaining members of an archived household.
- User selected blocking self-deactivation until active owner duties are transferred or the household is archived.
- User selected both assistant-proposal and separate security-settings entry points for account deactivation.
- Retain finance and audit history; anonymize/deactivate accounts rather than deleting historical rows.
- Use existing app services and audit semantics; no secret material in prompts, tool inputs, assistant history, or logs.
- Tests use `HOME_OS_TEST_SQLITE=true`; provider calls are mocked. Never run real OAuth.
- Work only on `module/assistant-actions` based on `origin/tests`; deploy only to `tests` after full validation and independent review.

## Acceptance criteria
- Every exposed tool has strict arguments, bounded output, scoped/role denial tests, failure-atomicity tests, and an observable domain result.
- Direct writes are idempotent and audited; sensitive proposals are single-use and revalidated before mutation.
- Archived households allow reads but reject writes for every route and tool; membership selection/UI clearly marks archived homes.
- Ownership transfer, archival, and account deactivation preserve required audit/finance records.
- Both account deactivation entry points share service behavior and are authenticated; active owner preconditions are enforced.
- Backend/frontend test suites, lint, build, migrations, independent review, tests-branch CI/deploy, and test-domain health are verified before claiming completion.
