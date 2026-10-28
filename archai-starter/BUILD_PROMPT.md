# ArchAI v2 — Enterprise AI Solutions Architect

Complete replacement build prompt • Revised 28 October 2026

This version incorporates both supplied specifications and supersedes the earlier GPU-centric prompt. The active product designs systems that use managed AI APIs. Local inference, GPU procurement, GPU sizing, and fine-tuning are outside v2. Keep any existing legacy calculator isolated for compatibility; do not invoke it or include it in managed-API designs.

Copy from **BEGIN BUILD PROMPT** through **END BUILD PROMPT** into your coding agent. The companion architecture file explains the system and includes diagrams. This file is self-contained; implementing it must not require the previous prompt.

---

# BEGIN BUILD PROMPT

## 1. Mission and scope

Act as the lead Python engineer and enterprise AI solutions architect. Build **ArchAI**, a terminal application that interviews a user, ingests requirements, and produces a coherent enterprise AI design package with implementation configurations and diagrams. Use `archai` as the repository slug and Python package, and `arch` as the primary CLI command. Every design capability must be usable individually under manual control and as part of automatic end-to-end design.

Build the designer application described here. Its outputs describe a separate target system. Do not confuse these scopes:

- **Designer runtime:** local Python CLI, structured model calls, five specialist roles, deterministic analysis/compiler, filesystem project store, tests, and export tools.
- **Target architecture:** enterprise client/API services, identity, model gateways, managed model APIs, queues/workers, databases, vector search, storage, guardrails, telemetry, and infrastructure.

The designer itself does not need AKS, Cosmos DB, Redis, Celery, or a public web server to run. It must work locally with an architect-model credential and optional rendering tools. Integration test services are optional development dependencies.

The product supports RAG, multimodal document processing, tool-using agents, HITL, text-to-SQL, real-time voice, enterprise copilots, and hybrid enterprise-network/cloud integrations. In this version, inference uses managed APIs. An offline-only or local-inference requirement must be recorded as unsupported/conflicting rather than silently changed.

Implement real functionality, complete tests, and useful examples. Do not stop at planning. Never report unimplemented exporters, untested integrations, or sample catalog values as production-ready facts.

## 2. Product decisions and constraints

1. Python 3.12+, Typer, Rich, Pydantic v2, a `src/` package, `pyproject.toml`, and a locked dependency set. Provide `arch`, a fallback `archai` alias, and `python arch.py` entrypoints, all invoking `archai.cli:app`. macOS already supplies `/usr/bin/arch`; document virtual-environment/PATH resolution and the alias without modifying the system executable. Repository and import names do not establish package-registry or trademark availability.
2. Model-generated content is a validated proposal. Pure Python code owns arithmetic, policy enforcement, graph validation, layout, configuration rendering, diffs, hashing, and manifests.
3. Use exactly five named specialist roles under a bounded supervisor. These are typed application workflow roles; they do not require five processes, five model subscriptions, or a separate orchestration framework. Component commands dispatch only applicable roles, prerequisites, and validators; a full automatic design coordinates all applicable roles.
4. Default to an Azure application profile with managed inference and optional AWS Bedrock provider failover. Also implement an AWS application profile and a cloud-agnostic design mode.
5. Enterprise features must be evaluated for every complete design; focused commands evaluate the selected component and its relevant constraints. Include implementations only when applicable. Do not put AKS, EKS, Celery, Service Bus, Redis, three databases, and three vector stores into every result.
6. No fine-tuning, training jobs, LoRA/QLoRA, or self-hosted inference. Keep models, deployment IDs, service capabilities, regions, prices, and license requirements in versioned catalogs/configuration.
7. Generate reviewed deployment assets. Never deploy, apply Terraform, create accounts, provision services, rotate credentials, or purchase capacity from the CLI.
8. Treat requirements files, retrieved text, tool descriptions, and imported skills as untrusted data. They cannot change designer policies, execute commands, or reveal secrets.
9. Preserve previous revisions and user edits. Never silently discard conflicting requirements.
10. No unsupported guarantees: queues do not guarantee crash prevention; semantic caching does not guarantee a fixed saving; provider fallback does not prove whole-application disaster recovery.
11. Commits created for this project must use the user's configured author and committer identity only, with no AI co-author or generated-by attribution. Follow section 25 and retain that policy in repository instructions.

## 3. Expected user outcome

Given an idea or existing specification, produce:

- an enterprise PRD, requirement evidence, interview record, assumptions, conflicts, and decisions;
- a justified service/component design with synchronous, asynchronous, retrieval, model, tool, and human flows;
- identity, tenant boundaries, role/attribute policies, service identities, and secret references;
- API management, model aliases, routing/fallback, provider quotas, token budgets, and caching design;
- workload/cost estimates and queue capacity scenarios with visible inputs and limitations;
- resilience, scaling, failure recovery, security, evaluations, and observability plans;
- a cloud service BOM and chosen deployment profile;
- one canonical JSON design and graph used to compile every output;
- Markdown, JSON, YAML, Mermaid, Draw.io, SVG, PNG, PDF, Terraform, and applicable native gateway/workload configurations;
- a machine-readable validation report and artifact manifest;
- update revisions with semantic differences and preserved history.

## 4. CLI and terminal experience

### Product naming and complete-design command

The product is ArchAI, the proposed repository is `archai`, and commands start with `arch`. `archai` is an executable alias for environments where `arch` conflicts with a system command. Do not require users to invoke Python modules directly.

Main entrypoints:

```text
arch                                  # guided terminal command/component selector
arch auto -p PROJECT [INPUT]           # unattended complete design, validation, and documents
```

`arch auto` is the complete-design command: it consumes the full requirements, coordinates all applicable components, validates their relationships, and produces the complete AI system design document and supporting artifacts. It runs unattended, records permitted noncritical assumptions, and preserves manual decisions. Missing critical constraints stop the run with actionable question IDs; automatic mode does not invent authorization. It is a bounded run, not a scheduled/background monitoring service. It has no partial-scope option; use a component command for an individual design.

If retaining the previously discussed `arch design` name, implement it as a documented alias of `arch system`, for the system architecture component only. It must not become another complete-design workflow.

### Individually controllable design components

Each command below is a first-class component entrypoint accepting `-p PROJECT`, requirements inputs, and applicable common options. It designs only that component and automatically produces its own standalone design document, together with applicable diagrams/configuration. A separate `arch doc` call is not required to obtain the component document. It defaults to guided control of that component. `--mode auto` requests unattended design of that component alone.

```text
arch requirements    # PRD, interview, requirements and evidence
arch system          # system boundaries, services, interfaces and overall topology
arch api             # external/internal API contracts and enterprise API management
arch routing         # model aliases, eligible endpoints, routing and fallbacks
arch budget          # token quotas, rate/concurrency limits and spending governance
arch cache           # prompt, response, semantic and retrieval caching policies
arch workflow        # agent steps, tools, state machines and human approval
arch rag             # ingestion, chunking, embeddings, retrieval and grounding
arch data            # databases, schemas, vector indexes, object storage and retention
arch infra           # compute, networking, cloud resources, IaC and workload assets
arch resilience      # queues, retries, circuit breakers, scaling and recovery
arch auth            # identity, SSO, tenants, RBAC/ABAC and workload identities
arch guard           # input, retrieval, tool, execution and output guardrails
arch security        # threat model, trust boundaries, secrets and security control mapping
arch observe         # traces, metrics, logs, dashboards and alerting
arch eval            # quality, safety, performance and regression evaluation plans
arch cost            # deterministic workload, quota, capacity and cost scenarios
arch diagram         # selected architecture/workflow/deployment diagram views
arch doc             # complete or selected design documents and report formats
```

