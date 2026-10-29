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
       PRD (role 1)
       Cloud, Data & Resilience Architect (role 3): system, data, workflow, rag, infra, resilience
       API & Routing Architect (role 2) ‖ Identity, Security & Observability Architect (role 4)
       ProposalMerger: normalize IDs, drop dangling references, clamp values
       Design Verifier (role 5): findings; blocking ones trigger <= 2 targeted revision passes
  -> deterministic capacity/cost engine, policy invariants, manual decisions, locks
  -> validation -> immutable revision -> project folder (Markdown, PDF, diagrams, IaC, configs,
     High_Level_Design, Low_Level_Design, and Master_Design)
```

Each role call uses a scoped structured-output schema built from only the components in scope, so
`arch infra` asks the cloud role for infrastructure fields alone. Calls share a run budget
(`ARCHAI_MAX_GENERATION_CALLS`, `ARCHAI_MAX_GENERATION_TOKENS`). Roles can be bound to different
providers and models (`ARCHAI_ROLE_MODELS`); if a provider fails with a quota, availability, or
credential error and another provider is configured, the role retries there and the failing
provider is skipped for the rest of the run. Transient failures without an alternative fall back to
the deterministic baseline with a warning; the component's "Designed by" label records which.

## Modules

- `interview/` — typed question bank and the resumable interview session (UI-independent).
- `application/supervisor.py` — five roles, prompts, call budget, failover, revision passes.
- `application/merge.py` — proposal validation and Python-owned invariants.
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
