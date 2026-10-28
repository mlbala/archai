---
name: resilience-and-queues
version: 2.1.0
---
Use bounded at-least-once processing, idempotent transitions, DLQs, and quota-aware scaling.

- Synchronous streaming path for chat and voice; asynchronous path (authorized job + outbox →
  broker → bounded worker → result store/status API) for ingestion, OCR, embeddings, batch
  evaluation, and long workflows.
- Brokers: Azure Service Bus with Azure SDK workers, AWS SQS with AWS SDK workers, Celery only
  when requested. Specify max attempts, lock/visibility renewal, retry delay, DLQ owner, poison
  quarantine, cancellation, graceful shutdown, and a redrive procedure.
- Bound queue size, in-flight jobs, payloads, memory, execution time, model calls, and connection
  pools. Apply backpressure and tenant fairness when downstream quota is exhausted.
- Scaling: Container Apps native scale rules; AKS/EKS with KEDA queue scalers; never claim CPU
  HPA reads a queue. Replica ceilings respect provider TPM/RPM.
- Liveness must not fail on provider outages (avoid restart storms); readiness reports degraded.
- Circuit breakers are closed/open/half-open with a limited probe budget; one retry owner.
- Topologies: provider-failover protects only the model dependency; application-dr needs a
  recovery environment with ingress, compute, identity, data, queues, secrets, budget authority,
  traffic switching, and a tested runbook, with explicit RTO/RPO.