`arch system` controls the system-level architecture; it does not implicitly redesign every domain. `arch guard` controls guardrail policies; `arch auth` controls identity and authorization; `arch security` checks the broader threat/control model. These components share referenced entities rather than copying independent contradictory rules.

Archetypes such as voice, multimodal RAG, text-to-SQL, and agentic workflows are selected through requirements or `--archetype`, and use the same components. They do not need a new agent or command framework.

`arch cost`, `arch diagram`, and `arch doc` use deterministic engines against saved canonical state. They do not silently call an LLM to fabricate missing upstream design. With no usable state, report prerequisite fields/components. A guided run may collect explicit scenario inputs for `cost`; an automatic run uses supplied inputs only. Documents and diagrams can be partial, but must prominently show their scope and omitted/stale components.

### Project operations and manual decision control

```text
arch update PROJECT [-f FILE] [-i INSTRUCTION] [OPTIONS]
arch resume PROJECT --run RUN_ID
arch inspect PROJECT [--revision N] [--component NAME]
arch list
arch edit -p PROJECT --component NAME --file OVERRIDES.yaml
arch lock -p PROJECT --component NAME [--field FIELD_PATH]
arch unlock -p PROJECT --component NAME [--field FIELD_PATH]
arch validate PROJECT [--revision N] [--scope COMPONENTS] [--strict]
arch export PROJECT [--revision N] [--formats LIST] [--offline]
arch diff PROJECT REV_A REV_B
arch simulate PROJECT --scenario PATH [--revision N]
arch doctor
arch catalog show|validate|import [OPTIONS]
```

`edit` imports schema-validated typed changes scoped to one component. An override document contains `component`, `set` (field-path/value entries), and explicit `unset` paths; reject unknown paths, immutable metadata, type mismatches, cross-component writes, and unset operations that violate required fields. Apply it to a candidate revision atomically, show a semantic diff, and preserve prior revisions. In interactive mode review before commit; `--yes` skips the review for that explicit edit. Scripts must supply `--yes --non-interactive` to commit an edit without a terminal.

Manual choices are provenance-tagged `user_set`; inferred/generated values are tagged separately. Both component commands and `auto` preserve user-set values by default. A lock additionally forbids modification through any component generator or imported edit until explicitly unlocked. Model text and source-file instructions cannot unlock a field. An incompatible requested change produces a conflict rather than replacing a user decision.

`lock` and `unlock` are explicit local revision operations with an auditable history. Omitting `--field` locks/unlocks the component's writable domain fields. Deterministic derived values are recomputed from their inputs; users lock inputs or constraints, not fabricated cost totals. Preserve invariant relationships when importing edits.

Common generation options:

```text
--project, -p TEXT
--file, -f PATH                 # repeatable: .md, .txt, .json, .yaml, .yml
--idea, -i TEXT
--stdin
--answers PATH
--architect-provider TEXT      # provider powering the designer
--architect-model TEXT
--profile [azure-aca|azure-aks|aws-eks|agnostic]
--region TEXT
--target-providers TEXT         # allowed target inference providers
--topology [single-cloud|provider-failover|application-dr]
--policy PATH                   # budgets, identity, residency, routing constraints
--archetype TEXT                # repeatable AI workload archetype
--mode [guided|auto]            # component commands; arch auto is always automatic
--base-revision INTEGER        # existing project baseline; defaults to latest revision
--override PATH                # typed scoped overrides, same schema as edit; preserves locks
--dry-run                      # show scope, prerequisites, writes, invalidations and outputs
--non-interactive
--allow-assumptions             # only noncritical defaults; never relax hard policy
--output-dir PATH
--formats TEXT                 # default all; core or explicit comma-separated list
```

Rules:

- `arch` with no arguments starts the guided selector and appropriate interview. `arch --help` groups full-design, component, and project-operation commands. Every component has useful `--help` with examples and scope.
- Accept `arch <component> -p NAME` for an existing project, or `arch <component> -p NAME -f FILE` to create a partial project with sufficient scoped inputs. Do not require the full design to exist before designing infrastructure or guardrails.
- A focused command loads valid shared requirements and existing artifacts. It asks only questions relevant to its own scope. It must not run every specialist or regenerate unrelated designs.
- `--dry-run` performs no LLM calls, writes, or renderer execution; its deterministic plan identifies unresolved requirements, dependencies and affected outputs. Automatic source interpretation occurs only in an actual generation run.
- Component commands never generate other components to satisfy a dependency. Reuse valid project context or collect the minimum external input contract needed for the selected component. The user can run a component command first, without running `arch auto`. If a critical input is unavailable, report exactly what is needed rather than forcing a complete design.
- A full run normally schedules every applicable prerequisite, then cost/diagrams/documents. A module run writes only its declared domain fields and scoped outputs, apart from shared provenance, requirement answers, and staleness metadata.
- Configurations, diagrams, reports, and estimates affected by a changed shared interface must be marked stale. Never present inherited stale output as current. `auto` can refresh affected unlocked components; a locked incompatible dependency creates a conflict.
- Scoped validation can pass even when a project is intentionally partial. Record `scope_valid` separately from `project_complete`. Whole-project strict validation fails for missing, blocked, or stale required components. Do not label an infra-only result as a complete enterprise architecture.
- Preserve old file-only invocation compatibility: `python arch.py -p NAME -f FILE` maps to `auto`; `--update` maps to `update`; explain the mapping in help. Parse without ambiguous collisions with subcommands.
- Accept combined files, text, and stdin. Preserve each input as a separate source with a hash.
- Ask only missing or conflicting questions; support back, review, skip-if-noncritical, and save/exit. Persist after each answer.
- Noninteractive commands never prompt. Return unresolved critical question IDs as JSON and human-readable text.
- `auto` is always noninteractive. It can use policy-approved defaults for noncritical choices and records them as assumptions. Guided mode requires a terminal unless inputs are complete; a non-TTY run must not hang. Neither mode may override a user-set value or lock implicitly.
- Source precedence: explicit update answers override prior values when unambiguous; conflicting source documents create a conflict. CLI configuration overrides environment/config for settings, not silently for domain facts.
- Creation requiring model inference cannot run offline. Validation, deterministic simulation, and export of saved canonical state can.
- `--formats all` requests every applicable format within the selected scope. `--formats core` requests md,json,yaml,mmd,drawio and applicable configuration sources; no renderer binaries required. `arch doc` creates documents from a selected revision, while `arch export` packages or rerenders selected artifact types; both share the same compiler implementations.
- `arch doctor` checks configuration presence without printing secrets and reports versions of optional renderers and Terraform. No network probe by default; `--check-provider` is explicit and reports any billed call.
- Document exit codes: 0 success; 2 invalid input/incomplete critical requirements; 3 provider/auth failure; 4 semantic validation failure; 5 requested export/dependency failure; 6 project lock/state conflict; 1 unexpected internal failure; 130 interruption.

