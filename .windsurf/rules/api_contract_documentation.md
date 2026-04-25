---
trigger: always_on
---

# API Contract Documentation Rule

- Treat `docs/api` as a required source of truth for this service's public and internal data contracts.
- Whenever changing any API contract, Temporal workflow contract, webhook payload, request model, response model, or integration payload, update the relevant file(s) under `docs/api` in the same task.
- A task that changes contract-related behavior is **not complete** unless the matching `docs/api` documentation is updated.
- If a relevant `docs/api` file does not exist yet, create it as part of the same change.
- Keep contract documentation concrete and example-driven. Include request fields, response fields, required prerequisites, important invariants, and error cases when relevant.
- For FastAPI endpoints, update both:
  - the markdown contract docs under `docs/api`
  - the in-code OpenAPI metadata and model field descriptions when appropriate
- For webhook payload changes, explicitly document which fields are always present, which are conditional, and which workflow or endpoint emits them.
- For workflow-specific contract differences, document those differences explicitly rather than describing a single generic payload.
- If a code change does **not** affect contracts, do not make unnecessary edits to `docs/api`.
- Before finishing contract-related work, verify that the documentation still matches the implemented behavior exactly.
