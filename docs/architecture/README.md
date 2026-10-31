# Architecture

ArchAI 1.0.0 is a modular local CLI. `arch auto` designs every applicable component.
A component command asks the same opening description on a new project, then designs only
that component, so the revision stays partial until the rest are saved. Both share one
registry, one canonical `EnterpriseDesign`, a linked `ArchitectureGraph`, immutable
revisions, and a project-folder export (documents, diagrams, config, infrastructure, state).

## Run flow

```text
arch auto / arch <component>
  -> inputs (files, --idea, --answers, stdin) merged into a requirements draft
  -> Enterprise Requirements Architect: intake analysis (suggestions + clarifying questions)
  -> guided interview on a terminal, starting with the application description
     (persisted after every answer; resumable)
  -> RequirementsSpec validated
  -> deterministic baseline for every scoped component (apply_scope)
  -> Supervisor
       PRD: Enterprise Requirements Architect
       Architecture plan: Chief Architect picks the style, services, interfaces, and the
         ArchAI defaults to change; the specialists design from this plan
       Cloud, Data, and Resilience Architect: system, data, workflow, rag, infra, resilience
       API Management and AI Routing Architect: api, routing, budget, cache
       Identity, Security, and Observability Architect: auth, guard, security, observe, eval
       Each proposal is merged before the next role starts; Python's structural checks run on
         it at once and send a broken service graph straight back to its role (self-check)
       Design Verifier and Compiler: each blocking finding names the fields its fix must change
       Every role that owns one of those fields revises it, one role at a time, PRD included
       A finding that only disputes a value taken from the requirements is kept as a warning
       The run stops at the repair limit or the call budget; open findings make the revision a draft
       Python invariants set the fixed facts: model-call limit, attempt limit, recovery scope,
       planning quotas, approval inbox, and a public surface equal to the API contracts
  -> deterministic capacity/cost engine, policy invariants, manual decisions, locks
  -> validation -> immutable revision -> project folder (Markdown, PDF, diagrams, IaC, configs,
     High_Level_Design, Low_Level_Design, and Master_Design)
```

The same path, including interview exits, provider failover, and export, is drawn in
[application-flow.mmd](application-flow.mmd). Cloud, API, and security run one after another on
the first pass.

Repairs follow the fields a finding names, not the single component it is filed under. The
verifier lists the design fields the fix must change (for example
`services.svc-retrieval.depends_on` and `identity_policy.service_identities`). Each field maps
to the component that owns it, and decision ids cited in the finding map to their component, so
one finding can go to the cloud role and the security role. The PRD role is a repair target
too. Repairs run in the first-pass order, one role at a time, with invariants applied after
each, so a later role sees the earlier fix. A repairing role receives the full current content
of its components and the finding, split into what it changes and what other owners change,
and returns that content with only those changes.

`fixed_facts` are values Python sets from the requirements: the model-call hard limit and what
it covers, the attempt limit and its owner, the endpoint planning envelope, the allowed regions
and recovery targets, tenant isolation, and the approval operations. Every role and the verifier
receive them. Python writes one decision record per fact (source `fixed from requirements`), and
a finding that only disputes those values is kept as a warning instead of being sent to a role
that cannot change them.

Python owns what the requirements fix and checks the rest. Endpoints are an example: ArchAI
creates one deployment per allowed provider, and a standby in another allowed region for
`application-dr`. The routing role may add deployments; each is kept only when its provider is
allowed and its region is in `data_residency`, and a rejected one is reported back with the
reason (`archai_rejected_changes`) to the verifier and to the role's next repair. The
disaster-recovery plan is the resilience role's text unless it names a region outside
residency. Python does not rewire services: `application/checks.py` reports a missing
request path, an admission service no one calls, or a dependency cycle as a finding for the
system role.

Repairs and later reviews read less. The first review sees the whole design. Later passes
see only the components that changed and those the open findings name, plus `design_index`,
a compact list of every component's ids, references, scopes, and decision titles. A repair
sees its own components in full, the index, and a PRD digest, and returns a patch: only the
services, stores, workflows, contracts, guardrails, threats, and decision records it adds or
changes, plus `remove_ids`; ArchAI keeps everything it leaves out. Each prompt starts with the
role's fixed instructions and puts the run's data after `# Context`, so providers cache the
instructions: OpenAI with a stable `prompt_cache_key`, Anthropic with `cache_control`. Cached
input tokens are recorded per call and shown in the run summary.