## 5. Interview and evidence model

Record fields as `provided`, `inferred`, `assumed`, `missing`, `conflicting`, or `not_applicable`, with source ID, location, value, unit, and rationale. Avoid uncalibrated numeric confidence scores.

Collect these groups:

1. Users, departments, tenants, journeys, business outcome, and acceptance metrics.
2. AI archetypes, modalities, tool permissions, autonomy, human approval, and prohibited behaviors.
3. Traffic: average/peak RPS, active sessions, per-turn model calls, input/output tokens, context, streaming, batch windows, documents/day, file sizes, and growth.
4. AI endpoints: allowed providers, deployment IDs, regions, capabilities, model eligibility, quotas, contract restrictions, retention, and processing geography.
5. Identity: Entra ID or another IdP, single/multiple tenant mode, roles/groups, user/workload distinction, and service credentials.
6. Governance: organization/department/user/application budgets, currency, reset timezone, hard/soft limit, RPM/TPM/concurrency, and unavailable-budget behavior.
7. Data: residency, classifications, ACLs, retention, deletion, indexes, embeddings, tenant partitioning, source connectors, and freshness.
8. Deployment: Azure/AWS/agnostic, AKS/Container Apps/EKS, networking, existing services, IaC ownership, team skills, and operating budget.
9. Reliability: request deadlines, TTFT, p95 completion latency, availability, recovery targets, queue maximum age, DLQ owner, and acceptable degradation.
10. Resilience scope: model/provider fallback, regional application recovery, or cross-cloud application DR; each must be chosen independently.
11. Security, audit, compliance targets, supply chain, and evaluation requirements.

Critical examples: prohibited destinations, permission for tool side effects, tenant isolation, required data location, and hard budget semantics. Never invent permission to cross a boundary because an answer is missing. A design can remain a clearly labeled draft with blocked decisions; it cannot receive a validated-release status.

## 6. Internal application architecture

Implement a modular monolith with dependency injection and these layers:

```text
Typer/Rich CLI
  -> component registry and scope/dependency planner
  -> manual decisions/locks + durable run state machine
  -> selected specialist roles + structured architect-model gateway
  -> deterministic domain engines and policy validators
  -> validated EnterpriseDesign + ArchitectureGraph
  -> configuration/diagram/document compilers
  -> immutable revision + separate export bundle + manifest
```

Core domain modules must not import Typer, Rich, provider SDKs, or subprocess utilities. Inject clocks, catalogs, tokenizers, provider clients, filesystem stores, and renderer runners through narrow interfaces.

Use an `EnterpriseDesign` object as the source of truth. `ArchitectureGraph` is a linked projection; it is not a separate conflicting architecture. Prose templates must render the same IDs, capacities, regions, budgets, and policy decisions found in canonical state.

Implement a `ComponentRegistry` with one specification per component command: owned fields, required input fields, optional context, prerequisite contracts, applicable roles, deterministic engines, validators, outputs, and downstream invalidations. Generate command help and the execution plan from this registry so `system`, `guard`, `infra`, and automatic design cannot drift into different implementations.

Model prerequisites at field/contract level, not as an assumption that every component requires a complete `system` run. A standalone infrastructure design can accept an explicit workload contract; a standalone guardrail design can accept a task/permission/data contract. Represent undesigned dependencies with typed `ExternalDependency` contracts and an explicit scope boundary, not invented services or dangling graph IDs. A missing module is absent with a recorded reason, not an empty success-shaped object.

Build an acyclic execution plan for the selected write set. Cross-component references that need reconciliation are checked by the bounded supervisor rather than encoded as an unresolvable dependency cycle. A combined run publishes one atomic design revision after scope validation; component commands publish their own incremental revision. If the baseline changes during a run, reject the commit with a state conflict rather than overwrite it.

Manual edit and automatic generation must share the same normalization, policy checks, canonical merge, invalidation, and compilation paths. Documentation is generated from the accepted state, including user decisions and locks, rather than a parallel narrative that can overwrite them.

## 7. Five specialist roles and supervisor

1. **Enterprise Requirements Architect:** extract facts, detect contradictions, interview, establish constraints, and produce `RequirementsSpec`.
2. **API Management and AI Routing Architect:** propose gateway ownership, API contracts, target endpoints, model aliases, quota/budget/cache policies, fallback eligibility, and token/cost scenarios.
3. **Cloud, Data, and Resilience Architect:** propose compute, queues/workers, state/vector/object stores, networking, failure behavior, scaling, provider failover versus application DR, and IaC specification.
4. **Identity, Security, and Observability Architect:** define tenant/identity controls, guardrails, tool authorization, OWASP mappings, audit, telemetry, and evaluation plans. Cross-check other roles' proposals.
5. **Design Verifier and Compiler:** reconcile cross-role findings into canonical state, execute deterministic invariants, emit structured diagnostics, and invoke exporters. An optional model review may improve explanations; it cannot bypass failing checks.

Every role has typed input/output, prompt version, requested permissions, timeout, token allowance, and at most two structured-output repair attempts. The supervisor permits at most two semantic revision passes after the initial proposals. If blocking conflicts remain, preserve a failed/draft run and explain the unresolved diagnostics.

A focused command invokes only the needed roles: `guard` primarily uses role 4, `infra` role 3, and `routing`/`budget` role 2; role 1 resolves scoped input gaps and role 5 validates/compiles. `system`, `rag`, and `workflow` combine relevant role 2/3 responsibilities according to their contracts. Do not invoke a model for deterministic cost recalculation or render-only commands when valid inputs already exist. The role count is independent of the number of CLI components.

Maintain a dependency graph: changed requirements invalidate affected proposals; changed routing/pricing affects estimates; changed regions affect privacy, connectivity, diagrams, and IaC; changed templates only affect corresponding exports.

The orchestration must be resumable and cancellable. Save checkpoints after each completed step. Finite retries and a total generation-call/token budget prevent runaway design generation.

## 8. Architect provider versus target providers

These are separate contracts:

- `ArchitectProvider`: the model used by `arch` to analyze and synthesize a design. Implement Gemini using `google-genai` as the baseline because it was in the original specification. Make the model ID configurable and verify current SDK syntax during implementation. Other architect adapters are optional unless selected explicitly.
- `TargetProviderSpec`: the endpoints the generated enterprise application will call, including Azure OpenAI, AWS Bedrock, OpenAI, Anthropic, and extensible alternatives. These are cataloged design/configuration targets, not required credentials for running the designer.

Use a generic structured-output interface returning a Pydantic model plus usage metadata. Validate locally even if the provider offers schema-constrained responses. Distinguish authentication, refusal, rate limit, timeout, truncated output, malformed output, and schema errors.

Store generation token/cost usage separately from projected target-system spending. Never claim to have called or tested a target provider just because its configuration was generated.

## 9. Target request flows and gateway responsibility

Define the standard interactive path as:

```text
Client with IdP token
 -> enterprise API gateway (token validation, admission, external API policy)
 -> application orchestration (tenant/ACL checks, context, RAG, HITL)
 -> model admission (budget reservation + eligible route selection)
 -> AI gateway/LiteLLM (provider adaptation, selected retries/fallback)
 -> managed AI endpoint
 -> output validation and budget reconciliation
 -> client
```

