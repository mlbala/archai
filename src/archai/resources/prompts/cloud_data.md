# Task: system, data, workflow, retrieval, infrastructure, and resilience

Design only the components in `scope`. You own the shape of the system: which services exist
because this product needs them, where its data lives, how a request and a job move, and how
it fails. Later roles will hang APIs, budgets, identity, and telemetry on the IDs you choose.
Vague IDs become vague security.

## How to decide

Start from the PRD journeys, the archetypes, the data sources, and the integrations. Draw
two paths before you name resources.

- The synchronous path is for a person waiting: client, enterprise gateway, application
  orchestration, model admission, AI gateway, managed model, then validation and the response.
  Keep it short enough for the latency target when one was given.
- The asynchronous path is for ingestion, extraction, embedding, batch evaluation, and any
  tool or workflow that must not block the user. The application writes an authorized job;
  a worker consumes it; status is readable.

Include a service only when a journey needs it. Retrieval exists when answers are grounded
in private or changing data. Ingestion exists when documents or events arrive ahead of the
question. A tool executor exists when integrations or tool use are in scope; its authority
matches `tool_side_effects`. An integration service exists per system of record that the
product writes to or reads operational state from, not one generic "integration" box for
everything. Name product services after the bounded context (`claims-answers`,
`refund-executor`), not after a layer. The four platform services are the exception and are
required when `system` is in scope: one enterprise API gateway (`gateway`), one application
or orchestration service, one model admission and budget service (`policy`), and one AI
gateway (`ai-gateway`).

`depends_on` is the real call graph: service IDs and store IDs you define in this response.
`data_owned` is the store that service is the system of record for. `exposes` is the API
resource or event the next role will turn into a contract.

## Data

Pick the store from the access pattern, then the hosting profile.

- The budget and any other money, entitlement, or approval state needs a transactional store
  with a serializable ledger. Conversation and job state may share that server in a separate
  database; do not put the ledger in a cache.
- Object storage holds documents and artifacts. Queues carry references and job ids, never
  document bytes, prompts, or secrets.
- Use one managed vector store only when retrieval is in scope. Record the embedding alias,
  dimensions, and that a model or dimension change is a new index version plus a reindex.
- Every store has an owner service, a partition key, consistency, retention, encryption, and
  backup. Multi-tenant designs partition by tenant first. Single-tenant designs still record
  the organization key. Retention follows the stated classification and compliance. If a
  regulation is named and no retention period was given, choose a conservative period and
  say in the decision that it is an assumption, not a stated requirement.
- Region is inside `data_residency`. Private data stores are not public. Only the enterprise
  gateway is public. Egress to model endpoints is allowlisted.

## Workflows, retrieval, infrastructure, resilience

Workflows are the PRD journeys expressed as system steps, including the async and approval
paths. `hitl_required` is true where a person must approve before a side effect, and wherever
`tool_side_effects` is `approval`. Four to ten steps, each a verb with an actor.

If retrieval is not required, set `applicable` to false and do not invent a corpus. If it
is required, the pipeline names how this application's documents enter,
how access control is enforced at retrieval time (not after the model has seen the chunk),
how an answer cites or refuses when grounding fails, and how fresh the index is relative to
the source. Permission to read a document comes from the system that owns that document's
access list, checked for the caller and for the version being cited. Access to a related
record in a different system of record is not that permission.

`exposes` names the resources and events a service provides. ArchAI keeps the public paths on
the enterprise gateway and on each owning service equal to the API contracts.

Infrastructure names concrete managed services for the selected profile, in the selected
region, with a tier justified by the stated RPS and data size. `agnostic` means portable
roles with no vendor SKU. Environments are the ones this operating model needs, not a
copied dev/test/stage/prod list when the requirements describe a smaller footprint.
Networking states what is public, what is private, and how identity reaches the model endpoint.

Resilience has one retry owner for model calls: the AI gateway, with a maximum of 2
attempts. Workers have their own bounded attempts and a named DLQ owner. Those queue
attempts do not dispatch an extra model call. Timeouts are per hop and fit inside the caller's
deadline. Degraded modes say what the user can still do, or that the system refuses, and
they never return a silent ungrounded answer. Circuit breakers probe with a limited budget.
Scaling ceilings respect provider token and request headroom without inventing the provider's
quota; take peak rates from `fixed_facts.planning_capacity`. Recovery targets apply only to failures that can be restored inside `data_residency`.
Do not claim a region outside that list. Loss of every allowed region is an accepted risk,
because failover would leave residency. `provider-failover` protects only the model dependency
and is not application disaster recovery. `application-dr` may use a second region only when
that region is already in `data_residency`. If RTO or RPO were not given, say so instead of
inventing minutes. Write `dr_strategy` for this application: what fails over, in which
allowed region, and what the user can do meanwhile. ArchAI keeps it unless it names a region
outside `data_residency`.

## Decisions

For each component in scope, record one to three decisions a reviewer would challenge:
why this service boundary, why this store, why sync versus async, why this recovery model.
Name the alternative you rejected and the requirement that made it lose.
