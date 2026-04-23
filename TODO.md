# TODO

## ProjectVersion

- Enforce immutability for versions with statuses `sent_to_client`, `accepted`, and `superseded`.
- Add strict status transition validation for `ProjectVersion` lifecycle.
- Wrap `Deal.create_new_version()` in a transaction to avoid race conditions and duplicate version numbers.

## Backlog / Deferred

- Add role-based visibility rules (designer should not see commercial fields).
- Add business validations for `ChangeLog` creation (field_path format, payload shape).
- Add dashboard-specific query indexes after Phase 2 profiling.
- Add tests for model methods (`create_new_version`, `mark_done`, project code normalization).
- Add scripted import for full `CostItem` catalog from Excel.