Identity is an authentication/control dependency, not a model-processing hop. Retrieval normally precedes a model call when the prompt requires retrieved context. Observability receives telemetry from all relevant stages.

The enterprise gateway can be Azure APIM, Kong, or APISIX. The AI gateway can be LiteLLM or a validated native equivalent. Emit an ownership map covering authentication, request limits, token limits, budget checks, provider retry, timeout, circuit breaker, caching, and logging. Select one authoritative owner per control to avoid duplicate retries, spend accounting, and conflicting policies.

Implement native APIM XML and LiteLLM YAML renderers for supported versions. For Kong/APISIX, emit portable policy plus an explicitly marked design-only target unless a tested native renderer is implemented. Exporting an unsupported native format must fail clearly; never return generic JSON mislabeled as deployable vendor configuration.

Use workload identity/secret references, allowlisted endpoints, and least privilege. Do not place managed-provider secrets in a browser or exported sample file.

## 10. API management, quotas, and budget governance

Model these independently:

- request rate (RPM/RPS and bursts);
- token rate (TPM with provider-specific accounting);
- concurrency and queue limits;
- hard/soft monetary budgets over a defined period;
- logical request/workflow token and step ceilings.

A Redis token bucket is an admission/rate mechanism, not automatically a durable spending ledger. Generate a durable budget-ledger design, reservation state machine, and local deterministic reference simulator. Redis may cache counters; state durability and consistency must be explicit.

Budget hierarchy: organization -> department -> application/user scope, with defined inheritance and enforcement at every applicable ancestor. Use decimal monetary values with a currency. Keep billing units separate from token-rate units.

Reservation state machine:

```text
requested -> reserved -> dispatched -> settled
                       -> unresolved -> reconciled
          -> rejected
reserved -> released (only when dispatch demonstrably never occurred)
```

Before dispatch, atomically check remaining allowance across applicable scopes, including outstanding reservations. Reserve a conservative per-attempt maximum based on estimated input, bounded output, and permitted billable charges. Each retry/fallback is a separate potentially billable attempt: either reserve the whole bounded attempt envelope upfront, or obtain an additional reservation before the next attempt.

Attach logical-request, attempt, reservation, and idempotency IDs. Settle with reported actual usage without double-counting it. A timeout, cancellation, or missing usage does not imply zero cost; retain an unresolved reservation and reconciliation task. Do not automatically release an uncertain dispatched reservation just because its TTL elapsed.

Define crash recovery and durable dispatch/outbox semantics. Unknown provider usage/rates must be labeled unknown; a hard guarantee requires an enforced upper bound on every billable dimension. Reject or require a policy change when that bound cannot be established.

For distributed/global budgets choose a consistent authority, single-writer partition, or preallocated regional spending envelopes. Asynchronously replicated counters must not be advertised as strict global limits. Describe behavior when the budget authority is unavailable; default hard-budget mode rejects new chargeable work.

Separate local token estimates, provider rate-limit accounting, and provider billing usage. Include cache reads/writes, input/output, audio/image units, embeddings, and tool charges when applicable.

## 11. Deterministic workload and cost engine

Replace GPU math with an API workload, quota, queue, and cost engine. It produces transparent scenario estimates, never live quotations or a latency guarantee.

Inputs include business RPS, calls/request by task and alias, peak factor, retries/fallback scenario, average/max input/output tokens, cache hit assumptions, batch volume, allocated RPM/TPM/concurrency per endpoint, price units, worker service time, utilization target, and cloud-service usage assumptions.

For each model/route class, calculate:

```text
primary_calls_per_minute = business_rps * 60 * model_calls_per_request
estimated_input_tokens_per_minute = primary_calls_per_minute * input_tokens_per_call
estimated_output_tokens_per_minute = primary_calls_per_minute * output_tokens_per_call

token_cost = sum(billable_units_i * price_per_unit_i)
scenario_total = model_attempts + embeddings + storage + search + queue
               + gateway + application_compute + telemetry + network

steady_worker_count = ceil(arrival_jobs_per_second * mean_service_seconds
                          / (parallel_jobs_per_worker * target_utilization))
```

Rates and quantities are decimal values with explicit units; do not add unlike units or currencies. Provider TPM enforcement formulas differ, so use the selected capability/quota profile rather than assuming input plus output is always the official quota count.

Report baseline, peak, and degraded/failover cases. Reserve enough eligible backup quota or mark the fallback capacity as unverified/insufficient. Retries may increase both cost and traffic. Cache hits reduce provider calls only for the applicable stage, not all application activity.

Queue sizing is a steady-state starting point requiring load tests. Account for retry work, visibility/lock timeouts, maximum backlog, oldest-message age, and downstream quotas when recommending replica ceilings.

Separate compute/gateway/data/network estimates from inference charges. Distinguish provisioned commitments from per-request rates. Unknown line items produce a known subtotal plus missing-cost warnings, never a false total of zero.

Provide synthetic golden fixtures with independently computed expected results. Label synthetic prices clearly and prohibit their use as current production quotations.

## 12. Intelligent routing and safe failover

Use logical model aliases tied to a task, such as `enterprise-chat` or `document-extraction`. Do not hard-code historical model names from the source examples.

An endpoint is eligible only if it meets:

- organization, tenant, and data-classification policy;
- processing and storage geography, including an inference profile's destination set;
- modality, context/output limits, tool use, response schema, streaming, and relevant API features;
- quality/evaluation threshold for the task;
- price/budget envelope, allocated quota, health, and deadline.

Filter eligibility before cost/latency ranking. Persist accepted/rejected candidates and reasons. Price uncertainty cannot be silently treated as cheapest.

Normalize errors. Transient timeouts, appropriate 429s, and 5xx may be eligible for bounded retry/fallback. Exhausted quota, authentication failure, malformed input, and safety refusal need distinct handling. Never route around a safety refusal simply to obtain a prohibited answer. Honor applicable Retry-After and the overall deadline.

Give one layer ownership of provider retries. Cap total attempts across SDK, gateway, workflow, and worker layers; do not multiply independent retry budgets. Circuit-breaker state uses closed/open/half-open and a limited probe budget.

Do not transparently restart a response after bytes have streamed to a client. Surface a resumable/interrupted result according to the target protocol. Treat uncertain tool side effects separately from model failures; no automatic replay of an external action.

Changing embedding models requires index/version compatibility. Never route a query embedding to a different vector space while keeping the same index. Agent checkpoint/history conversion and tool-schema compatibility must be evaluated before model switches.

Provider failover protects the model dependency only. Application DR additionally needs ingress, compute, identity, data, queue, secrets, budget authority, and recovery procedures in the recovery environment.

## 13. Caching

Distinguish provider prompt/prefix caching, exact response caching, semantic response caching, and retrieval caching.

Semantic caching is opt-in per eligible route. Its key/namespace and authorization filter must bind tenant, principal/permission scope, data source/index version, prompt/template version, model/route policy version, locale, and other answer-changing context. Reauthorize source access at read time where appropriate.

