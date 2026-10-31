---
name: architecture-planning
version: 1.0.0
---
Choose the shape of the system from its journeys, data, and side effects, then name the
services the specialists will build. A plan is good when every service exists for a journey
or a control, and every journey can be traced through the services.

Pick the style from the dominant journey:

- Interactive answers (chat, copilot, Q&A): a synchronous request path with streaming,
  bounded by the latency target. Grounding and permission checks sit before the model sees
  data.
- Document or data intake (ingestion, OCR, extraction, embedding, reindexing): an
  asynchronous job pipeline. The caller gets a job id and a status resource, workers are
  bounded, and a dead-letter queue has an owner.
- Actions in other systems (refunds, tickets, payments, record updates): an agent loop
  whose tool calls go through one tool executor. Read tools and write tools are separate.
  Writes follow `tool_side_effects`: none, an exact-argument human approval, or bounded
  autonomy.
- Bulk or scheduled work (summaries, classification, evaluation runs): batch jobs on a
  schedule with their own budget share and no interactive latency target.
- Events from other systems (webhooks, CDC, alerts): event-driven consumers with
  idempotent handling and replay.

Most applications combine two of these. Say which one owns the latency target.

Boundaries to decide before naming services:

- Trust: only the enterprise gateway is public. Identity comes from tokens, never from the
  prompt.
- Tenancy: for multi-tenant designs, choose pooled with tenant partition keys or siloed
  stores per tenant, and say why. Every store, index, cache, and log carries the tenant key.
- Data: name the system of record for each data source. Retrieval is evidence, not a system
  of record. Permission to read a document comes from the system that owns its access list.
- Model path: model admission reserves budget before every billable attempt, and the AI
  gateway owns retries and fallback. They may call each other in either direction, but never
  both ways.
- Recovery: for `application-dr`, plan a standby deployment, including model endpoints, in
  another allowed region. Never plan a region outside `data_residency`.

Channels: each client channel other than the web app has its own adapter service. A
Microsoft Teams or Slack bot validates the platform's signed requests (Bot Framework token,
Slack signing secret), maps the platform user to the identity provider through single sign-on
and token exchange (on-behalf-of), and then calls the application service like the web client.
The adapter's endpoint is authenticated by the bot platform, not by a user's bearer token, and
answers go back through the platform's reply API. Plan the adapter as a service; do not route
a chat platform straight to the user API.

Service boundaries follow bounded contexts (answers, intake, approvals, a system of record's
integration), not layers. One integration service per system of record it reads or writes.
Merge services that would only forward calls. Keep the four platform controls: the enterprise
gateway, an application or orchestration service, model admission, and the AI gateway.

`default_changes` is where you overrule ArchAI's starting template for this application,
each with the reason, for example: add a standby endpoint in the recovery region, split an
approval service out of the application service, or drop a worker that no journey needs.
ArchAI checks every change against the requirements and reports any it cannot accept.
