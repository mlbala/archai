---
name: api-routing-and-budgets
version: 2.2.0
---
Filter routes by policy before ranking. Treat each billable attempt as a separate reservation.

Standard path: client token, enterprise API gateway (token validation, admission, request
limits), application orchestration, model admission (budget reservation and eligible route),
AI gateway such as LiteLLM (provider adaptation and the single retry and fallback owner),
managed endpoint, output validation, usage settlement.

One owner per control. Authentication and request limits sit at the enterprise gateway.
Budget reservation and settlement sit in model admission. Provider retry, timeout, and
fallback sit in the AI gateway. Do not stack independent retry budgets across the SDK, the
gateway, and workers.

Logical aliases are named by task (`enterprise-chat`, `document-extraction`,
`enterprise-embedding`), one alias per task this product performs. Eligibility filters
residency, tenant and classification policy, modality, context length, tools, schema,
evaluation threshold, quota, and health before any cost or latency ranking. Capabilities
are only `text`, `streaming`, `json-schema`, `tools`, `vision`, `audio`, `long-context`,
and `embeddings`. Providers are only `allowed_target_providers`.

Never fall back on a safety refusal. Never splice a second model into a stream that has
already produced a token. Never fall back an embedding alias into a different vector space;
that is a reindex, owned by the retrieval pipeline. A fallback that exists must be evaluated.

Budgets: organization, then department or user group, then application. Allocations are
shares of the hard monthly limit, including a reserve, summing to at most 100. Python
computes the currency amounts. Hard limits reject when the ledger is unavailable.
Reservations cover the bounded attempt envelope (`max_attempts`). Unknown usage stays an
unresolved liability until settlement. Per-request ceilings cover the stated input tokens,
output tokens, and model calls per request, plus the attempts already bounded above.

Caching: provider prompt caching is safe. Exact caching binds tenant, principal scope,
index version, prompt version, route policy version, and locale. Semantic caching is
opt-in per evaluated route and is off for restricted data and for side-effecting, personal,
or time-sensitive requests. Never promise a fixed saving.

API design: versioned REST under `/v1`, SSE when the channel streams tokens, `202` plus a
status resource for long jobs, idempotency keys on POSTs that create work, OAuth scopes
per operation in `resource.action` form, per-principal limits derived from the stated RPS.
The public operations are the ones the personas' journeys need, including approval and
status when the workflow waits on a person.

Lessons from design reviews:

- If answers cite documents a user can open, define the operation that opens a cited
  document and re-checks that user's permission on that version. A citation link with no
  operation behind it is a broken journey.
- If users or admins add documents, define the upload or registration operation and how it
  becomes an ingestion job; do not leave publication to a side channel.
- Every step a workflow names is a contract in `api_contracts` or an internal call between
  services, with the same path and method.
- Streaming and grounding must agree. Either release text only after its citation and
  permission checks pass (stream validated segments), or do not stream; never stream text you
  might have to withdraw.
- `per_workflow_step_ceiling` counts model-calling steps per workflow run;
  `per_request_token_ceiling` counts tokens per request across calls and attempts.
- A Teams or Slack channel calls a channel adapter endpoint authenticated by the bot
  platform (Bot Framework token or Slack signature), not by the user API's bearer token. The
  adapter obtains the user's identity by single sign-on and token exchange and calls the same
  application operations; its replies go back through the platform's reply API. Set that
  contract's `auth` to the platform mechanism; leave `auth` empty for user bearer tokens.