Specify TTL, invalidation, encryption, deletion propagation, similarity threshold, quality checks, and bypass conditions. Do not reuse responses for sensitive personal data, state-changing tool actions, or time-sensitive decisions without an explicit validated policy. Treat permission changes as invalidation events.

Report savings as a scenario based on an assumed or measured hit rate with evaluation evidence. Do not promise 30% or any other fixed saving.

## 14. Queues, workers, and failure handling

Design a synchronous streaming path for latency-sensitive chat/voice and an asynchronous path for ingestion, OCR, embeddings, batch evaluation, and long workflows.

Asynchronous path:

```text
authenticated request -> authorized job + outbox -> broker -> bounded worker
 -> authorized data/model/tool operations -> result store/status API
 -> explicit notification when required
```

Choose one coherent broker/worker combination. Baselines: Azure Service Bus with an Azure SDK worker; AWS SQS with an AWS SDK worker; Celery with Redis/RabbitMQ when requested and validated. Do not assume broker transports expose identical Celery features.

Specify at-least-once delivery, idempotent state transitions, deduplication, visibility/lock renewal, maximum attempts, retry delay, DLQ handling, poison-message quarantine, cancellation, graceful shutdown, and a redrive operator. Do not claim exactly-once external side effects.

Bound queue size, in-flight jobs, payload size, worker memory, execution time, model calls, and connection pools. Messages contain object references rather than large documents or secrets. Apply backpressure and tenant fairness when downstream quota is exhausted.

For AKS/EKS: define startup/readiness/liveness probes, requests/limits, disruption policy, and scaling. Use KEDA or a configured external metrics adapter for queue-based scaling. Do not claim ordinary CPU HPA reads a queue automatically. Avoid competing HPAs for one workload.

For Container Apps: generate supported native scaling rules and reference their identities/secrets. Do not emit raw Kubernetes resources for a Container Apps deployment. Do not require Azure Container Storage for a stateless managed-container design; select storage by actual persistence needs.

External provider outages should not automatically fail process liveness and trigger restart storms. Distinguish health signals from dependency health and degraded readiness.

## 15. Cloud profiles and data choices

Implement these profiles as tested template bundles:

- `azure-aca`: APIM, Container Apps application/router/workers, Service Bus, chosen state store, one vector store, Blob Storage, Key Vault, managed identities, and telemetry.
- `azure-aks`: APIM, AKS application/router/workers, Service Bus, KEDA, and the same justified data/security choices.
- `aws-eks`: an ingress/API management choice with verified streaming support, EKS, SQS, RDS PostgreSQL or the selected compatible state service, a supported managed vector target, S3, secrets, IAM roles, and telemetry. Entra ID can remain the enterprise IdP through verified federation.
- `agnostic`: portable logical design, policy contracts, and deployment requirements; no fake universal Terraform.

Choose Cosmos DB for documented document/state access patterns and partition/consistency needs; choose PostgreSQL when transactional/relational patterns justify it. The budget ledger needs its own explicit transactional guarantees even if chat history is in Cosmos DB. Include router metadata-store dependencies required by the pinned gateway deployment.

Select one managed vector store per workload: Azure AI Search, Qdrant Cloud, or Pinecone according to region, network access, filtering/ACL, hybrid search, scale, and contract requirements. Record embedding model, dimensions, similarity metric, index version, and deletion/reindex behavior.

For each data store specify ownership, schema/access pattern, partition key, consistency, indexing, capacity assumptions, backup, retention, encryption, tenancy, and recovery implications. Blob/S3 are object stores; they are not interchangeable with a queue or transactional ledger.

Private endpoints/network features and SKU availability must come from a verified service-capability catalog. Any unavoidable public endpoint must be shown with its TLS/auth/egress policy. Do not draw a private cross-cloud link without specifying the actual connectivity design.

Hybrid means connecting enterprise/on-prem applications, data, or edge clients to managed APIs with an approved egress path; it does not introduce local inference.

## 16. Multi-cloud and recovery design

Represent application hosting cloud, model providers, processing regions, storage regions, telemetry location, and recovery destination as independent fields.

For `provider-failover`, keep the application in its chosen hosting profile while adding eligible AI endpoints in another provider/cloud. Include cross-cloud authentication, egress, latency assumptions, destination restrictions, quotas, and extra costs. Switching the primary provider changes route preferences, not arbitrary service placement.

For `application-dr`, generate separate environment plans and IaC roots plus a runbook covering traffic switching, identity, secrets, data recovery, vector reindex/replication, queue recovery, budget consistency, split-brain prevention, dependency availability, failback, RTO/RPO assumptions, and drills. Select a supported recovery profile explicitly. A Cosmos-to-PostgreSQL migration is not automatic cross-cloud replication; require a compatible recovery data strategy or mark that topology blocked.

No claim of cross-cloud HA until the application, its state, and all critical shared dependencies have an explicit recovery design. Record degraded modes when only model-provider failover is implemented.

## 17. Identity, guardrails, and observability

Design Entra ID OIDC/OAuth2 login and access-token validation where selected. Validate issuer, audience, signature, expiry, tenant, scopes/roles, and workload identity; never trust a caller-supplied department ID for budgeting. Define how trusted claims map to the budget hierarchy and ACLs.

Enforce object-level authorization in retrieval, source download, vector filtering, cache lookup, job status, audit views, and tool execution. Define managed/workload identities and short-lived credentials per cloud. Include secret rotation without embedding secret values.

Guardrails cover input, retrieved/tool content, tool arguments, execution permissions, output schemas, sensitive-data release, and audit. Prompt-injection detection is a defense layer, not a replacement for authorization or sandbox boundaries. Bind human approval to the exact operation/arguments and invalidate it on material changes.

Include scoped SQL credentials/read-only constraints for text-to-SQL; voice deadlines and cancellation for real-time workloads; parsing isolation and size limits for document ingestion.

Map applicable threats to a versioned official OWASP Agentic Top 10 reference and, where relevant, the LLM application reference. Store source/version/ID, mitigation, owner, evidence/test, applicability, and residual risk. Do not invent category IDs or claim compliance from a checklist.

Use OpenTelemetry for correlated traces/metrics/logs and Langfuse for selected model/evaluation visibility. Include ingress, workflow, logical request, attempt, queue job, model call, budget reservation, tool call, and approval IDs. Async queues carry trace linkage appropriately.

Define SLO-linked metrics for first token/completion latency, provider error classes, route switching, retry amplification, queue age/DLQ, quota headroom, reservation contention, unresolved spend, cache correctness, retrieval quality, task success, and policy violations. Langfuse analytics are not automatically the authoritative hard-budget ledger.

Redact sensitive content; restrict telemetry payloads, region, retention, access, and sampling. Store concise decision summaries and evidence, not hidden chain-of-thought. Evaluation must cover each route and fallback, not just the primary model.

## 18. Canonical schemas and catalogs

Use Pydantic v2 with forbidden extra fields, explicit bounds/units, tagged unions, typed IDs, and cross-reference validators. Avoid claiming universal strict parsing where valid JSON serialization needs a documented conversion.

Define at least:

