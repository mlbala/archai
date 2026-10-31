# Task: identity, guardrails, threat model, observability, and evaluation

Design only the components in `scope`. You are securing and proving the design that already
exists, not inventing a parallel platform. Every identity, threat, and metric must name
services, stores, APIs, or aliases from `existing_design`. Authorization is enforced in
code and policy at the gateway, the retrieval filter, and the tool executor. Prompts are
data. A system prompt is not an access-control boundary.

## Identity

Use the identity provider from the requirements when one is set. Users authenticate with
OIDC authorization code and PKCE. Services use workload identity and client-credentials
tokens. On-behalf-of or token exchange is for a tool call that must carry the user's
delegated authority. Do not store long-lived secrets for these paths.

Application roles are the stated user roles. If none were stated, derive the smallest set
from the PRD personas and record that as a decision. Each role's permissions are exact
scope strings copied from `existing_design.api_contracts`. No wildcard permissions, no
scopes that no operation enforces.

One service identity per service id. Grants match that service's responsibilities and the
stores it owns: the tool executor is read-only when side effects are forbidden, holds
approval-gated grants when they require approval, and has explicit write grants only when
side effects are allowed. Retrieval identities can read the index and the object store
through an ACL filter; they cannot read another tenant's partition. The permission to read a
document is granted by the system that owns that document's access list, not by a service
that holds a related record in another system.

Tenant and department come from trusted claims (`tid` and the claims you add), never from
the prompt or a tool argument. Sessions are short-lived access tokens and rotating refresh
tokens. Object-level authorization covers retrieval, source download, cache lookup, job
status, audit views, and tool execution.

## Guardrails

Add a control only where this application's path needs it. Stages are `input`, `retrieval`,
`tool`, `execution`, `output`, and `audit`.

- Input: size, content policy, injection screening, and whether this principal may run this
  task. Injection detection is a layer, not the boundary.
- Retrieval: tenant and document ACL filters before chunks reach the model, and a source-trust
  rule for untrusted documents. Omit this stage when the design has no retrieval.
- Tool: schema validation, permission check, and exact-argument human approval when
  `tool_side_effects` is `approval`. Omit write-side tool controls when side effects are
  forbidden; still constrain any read tool that can exfiltrate.
- Execution: sandbox and read-only credentials when side effects are forbidden.
- Output: schema, grounding or citation when the product answers from sources, and a
  sensitive-data release check matched to the classification.
- Audit: who approved, which route and reservation ran, and which sources were used,
  without storing raw prompts that contain personal data.

`enforcement` is `native` when the gateway, IdP, or managed store already does it,
`custom-runtime-required` when application code must run the check, and `design-only`
when it is a process or release control. Name an owner service that exists.

## Threats

Model the trust boundaries of this design: the channels, the document corpus, the tool
integrations, the cache, the queue, and the model provider. Eight to fourteen threats,
STRIDE, each with a mitigation that is a control you can point at and a residual risk that
is honest. Use an OWASP Top 10 for LLM Applications 2025 id when it fits
(`LLM01:2025` through `LLM10:2025`) and an empty string when it does not. Never invent
other ids. Cover prompt injection when untrusted text enters a prompt, sensitive
disclosure when data is confidential or restricted, excessive agency when tools exist,
vector and embedding weaknesses when retrieval exists, misinformation when the product
answers questions, and unbounded consumption on every design. Affected ids are services
and stores from the context.

## Observability and evaluation

Traces, metrics, and logs use OpenTelemetry. Model analytics (Langfuse or the platform
equivalent) are not the budget ledger. Correlate `logical_request_id`, `attempt_id`,
`reservation_id`, `queue_job_id`, `tool_call_id`, and `approval_id` wherever that hop
exists. Metrics are the ones an on-call engineer would page on for this product: first
token or completion latency against the stated target, availability, provider errors,
retry amplification, queue age when jobs exist, quota headroom, unresolved spend, and
policy violations. Alerts name a threshold and a page versus a ticket. Dashboards map to
the journeys. Logs are redacted: decision summaries and ids, not prompt or document bodies.
Retention matches the compliance and audit need stated in the requirements.

Evaluation datasets are a golden set from the journeys, an adversarial set for the
archetypes (injection, ACL bypass, ungrounded answers, unsafe tool arguments), and a
feedback sample. Score every primary route and every fallback route. Release gates fail
the rollout on safety regressions, grounding regressions, and tenant-isolation failures,
not only on average quality.

## Decisions

Record the role-to-scope mapping, where you refused to treat the prompt as a control, which
threats you accepted as residual, and which SLOs are direct copies of the requirements
versus operating assumptions.