Review converges because it answers fixed questions. `application/acceptance.py` builds an
acceptance checklist from the requirements and the PRD: one criterion per hard requirement
(residency, tenancy, budget, identity, side effects, classification, latency, recovery,
channels, each integration and data source), per must-have functional requirement, per
non-functional target, and per user journey. The verifier marks each criterion pass or fail
with evidence; a failure is a blocking finding with the criterion's id, so it is tracked
across passes. The first pass answers every criterion; later passes answer the failed ones
and those touching changed components. After the first review, a new open-ended finding can
block only when it is about a part that changed; otherwise it is kept as a warning. The design
is complete when every criterion passes and no blocking finding is open. The CLI and the
complete design document show the criteria with their status and evidence.

Python derives facts instead of asking a second agent to restate them
(`application/derive.py`): a grant on the caller's identity for every service call and store
it uses, user sign-in scopes covering every role's operation scopes, a guardrail owner as a
service id, and the retry policy's opening sentence from `queue_policy.max_attempts`.
`application/checks.py` also reports a retry text with a different delivery count, and a
workflow step naming an operation, service, or store that does not exist.

When fixing something depends on a business choice, the verifier lists it in
`decisions_needed` instead of a defect. In an interactive run ArchAI asks the person running it;
an answer is stored as a clarification and the owners of the affected components apply it.
Unanswered decisions are listed on the revision, in the CLI summary, and in the complete
design document, and do not block. ArchAI also writes them to `<project>/decisions.yaml`;
fill in the answers and run `arch update <project> --answers <project>/decisions.yaml`.
Answers are added to the saved clarifications (a newer answer to the same question replaces
the older one), and the update re-designs the project with them.

The verifier receives the previous pass's findings with ids and marks a repeat with `same_as`.
A finding is resolved when a later pass no longer repeats it. One that is still open after two
repairs of its components is not sent again. When no blocking finding is open, `arch auto` is a
complete design. If the repair limit or the call budget is reached first, the revision is saved
as a draft: `project_complete` is false, the open findings stay on the revision and in
`validation_report.json`, and the CLI lists them with the component command that re-runs the
owning role. A component command can still be partial because the other components were outside
its scope.

Each role call uses a scoped structured-output schema built from only the components in scope, so
`arch infra` asks the cloud role for infrastructure fields alone. Calls share a run budget
(`ARCHAI_MAX_GENERATION_CALLS`, `ARCHAI_MAX_GENERATION_TOKENS`). Roles can be bound to different
providers and models (`ARCHAI_ROLE_MODELS`); if a provider fails with a quota, availability, or
credential error and another provider is configured, the role retries there and the failing
provider is skipped for the rest of the run. Transient failures without an alternative fall back to
the deterministic baseline with a warning; the component's "Designed by" label records which.

## Modules

- `interview/` — typed question bank and the resumable interview session (UI-independent).
- `application/supervisor.py` — five roles, prompts, call budget, failover, and the repair loop.
- `application/findings.py` — maps the fields a finding names to the components and roles that
  own them, and detects findings that only dispute fixed facts.
- `application/checks.py` — structural checks Python reports as findings instead of fixing.
- `application/derive.py` — facts Python derives from the design (grants, sign-in scopes,
  guardrail owners, queue retry sentence).
- `application/acceptance.py` — the acceptance checklist the verifier answers every pass.
- `application/merge.py` — proposal validation and Python-owned invariants, including the fixed
  facts, in-region recovery, planning quotas, the approval inbox, and the public surface.
- `application/designer.py` — deterministic baseline and graph projection.
- `compilers/` — documents (`report.py`, `master.py`, `hld.py`, `lld.py`), hop compiler
  (`hops.py`), Mermaid views (`views.py`, `diagram.py`), PDF drawings (`scene.py`, `pdf.py`),
  Terraform and Kubernetes (`terraform.py`), exports (`export.py`). High-level and low-level
  packages are compiled documents, not design components. Diagram files are Mermaid only.
- `domain/scale.py` — the scale-up contract. The complete design document, the scale diagram,
  and the generated autoscaler minimums and maximums all use this one calculation.
- `ui.py` — Rich interview prompts, live status board, summaries.

The generated target system is distinct from the designer. Target assets describe managed model
APIs, gateway responsibilities, durable budget reservation, identity, queues, data, guardrails,
telemetry, and reviewed infrastructure. They are never applied by ArchAI.