```text
ProjectMetadata, RunState, RevisionMetadata, SourceDocument, EvidenceRef
ComponentSpec, ExecutionPlan, ComponentState, ExternalDependency, ScopeManifest
DecisionOverride, ManualDecision, DecisionLock, InvalidationRecord
RequirementsSpec, Question, Answer, Assumption, Conflict, Decision, Risk
ArchitectProviderConfig, ArchitectUsage
EnterpriseDesign, Service, APIContract, DataStore, DataFlow, Workflow, HITLGate
IdentityPolicy, TenantPolicy, GuardrailControl, Threat, EvalPlan, ObservabilityPlan
TargetEndpoint, ModelAlias, RoutingPolicy, FallbackRule, CapabilityConstraint
QuotaPolicy, BudgetPolicy, ReservationPolicy, CachePolicy, RetryPolicy, CircuitPolicy
QueuePolicy, WorkerPolicy, DeploymentProfile, DRPlan
WorkloadScenario, RateCard, CapacityResult, CostLineItem, CostEstimate
CloudBOM, IaCSpec, NativeConfigSpec, TemplateCapability
ArchitectureGraph, Node, Edge, Group, TrustBoundary, DiagramView
ValidationDiagnostic, ArtifactRecord, ExportBundleManifest, RevisionManifest
```

IDs remain stable across revisions when semantic entities persist. Keep revision membership/hashes separate from entity identity so renames and diffs are meaningful.

Track component state as `missing`, `draft`, `valid`, `stale`, `blocked`, or `not_applicable`, with revision/input hashes and validation scope. Track `scope_valid` and `project_complete` independently in manifests. User-set field provenance and lock state must survive save/load, schema migration, updates, and automatic runs.

Versioned catalogs: models/endpoints and capabilities; service/SKU/region capabilities; prices with unit/currency/source/as-of; provider quota accounting; gateway/template version support and license requirements; OWASP references. Endpoint access and quota allocations are user/account inputs, not facts inferred from a public catalog.

Fixtures may use invented synthetic entries clearly tagged test-only. Real catalogs need sources and verification dates. Catalog import is explicit; normal generation never silently fetches new rates or arbitrary URLs. Store snapshots or content-addressed copies so old calculations remain reproducible.

## 19. Configuration and IaC compilation

Compile portable validated policies into supported native configuration; preserve portable policy as the canonical source. Each control declares `native`, `custom-runtime-required`, or `design-only`, and each renderer has a tested product/version/SKU/license capability manifest.

Produce:

- `api_gateway_and_routing_config.json` — canonical gateway and route specification;
- `litellm.yaml` — supported router/deployment aliases, endpoint/secret references, eligible fallback settings, and bounded retry ownership;
- `apim_policies.xml` where APIM is selected;
- `budgets.yaml`, `cache_policy.yaml`, `queue_policy.yaml`, `identity_policy.yaml`, and `guardrails.yaml`;
- `integration_contracts.md` describing custom runtime controls and prerequisites;
- profile-specific Terraform modules/roots and Kubernetes/Container Apps workload assets where applicable.

Do not invent LiteLLM or APIM fields for a custom reservation protocol. Emit a validated custom-service contract and simulator for that behavior, and label its integration status. Supported native config must load/parse against its pinned tooling in integration tests.

Terraform uses separate roots/states for independent environments/clouds, provider/module constraints and locks, variables/outputs, encryption, identity, explicit network rules, secret references, tags, and budget/telemetry resources where supported. No secret values in code, tfvars examples, diagrams, or state committed to the repo.

Generated app workloads need a user-supplied image reference. Validate that variable and list it as a prerequisite; do not deploy a placeholder image and call it the user's application. Config files describe a target app, not a generated business application implementation.

Run formatting and static validation. Use backend-disabled Terraform initialization only with approved package-network access and pinned dependencies; never apply or access user cloud credentials automatically. `terraform validate` does not prove the resources will deploy in a particular account/region. Record validation level precisely.

## 20. Diagrams and documents

Generate every view from canonical design/graph using deterministic code. The LLM never produces XML coordinates or raw Terraform.

Views: designer internals; target system context; interactive request; asynchronous ingestion; deployment and cloud/trust boundaries; provider fallback; budget lifecycle; HITL/workflow; recovery topology when selected.

Default target lanes: clients/identity; enterprise ingress; application/workflows; data/queues/workers; AI gateway/managed providers; security/operations. Group by cloud and region; show approved cross-cloud calls and distinguish telemetry/identity edges from payload flow. No GPU lane in managed-API mode.

Layout uses measured/wrapped labels, stable ordering, lane padding, collision detection, orthogonal routing, and pagination for large graphs. Fixed 300px columns alone are not a nonoverlap guarantee. Avoid edges through unrelated nodes; graph cycles need a deterministic back-edge route. Split crowded views rather than compressing unreadable labels.

Draw.io uses valid escaped mxfile XML with stable IDs; Mermaid uses escaped labels and matching semantic references. Generate SVG from the same layout; render PNG from that SVG using a pinned local renderer. Embed local SVG/PNG diagrams in the PDF report. Use controlled HTML/CSS, safe Markdown, and an asset allowlist; block arbitrary remote and filesystem resource loads.

Default all-formats export attempts md,json,yaml,mmd,drawio,svg,png,pdf and applicable tf/xml/workload files. A missing renderer creates an explicit failed requested artifact and exit 5, while preserving usable core output. An inapplicable artifact is `not_applicable` with a reason, not a failure. Never create dummy/empty files.

For component-only commands, apply that export policy only to scoped artifacts. `arch infra` emits infrastructure design, cloud BOM, relevant IaC/configuration, and scoped diagrams/reports; `arch guard` emits guardrail design, control policies, verification scenarios, and relevant views. It does not regenerate routing or infrastructure. `arch doc -p PROJECT --scope guard,auth --formats md,pdf` compiles selected documents; omitting `--scope` documents the available project and states its completeness. `arch diagram --view deployment` renders the chosen view only.

Give each component document a predictable name, such as `System_Design.md`, `Infrastructure_Design.md`, `Guardrails_Design.md`, or `API_Design.md`, with PDF equivalents when requested. Each document includes its component requirements, decisions, interfaces/dependencies, relevant diagrams, configuration, assumptions, and validation findings. `arch auto` generates these component documents and a consolidated `Complete_AI_System_Design` report that checks cross-component consistency. Document scope/completeness must be visible; a component document is usable on its own and does not claim the rest of the system was designed.

Documentation has manual presentation controls: `arch doc --sections LIST --audience technical|executive --template NAME --formats LIST`. Validate section/template identifiers against a trusted packaged registry. These choices control selection and presentation, not architecture facts or completeness labels. `arch diagram -p PROJECT --view system|deployment|request|ingestion|guardrails|workflow|fallback|budget|recovery --formats LIST` selects supported views. `auto` uses project defaults for documents/diagrams; explicitly saved presentation choices survive reruns. Document-only generation must not redesign the system.

The report includes requirements, decision rationale, diagrams, APIs/workflows, gateway/routing, budget/capacity, cloud BOM, data/identity, resilience, security, SLO/evaluations, IaC prerequisites, assumptions, and validation limitations. Make evidence/requirements-to-components traceability navigable.

## 21. Persistence, updates, and exports

Use this state layout:

