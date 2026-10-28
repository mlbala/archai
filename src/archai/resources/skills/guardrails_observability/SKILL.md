---
name: guardrails-observability
version: 2.1.0
---
Authorization is external to prompts. Redact telemetry and correlate logical requests and attempts.

- OAuth/OIDC: validate issuer, audience, signature, expiry, tenant, scopes, and roles at the
  gateway; derive tenant and department from trusted claims only; short-lived access tokens,
  rotating refresh tokens. Define application roles as sets of API scopes (RBAC) and add attribute
  conditions (tenant, department, document ACL) for ABAC.
- Object-level authorization applies to retrieval, source download, vector filters, cache lookup,
  job status, audit views, and tool execution.
- Guardrail stages: input (size, content, injection screening, task authorization), retrieval
  (tenant/ACL filter, source trust), tool (schema, permission, exact-argument human approval),
  execution (sandbox, read-only credentials when side effects are forbidden), output (schema,
  grounding, sensitive-data release), audit. Injection detection is a layer, not a boundary.
- Threat model: STRIDE per trust boundary, mapped to OWASP Top 10 for LLM Applications 2025 IDs
  (LLM01:2025 Prompt Injection, LLM02:2025 Sensitive Information Disclosure, LLM03:2025 Supply
  Chain, LLM04:2025 Data and Model Poisoning, LLM05:2025 Improper Output Handling, LLM06:2025
  Excessive Agency, LLM07:2025 System Prompt Leakage, LLM08:2025 Vector and Embedding Weaknesses,
  LLM09:2025 Misinformation, LLM10:2025 Unbounded Consumption). Never invent other IDs.
- Observability: OpenTelemetry traces/metrics/logs with logical request, attempt, reservation,
  queue job, tool call, and approval IDs; Langfuse for model analytics (not the budget ledger);
  SLOs for first token, completion latency, provider errors, retry amplification, queue age,
  quota headroom, unresolved spend, and policy violations; redact content and store decision
  summaries, never hidden reasoning.
- Evaluation: golden sets, adversarial sets, and feedback samples; evaluate every primary and
  fallback route; release gates on regressions and safety failures.
