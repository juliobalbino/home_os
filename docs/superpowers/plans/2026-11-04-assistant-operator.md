# Home OS Assistant Operator Implementation Plan

> **For agentic workers:** Use OpenCode as the coding worker. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a scoped Home OS assistant operator with validated reads/writes, confirmed sensitive actions, archived-house read-only access, and safe account deactivation.

**Architecture:** Typed server-side tool schemas dispatch only to domain services. Ordinary mutations use authenticated household context, audit, transactions, and request idempotency. Sensitive operations use expiring actor-bound proposals with previews and locked snapshot/permission revalidation. Household/account lifecycle flows share backend services between assistant and security UI.

**Tech Stack:** Django REST Framework, Django ORM, React/TypeScript, Mantine, Vitest, Ruff.

**Spec:** `docs/superpowers/specs/2026-11-04-assistant-operator-design.md`

## Global Constraints
- Branch `module/assistant-actions` is based on `origin/tests`; preserve `main` and production.
- Every `manage.py` test/check/migration command sets `HOME_OS_TEST_SQLITE=true`.
- No live provider/OAuth calls; mock external provider requests.
- Never read/print `.env`, keys, credential bundles, or tokens.
- No arbitrary SQL/ORM from model output; use validated services, scoped actor/household, audit, and atomicity.
- Retain finance/audit rows; do not expose invitation hashes/tokens or user credentials to model.
- No commit/push/merge/deploy until implementation, full validation, and independent review; final publish target is `tests` only.

## Review Focus
- A retry or concurrent duplicate write must not create a second mutation or audit event.
- A stale/foreign/expired proposal must leave both domain state and proposal status correct.
- A viewer or archived member must retain read-only reads but never mutate via API, assistant, or delayed UI actions.
- An archived household must not accept invitations, new members, purchases, or other writes; existing retained data remains readable.
- Account deactivation must block owner duties, revoke personal assistant credentials/sessions, anonymize identifiers, and preserve financial/audit history.

---

### Task 1: Finish core assistant operator direct tools (in progress)

**Files:** `backend/apps/assistant/operator.py`, `services.py`, `views.py`, migrations/tests; `backend/apps/{finance,shopping,inventory,chores}/services.py` and APIs; `frontend/src/modules/assistant/Assistant.tsx`.

**Interfaces:** `dispatch_tool(name, arguments, *, user, household_id, request_uuid, call_index)`; strict schemas; domain-service handlers; bounded read output.

- [x] Read-only household, finance, shopping/inventory, and chores tools.
- [x] Idempotent shopping-list creation.
- [x] Finance create/update/payment/budget/category tools and shared cache.
- [x] Product, alias, price, list-item, inventory-event, and purchase tools with shared services.
- [x] Chore create/update/status tools; occurrence generation remains excluded from direct tools.
- [ ] Re-review complete tool registry and direct APIs for route coverage, limits, transaction races, provider loop, and omission of secret data.
- [ ] Run full backend and frontend suites, format/lint/build/migration checks after all remaining work.

### Task 2: Persisted sensitive-action proposals

**Files:** assistant proposal model/service/API/migration/tests; assistant views/services/operator schemas; frontend assistant result/proposal components/tests.

**Interfaces:** proposal create returns a bounded preview and opaque proposal ID; confirm/cancel APIs are authenticated and actor-bound; tool outputs to the model omit raw tokens/secrets.

- [ ] Write RED tests for delete-list exact snapshot, bulk occurrence-generation preview, member role/removal, invitation create/revoke, and expense reversal/cancellation proposals.
- [ ] Implement proposal expiry, single-use terminal state, cancel, replay, actor/household scoping, locking, exact snapshot revalidation, and no mutation on stale/cancelled/expired previews.
- [ ] Add UI cards with exact target/impact preview and accessible explicit confirm/cancel actions; isolate state by household.
- [ ] Verify no API path bypasses proposal requirements for destructive, bulk, or access changes.

### Task 3: Household archive and ownership transfer

**Files:** household model/service/API/migration/tests; assistant proposal handlers; household selectors/navigation/UI tests.

**Interfaces:** `archive_household(...)` preserves household/domain/audit data and makes all existing memberships read-only; `transfer_ownership(...)` preserves a single active owner and is proposal-confirmed.

- [ ] Write RED tests for archive retention/read access, denial of every write path, invitation revocation, owner-transfer invariants, race/stale snapshot, and later household creation/join.
- [ ] Implement archive/transfer services and proposals using locks and audit; no hard delete.
- [ ] Update membership/list endpoints and UI to present active versus archived households; archived selection has visible read-only state.
- [ ] Run household, assistant, shopping, finance, chores, and frontend regression suites.

### Task 4: Account deactivation shared workflow

**Files:** accounts model/service/API/migration/tests; assistant tool/proposal route; security UI and assistant proposal UI tests.

**Interfaces:** one backend service handles both entry points; authenticated proposal ID + explicit confirmation; owner-precondition and preview are identical in both flows.

- [ ] Write RED tests for owner blocking, member departure, archived-home read-only retention, concurrent membership change, one-use confirmation, session invalidation, assistant credential cleanup, invite revocation, anonymization, and finance/audit retention.
- [ ] Implement shared proposal/service; refuse deactivation while user owns an active home; after transfer/archive, revoke the user's active memberships/invitations and personal assistant credentials, disable sign-in, anonymize PII, preserve finance/audit rows.
- [ ] Add a separate security-settings entry point available with or without an active household, plus assistant proposal support.
- [ ] Verify login/session rejection, privacy boundaries, and retained-history reads.

### Task 5: End-to-end verification and independent review

**Files:** `PLAN.md`, tests only for discovered gaps.

- [ ] Compare tool registry and HTTP routes to the requested action matrix; record any intentional gaps.
- [ ] Run full backend suite, frontend suite, lint, format, build, migration checks, and compose configuration with explicit test environment.
- [ ] Run independent security/correctness review over the entire uncommitted diff; fix findings with focused tests.
- [ ] Update `PLAN.md` with verified scope/results and remaining exclusions.
- [ ] Re-run all required checks after final edits.

### Task 6: Publish to tests only

- [ ] Inspect/confirm exact branch diffs and staged file list.
- [ ] Commit/push/merge only the approved module branch into remote `tests`; never touch `main`/production.
- [ ] Read back remote SHA, inspect tests-branch CI/deploy outcome, and verify `https://homeostests.juliobalbino.com.br/api/v1/health`.
