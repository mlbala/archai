---
name: resilience-and-queues
version: 2.2.0
---
Use bounded at-least-once processing, idempotent transitions, dead-letter queues, and
quota-aware scaling.

Two paths. Chat and voice use a synchronous stream whose hop timeouts fit inside the
latency target when one was stated. Ingestion, OCR, embeddings, batch evaluation, and long
workflows use an authorized job, an outbox, a broker, a bounded worker, and a result or
status API. The user is never left without a status they can read.

Brokers follow the profile: Azure Service Bus with the Azure SDK, Amazon SQS with the AWS
SDK, Celery only when the requirements ask for it. State max attempts, lock or visibility
renewal, retry delay, the DLQ owner, poison quarantine, cancellation, graceful shutdown,
and the redrive procedure. External side effects are at-least-once; the idempotency key
makes the duplicate safe. Do not claim exactly-once delivery to a third party.

Bound queue depth, in-flight jobs, payload size, memory, execution time, model calls, and
connection pools. When downstream quota is exhausted, apply backpressure and tenant
fairness instead of retrying harder. Replica ceilings stay inside provider token and
request headroom. Do not invent the provider's quota; name it as an account input the
capacity plan must confirm.

Scaling: Container Apps native scale rules on `azure-aca`; KEDA queue scalers on AKS and
EKS. Do not claim that CPU-based horizontal pod autoscaling reads queue depth. Liveness
must not fail because the model provider is down, or a provider incident becomes a restart
storm. Readiness reports degraded.

Circuit breakers are closed, open, and half-open, with a limited probe budget. One retry
owner for model calls. Degraded behavior is explicit: a labeled stale answer, a queued job,
or a refusal. A silent answer from a different corpus or a different tenant is not a
degraded mode.

Topologies: `provider-failover` protects only the model dependency and still respects
residency and the embedding vector space. `application-dr` needs a recovery environment
with ingress, compute, identity, data, queues, secrets, budget authority, traffic
switching, and a tested runbook, using the stated RTO and RPO. `single-cloud` does not
describe a second region as if it were already funded.

Lessons from design reviews:

- One delivery limit per queue. `queue_policy.max_attempts` is the count; the retry text
  describes backoff and which errors retry, and does not restate a different number.
- At-least-once jobs that call a model carry an idempotency key per model call, so a
  redelivered job reuses the earlier result instead of paying for the call again.
- An atomic commit spans one database. State that lives in two stores is kept consistent by
  an outbox or a saga, not by one transaction.
- `application-dr` recovery needs everything the request path uses in the recovery region,
  including the model endpoints and the embedding deployment for the same vector space.
- An availability SLO counts dependency, model, and budget-limit failures as unavailable. An
  explained refusal is not an available answer.
