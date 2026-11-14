# Demo data cleanup

## Goal

Let the household assistant prepare an exact preview of selected demonstration records, then remove them only after explicit confirmation. Preserve unrelated records and explain blockers.

## Design

- The operator reads household records and calls `propose_record_cleanup` with the IDs of selected shopping lists, products, chores, finance categories, and expenses.
- The proposal stores a snapshot of the selected records and their dependent records. Its preview lists every primary record and dependent counts. The confirmation endpoint checks the snapshot again and applies the deletion in one database transaction.
- A selected record linked to an unselected list, product, expense, or purchase blocks the proposal with an actionable message. It never silently expands the selection. Audit events stay as system history.
- A malformed or unavailable tool result gets a specific safe error message, while server logs retain the exception type for diagnosis. No raw household data or credentials enter logs.
- The frontend displays every proposed record and requires the existing sensitive-action confirmation button.

## Verification

- Reproduce the generic list-proposal failure path and validate clearer error handling.
- Prove selection, cross-household rejection, dependency blocking, stale proposals, cancellation, idempotent confirmation, and transaction rollback with backend tests.
- Prove the preview and confirmation control render in the frontend.
- Run complete test suites, lint, formatting, build, and migration checks before merging to `tests`.
