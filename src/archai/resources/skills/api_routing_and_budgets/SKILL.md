---
name: api-routing-and-budgets
version: 2.1.0
---
Filter routes by policy before ranking. Treat each billable attempt as a separate reservation.

- Standard path: client token → enterprise API gateway (token validation, admission, request
  limits) → application orchestration → model admission (budget reservation + eligible route) →
  AI gateway such as LiteLLM (provider adaptation, the single retry/fallback owner) → managed
  endpoint → output validation and usage settlement.
- One owner per control: authentication and request limits at the enterprise gateway; budget
  reservation and settlement in model admission; provider retry, timeout, and fallback in the AI
  gateway. Never stack independent retry budgets across SDK, gateway, and workers.
- Logical aliases are named by task (enterprise-chat, document-extraction, enterprise-embedding).
  Eligibility filters residency, tenant/classification policy, modality, context, tools, schema,
  evaluation threshold, quota, and health before any cost or latency ranking.
- Never fall back on a safety refusal, never splice a second model into a stream that already
  started, and never fall back embeddings to a different vector space.
- Budgets: organization → department → application/user hierarchy, hard limits reject when the
  ledger is unavailable, reservations cover the bounded attempt envelope, unknown usage stays an
  unresolved liability. Redis counters are rate limiting, not the ledger.
- Caching: provider prompt caching is safe; exact caching binds tenant, principal scope, index,
  prompt, route policy, and locale; semantic caching is opt-in per evaluated route and bypassed
  for side-effecting, personal, or time-sensitive requests. Never promise a fixed saving.
- API design: versioned REST (/v1), SSE for streaming chat, 202 + status resource for long jobs,
  idempotency keys on POSTs that create work, OAuth scopes per operation, per-principal limits.