```text
output/<project>/
  project.json
  sources/<hash>_<safe-name>
  runs/<run-id>/                  # mutable checkpoints, interview, bounded diagnostics
  revisions/0001/                # immutable accepted design
    requirements/AI_Enterprise_PRD.md
    state/requirements.json
    state/enterprise_design.json
    state/architecture_graph.json
    state/catalog_refs.json
    state/component_status.json
    state/manual_decisions.json
    state/decision_locks.json
    changes.md
    manifest.json
  exports/0001/<bundle-id>/       # immutable export bundle for a fixed design revision
    AI_System_Architecture.md
    api_gateway_and_routing_config.json
    policies/
    capacity_and_cost.json
    cloud_bom.json
    diagrams/architecture_diagram.{mmd,drawio,svg,png}
    infrastructure/<environment>/
    Complete_AI_System_Design.pdf
    validation_report.json
    manifest.json
```

Other required views live alongside the architecture diagram. Use deterministic directory ordering and relative artifact references. Maintain latest-successful-design and latest-export references separately.

Also maintain a latest accepted partial revision reference; update the latest-complete-design reference only when every required applicable component is current and valid. New focused commands and edits default to the latest accepted revision, which can be partial. Their manifests declare selected scope, read dependencies, write set, manual overrides, locks, inherited states, and newly stale components.

Updates create a new revision; exports create new bundles and do not mutate an existing revision or bundle. This resolves the conflict between immutable design history and rerunning exporters with newer templates.

Use per-project locking, safe slug/path normalization, symlink containment checks for writes, atomic directory promotion, hashes, and explicit schema migrations. User-selected source paths may be outside the output root; output writes may not escape it.

Snapshot inputs, structured provider responses with redaction, prompt/skill/template/catalog versions, settings, tool versions, and decision evidence. Deterministic re-export should reproduce bytes for fixed versions after excluding specified timestamps/metadata. New LLM generation is not promised to be identical, even with low temperature.

Source documents may contain sensitive data: use restrictive local permissions, redact logs, document retention, allow deletion/export, and make the external architect-provider data flow visible before sending content. Do not require a new permission prompt for every file once the user has chosen that workflow.

## 22. Repository layout and skills

```text
arch.py
pyproject.toml
uv.lock
AGENTS.md
README.md
SECURITY.md
.env.example
.gitignore
src/archai/
  cli.py, config.py, errors.py, logging.py, __main__.py
  schemas/
  application/             # registry, scope planner, commands, supervisor, five roles
  architect_providers/     # Gemini adapter and provider-neutral protocol
  ingestion/
  interview/
  domain/
    routing.py, budgeting.py, cost.py, quota.py, cache.py, resilience.py
    cloud.py, security.py, graph.py, validation.py, decisions.py
  simulators/              # local policy/failure/budget reference engines
  persistence/             # locks, runs, revisions, manifests, migrations
  compilers/
    gateway.py, litellm.py, apim.py, terraform.py, workload.py
    drawio.py, mermaid.py, svg.py, report.py
  exporters/               # bounded subprocess/rendering adapters
  resources/
    prompts/
    skills/
      enterprise_prd/SKILL.md
      api_routing_and_budgets/SKILL.md
      resilience_and_queues/SKILL.md
      cloud_data_and_identity/SKILL.md
      guardrails_observability/SKILL.md
    catalogs/
    templates/
tests/{unit,integration,property,golden,e2e}/
examples/{azure-enterprise-rag,aws-agentic-support,provider-failover}/
docs/{architecture,cli,catalogs,configuration,security,limitations}.md
.github/workflows/ci.yml
```

Use separate real files rather than literal comma-separated filenames. Include resource files in wheels and load through `importlib.resources`; installed commands must not depend on the source checkout's working directory.

Skill selection uses trusted bundled metadata and detected archetypes. Record skill versions, include only relevant instructions, and reject source documents pretending to install/replace skills. Skills guide generation; compiled validators enforce policy.

Dependencies: Typer, Rich, Pydantic v2/settings, google-genai baseline, safe YAML/Markdown/XML handling, Jinja2, and appropriate locking/rendering libraries. PDF/image extras are optional installation groups. Do not require production target SDKs/cloud services for core CLI tests. Add pytest, Hypothesis, Ruff, mypy, and build tooling for development.

## 23. Verification and acceptance

Test domain behavior with independent expected values, then integration/CLI behavior. Production runtime must never use a fake model response; deterministic fakes and synthetic price catalogs are allowed in clearly isolated tests/examples.

Required tests:

1. Terminal/file/combined input, resumable interview, conflicting facts, and noninteractive missing requirements.
2. Structured output repair bounds, provider error taxonomy, call-budget exhaustion, cancellation, and resume invalidation.
3. Unit-safe estimates, missing prices, token accounting profiles, quotas, peak/failover scenarios, and cost fixture math.
4. Concurrent budget reservation simulation: applicable scopes never accept an amount above available authorized capacity; retries consume separate reservations; duplicated settlements are idempotent; uncertain dispatch retains liability; budget-authority outage follows policy.
5. Route exclusion for residency/modality/tool/schema/context constraints; no fallback on safety refusal; bounded attempts; no transparent replay after a stream begins.
6. Tenant/ACL-safe cache lookups and permission-change invalidation; changed embedding model/index rejected without migration.
7. Queue redelivery/idempotency, poison message/DLQ, bounded backpressure, interruption, and worker autoscaling constrained by provider quotas.
8. Stable semantic IDs across revisions, no graph orphans, same references in policies/diagrams/IaC, nonoverlapping layout, escaping, and independent XML parse checks.
9. Atomic writes, locks, output path traversal/symlinks, revision immutability, new export bundles, migrations, and reproducible deterministic re-export.
10. Template capability checks and native YAML/XML validation; Terraform checks for every shipped profile, and no deployment side effects.
11. Installed-wheel smoke test outside the repository to verify packaged templates/catalogs/skills.
12. Export failure reporting, requested-versus-inapplicable artifacts, secret redaction, renderer network/file restrictions, and prompt injection treated as data.
13. Every registered component command has guided/automatic behavior or a documented deterministic-only implementation. Test scoped reads/writes: infra-only generation does not call routing/guardrail synthesis or change their domain values; guard-only generation cannot rewrite infrastructure.
14. New partial projects work with sufficient component inputs, without a prior complete design. Missing prerequisites ask for scoped input or block; they never trigger generation of another component. Every component design command emits its own document automatically. Changed inputs mark downstream outputs stale; full strict validation rejects an incomplete/stale project while scoped validation can succeed.
15. Manual overrides validate types/ownership; imported changes cannot unlock fields. `auto` preserves user-set/locked decisions, detects incompatible locked dependencies, and produces an explicit conflict. Derived totals cannot be set as arbitrary manual values.
16. `auto` completes every applicable component and their documents plus the consolidated system design from complete input without prompts. Focused commands never expand beyond their component; dry-run performs no writes/LLM calls. Cost/diagram/doc commands use saved data without hidden model calls. Both `arch` and `archai` aliases resolve to the same application.

Acceptance examples:

