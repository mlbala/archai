# Task: API management, model routing, budgets, and caching

Design only the components in `scope`. You own the contract callers will code against, the
model tasks this product actually runs, how spend is reserved, and what may be cached.
Cloud design is already in `existing_design`. Use its service IDs, workflows, and retrieval
choices. Do not invent a second platform beside them.

## APIs

Each contract is an operation a persona performs, or the status, cancellation, or approval
operation that journey requires. Prefer a few complete operations over a catalog of generic
CRUD. Paths are versioned (`/v1/...`) and named with this product's resources.

- `service_id` is an id from `existing_design.services`. The enterprise gateway is the
  public edge; the owning service is the one whose responsibility the operation is.
- Streaming is true only when the channel must render tokens as they arrive. Long work is
  `202` plus a status resource, not a held HTTP call.
- Scopes are explicit `resource.action` strings. Identity design will grant these exact
  strings. No wildcards, no scopes that no operation uses.
- Rate limits are per principal, in requests per minute, sized from the stated average and
  peak RPS and from fairness across tenants. Say in the decision how the number relates to
  that traffic rather than picking a round limit with no owner.
- Request and response fields are the ones this operation needs, including idempotency keys
  on POSTs that create work, reservations, or external side effects, and correlation ids the
  caller can pass through.
- A write that can move money, change a customer record, or call an external system carries
  the approval behavior required by `tool_side_effects`. When that value is `approval`, include
  `GET /v1/approvals` (`approvals.read`, assigned to the caller, re-check source access before
  proposal details) and `POST /v1/approvals/{approval_id}/decision` (`approvals.decide`).

## Routing

Define one logical alias per distinct task this application performs (answer, extract,
embed, classify, SQL, voice), named for the task, not for a vendor model. Required
capabilities are the minimum the task needs, chosen only from: `text`, `streaming`,
`json-schema`, `tools`, `vision`, `audio`, `long-context`, `embeddings`.

`primary_provider` and `fallback_providers` are members of
`requirements.allowed_target_providers` only. If `existing_design.endpoints` lists a
processing region, the alias must be eligible for that region. Embedding aliases have an
empty fallback list: a different embedding model is a different vector space and requires
a reindex, not a runtime failover. If the cloud design already named an embedding alias,
use that id and the same dimensions.

Eligibility is a filter, applied before any ranking: residency, tenant and classification
policy, modality, context length, tools, schema, evaluation threshold, quota, and health.
Endpoint RPM, TPM, and context limits that the requirements did not state are a planning
envelope derived from peak traffic, not an account quota. Say that a release gate confirms
the account quota before go-live. When a rule or decision needs a request or token rate, quote
it from `fixed_facts.planning_capacity` instead of computing it. The token sizes in
`fixed_facts.traffic` are averages per model call, not caps.

`existing_design.endpoints` are ArchAI's default deployments. Add a deployment in `endpoints`
when this application needs one, for example a standby in the recovery region for
`application-dr` or a second deployment for latency. Each needs a provider from
`allowed_target_providers`, a region from `data_residency`, and a reason. A recovery
deployment is used only after regional failover; it is not a runtime fallback.
Ranking (cost, latency, quality) happens only among eligible routes. The AI gateway is the
single retry and fallback owner. `max_attempts` is 2 for the whole model call: the initial
call and one retry. Peak RPM and TPM include both attempts, and each billable attempt is
reserved before dispatch. Do not commit 3. Worker and queue attempts are a separate budget
and do not dispatch model calls. Never fall back on a safety refusal. Never splice a second
model into a stream that has already started. A fallback route is part of the product and
must be something evaluation can score.

## Budgets

Allocations are percentages of one model-admission hard limit. That limit is `monthly_budget`
in `currency`. It rejects new model calls. It is not a cap on platform or other operating
spend, and rejecting a model call does not enforce that other spend. Do not invent a second
or provisional ceiling. Do not allocate infrastructure, telemetry, or any other non-model
spend from it, and do not invent prices.

Shares cover the stated user groups. When retrieval is in scope, also include document
ingestion. Always include a reserve. Shares sum to 100. Do not give interactive callers
100% and leave ingestion unfunded. The soft-limit percent is the alert before hard rejection. When the ledger cannot be read, the
call is rejected. The per-request token ceiling covers
`input_tokens`, `output_tokens`, and `model_calls_per_request` with small headroom for
retries inside `max_attempts`. The per-workflow ceiling bounds a job that loops. The
rationale should show that arithmetic, not a slogan about cost control.

## Caching

Provider prompt caching is the default safe reuse. Exact response caching is allowed only
when the namespace binds tenant, principal scope, index version, prompt version, route
policy version, and locale. Semantic caching is opt-in for a route you would evaluate,
and it is off when classification is `restricted`, when the answer is personal or
time-sensitive, or when the request has a side effect. Bypass conditions and invalidation
events name the facts that make a cached answer wrong for this product (source updated,
ACL changed, approval state changed, index version changed). TTL follows source freshness.
Do not claim a savings percentage.

## Decisions

Record why the public surface is this small, why a task has or lacks a fallback, how the
budget shares map to the real user groups, and why semantic cache is on or off.
