---
name: guardrails-observability
version: 2.2.0
---
Authorization is external to prompts. Redact telemetry and correlate logical requests and attempts.

OAuth and OIDC: validate issuer, audience, signature, expiry, tenant, scopes, and roles at
the gateway. Derive tenant and department from trusted claims only. Short-lived access
tokens, rotating refresh tokens. Application roles are sets of the API's exact scope
strings (RBAC) plus attribute conditions for tenant, department, and document ACL (ABAC).
No wildcard scopes.

Object-level authorization applies to retrieval, source download, vector filters, cache
lookup, job status, audit views, and tool execution. A cache hit must re-check the same
principal and tenant it was stored for.

Guardrail stages, include only the stages this path has:

- Input: size, content policy, injection screening, task authorization. Injection detection
  reduces risk; the gateway and the ACL still decide access.
- Retrieval: tenant and ACL filter before the model sees a chunk, plus source trust.
- Tool: schema, permission, and exact-argument human approval when side effects require it.
- Execution: sandbox, and read-only credentials when side effects are forbidden.
- Output: schema, grounding or citation, sensitive-data release matched to classification.
- Audit: actor, route, reservation, sources, and approval id. Store decision summaries,
  not raw prompts that hold personal data.

Threat model: STRIDE per trust boundary of this design (channel, corpus, tool, cache,
queue, model provider). Map to OWASP Top 10 for LLM Applications 2025 when it fits, and
only these ids: LLM01:2025 Prompt Injection, LLM02:2025 Sensitive Information Disclosure,
LLM03:2025 Supply Chain, LLM04:2025 Data and Model Poisoning, LLM05:2025 Improper Output
Handling, LLM06:2025 Excessive Agency, LLM07:2025 System Prompt Leakage, LLM08:2025 Vector
and Embedding Weaknesses, LLM09:2025 Misinformation, LLM10:2025 Unbounded Consumption.
Never invent other ids. Cover LLM01 when untrusted text enters a prompt, LLM02 when
classification is confidential or restricted, LLM06 when tools exist, LLM08 when a vector
index exists, LLM09 when the product answers questions, and LLM10 on every design.

Observability: OpenTelemetry traces, metrics, and logs with `logical_request_id`,
`attempt_id`, `reservation_id`, `queue_job_id`, `tool_call_id`, and `approval_id`.
Langfuse or the equivalent is model analytics, not the budget ledger. SLOs follow the
stated availability and latency targets: first token, completion latency, provider errors,
retry amplification, queue age, quota headroom, unresolved spend, and policy violations.
Redact content. Never store hidden reasoning.

Evaluation: golden sets drawn from the journeys, adversarial sets for the selected
archetypes, and feedback samples. Evaluate every primary route and every fallback route.
Release gates block on safety, grounding, and tenant-isolation regressions, not only on
average quality.

Lessons from design reviews:

- Each guardrail's owner is the id of the service that enforces it, not a team or a layer.
- Permission checks run on every passage the model sees, not only on the cited ones; access
  revoked during generation withdraws the answer before release.
- Release gates include the PRD's acceptance metrics, not only quality and safety scores.