```text
arch auto -p eu-support -f examples/azure-enterprise-rag/requirements.md \
  --answers examples/azure-enterprise-rag/answers.yaml \
  --profile azure-aca --topology provider-failover --non-interactive --formats core

arch update eu-support -i "Limit Finance to a hard monthly budget; allow only EU processing; require approval before refunds" \
  --answers examples/azure-enterprise-rag/update-answers.yaml --non-interactive

arch simulate eu-support --scenario examples/provider-failover/timeout-and-429.yaml
arch validate eu-support --strict
arch diff eu-support 1 2
arch export eu-support --revision 2 --offline --formats all
```

Manual and automatic component-control acceptance:

```text
arch system -p controlled-support -f examples/azure-enterprise-rag/requirements.md
arch infra -p controlled-support --profile azure-aca
arch guard -p controlled-support --override examples/azure-enterprise-rag/guard-overrides.yaml
arch lock -p controlled-support --component guard
arch routing -p controlled-support --mode auto --answers examples/azure-enterprise-rag/answers.yaml
arch auto -p controlled-support --answers examples/azure-enterprise-rag/answers.yaml --formats core
arch doc -p controlled-support --scope guard,infra --formats md,pdf
arch validate controlled-support --strict
```

The fixture must make the guarded decisions compatible with the remaining full design. Verify that automatic completion preserves them byte-for-byte at the owned-field level, updates only derived metadata, and generates documentation that matches them. Also test an incompatible fixture that stops with a conflict rather than overriding the lock.

Fixtures supply any missing monetary amount/region/endpoint details; the CLI cannot invent them from the prose example. Example model IDs are verified identifiers or clearly unresolved user parameters, not claims of universal availability.

Required checks: `ruff format --check .`, `ruff check .`, `mypy src`, `pytest -q`, `python -m build`, installed-package smoke test, core end-to-end create/update/simulate/export. Run golden/native/renderer/IaC integration checks in the appropriate documented CI environment. No passing claim for a skipped dependency or cloud connectivity test.

Use quality thresholds based on meaningful branch coverage of routing, budgets, persistence, and validators, not a blanket percentage inflated by easy boilerplate tests.

## 24. Delivery milestones and final handoff

Build in integrated milestones and continue until the requested scope is implemented or a concrete blocker requires user input:

1. ArchAI packaging/entrypoints, component registry, typed schemas, runs/revisions, ingestion, interview, and provider gateway; deliver a working terminal-to-validated-requirements path.
2. Scope/dependency planner, manual overrides/locks, five-role supervisor, canonical design, route/budget/quota/cache/cost validators, and local simulation; deliver both focused component commands and full automatic design end to end.
3. APIM/LiteLLM and cloud-profile compilers, Terraform/workload assets, versioned capability catalogs, and deployment prerequisites.
4. Canonical graph, all diagram/document exports, revision updates/diffs, and reproducibility.
5. Acceptance fixtures, failure/security tests, packaging/CI, examples, and documentation. Fix regressions and inspect representative rendered diagrams/PDFs.

The README must explain designer versus target runtime, installation, architect credentials, supported native targets, all CLI commands, cost assumptions, data sent to the model, optional tools, partial export status, catalog provenance, and deployment prerequisites. `AGENTS.md` should hold concise repository rules and validation commands, including the Git identity/attribution policy in section 25. Preserve any existing user-authored rules when extending that file.

At handoff report implemented features, actual verification results, run commands, sample output paths, unsupported native targets/custom-runtime dependencies, and remaining blockers. Do not call the repository complete while required code paths are stubs or required tests fail. Do not equate local policy simulation or syntax validation with a deployed enterprise system.

Initial defaults:

```yaml
product: ArchAI
repository_slug: archai
python_package: archai
cli_command: arch
cli_alias: archai
version_scope: enterprise-managed-api-v2
component_control: guided-and-automatic
auto_default_scope: all-applicable-components-and-documents
preserve_manual_decisions: true
runtime: local-python-cli
architect_provider: gemini
architect_model: configure-at-installation
inference_mode: managed-api
default_profile: azure-aca
default_topology: single-cloud
fine_tuning: forbidden
self_hosted_inference: out-of-scope
gpu_sizing: not-applicable
default_formats: all
deployment_actions: forbidden
```

## 25. Git authorship and attribution policy

This policy applies to every new commit the coding agent creates for the user in this repository, including commits later pushed to a remote:

- Use the user's configured Git name and email for both author and committer. Inspect effective identity before committing, including environment overrides. `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT` show the effective identities; repository `user.name` and `user.email` alone may not reveal an override.
- Never substitute Codex, Copilot, Claude, an assistant, a bot, or a fabricated identity. If the expected user identity is missing or ambiguous, ask for the correct name/email before making a commit; implementation work can continue meanwhile. Do not infer identity from the local directory/account name.
- Do not add `Co-authored-by:` trailers, AI `Signed-off-by:` trailers, `Generated-by:` trailers, or assistant-credit messages such as “Generated with Codex/Copilot” to new commit messages. Preserve an existing requirement for the user's own sign-off or commit signing; do not impersonate a signer or disable signing settings.
- A push transfers commits; it does not replace their author metadata. Before an authorized push, resolve the exact outgoing refs/range and inspect every new agent-created commit in that range for effective author, committer, and message trailers. If a mismatch is found, report it before pushing; do not automatically rewrite previously committed or published history.
- Do not strip legitimate attribution from imported code, dependency licenses, or historical commits. This policy governs new work performed for this user, not rewriting other people's contributions.
- Do not change global Git configuration, authentication, remotes, hooks, or signing settings to enforce this preference. Use repository-local identity settings only with the user's supplied values. Creating the project does not itself authorize publishing it or force-pushing history.
- Keep this concise policy in root `AGENTS.md`. If the repository already has instructions for other coding tools, keep their attribution guidance consistent. Do not claim one instruction file controls every external tool, hosting service, or server-generated merge commit.

Document these user-run setup commands, with clearly labeled placeholders, for the cloned repository:

```sh
git config --local user.name "YOUR NAME"
git config --local user.email "YOUR EMAIL"
```

Do not execute these placeholder values or guess replacements. Do not create a commit or push merely to test attribution. When a commit is actually requested, verify its resulting metadata and message before any requested push.

# END BUILD PROMPT

## Reference notes for implementation

The specifications above are engineering requirements, not claims that any one gateway supplies every control. Verify native fields and editions against the pinned products during implementation.

- Gateway roles and topology: [Microsoft architecture guidance](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/generative-ai-gateway-multiple-models).
- Native retry/fallback configuration: [LiteLLM fallbacks](https://docs.litellm.ai/docs/proxy/reliability). Budget configuration: [LiteLLM budgets and rate limits](https://docs.litellm.ai/docs/proxy/users). The reservation ledger and strict cross-cloud rules in this prompt are additional design requirements, not asserted native LiteLLM guarantees.
- Failure-state design: [Microsoft circuit-breaker pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker).
- Queue scaling: [KEDA Service Bus scaler](https://keda.sh/docs/2.18/scalers/azure-service-bus/) and [Container Apps scaling](https://learn.microsoft.com/en-us/azure/container-apps/scale-app).
- Broker capabilities must be verified individually: [Celery broker documentation](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/index.html).
- Processing region includes destination profiles: [Bedrock cross-region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html).
- Versioned security mapping: [OWASP Agentic Top 10 announcement and reference](https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/).

