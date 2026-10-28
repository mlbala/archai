# ArchAI

An AI system-design CLI that turns requirements into complete enterprise architectures or focused component designs, with diagrams, documentation, and infrastructure configurations.

**Product:** ArchAI · **Repository / Python package:** `archai` · **CLI:** `arch` · **CLI alias:** `archai`

## Project status

This repository starter contains the implementation specification, architecture, diagrams, and coding-agent instructions. The application has not been implemented yet. The commands below describe the required product behavior; they are not commands available from this starter alone.

Start with [START_HERE.md](START_HERE.md), then use [BUILD_PROMPT.md](BUILD_PROMPT.md) as the implementation contract. The coding agent should replace this status section with verified installation and usage instructions once the application is built.

## What ArchAI will do

ArchAI takes requirements from the terminal or files and designs enterprise AI applications that use managed model APIs. It covers API management, model routing and failover, token and spending budgets, identity, guardrails, workflows, retrieval, data storage, cloud infrastructure, resilience, observability, and evaluations.

There are two ways to use it:

- **Complete design:** `arch auto` coordinates all applicable components, checks that their designs agree, and produces a complete AI system design package.
- **Component design:** commands such as `arch infra`, `arch guard`, and `arch system` design only the selected component and automatically create its standalone design document. No previous `arch auto` run is required when the necessary inputs are supplied.

Users can review and edit choices, lock decisions, and let automatic runs complete the remaining work while preserving those choices. Project revisions and export bundles retain history and identify stale dependent outputs.

## Planned command examples

```sh
# Complete AI system design and documentation.
arch auto -p support -f requirements.md --answers answers.yaml

# Independent component designs, each with its own document.
arch system -p support -f requirements.md
arch infra -p support --profile azure-aca
arch guard -p support -f guardrail-requirements.md

# Protect a decision before further automatic design.
arch lock -p support --component guard

# Inspect or rerender existing design outputs.
arch inspect support
arch doc -p support --scope infra,guard --formats md,pdf
```

Other components include `requirements`, `api`, `routing`, `budget`, `cache`, `workflow`, `rag`, `data`, `auth`, `security`, `resilience`, `observe`, `eval`, `cost`, and `diagram`. Their precise behavior and acceptance tests are in [BUILD_PROMPT.md](BUILD_PROMPT.md).

## Intended outputs

- Requirements and decision records.
- Complete or component-specific system design documents.
- Versioned JSON state and YAML policies.
- Mermaid, Draw.io, SVG, and PNG diagrams.
- Markdown and PDF reports.
- Applicable Terraform and native gateway/workload configuration.
- Workload, quota, capacity, and cost scenarios with visible assumptions.
- Validation reports and artifact manifests.

The designer generates infrastructure configurations; it does not deploy cloud resources. The current scope uses managed AI APIs and excludes fine-tuning and self-hosted GPU inference.

## Starter contents

```text
README.md
START_HERE.md
AGENTS.md
BUILD_PROMPT.md
ARCHITECTURE.md
.gitignore
LICENSE-MIT.template
diagrams/
  designer-internals.mmd
  enterprise-target.mmd
```

The architecture is explained in [ARCHITECTURE.md](ARCHITECTURE.md). The diagram sources describe [the designer itself](diagrams/designer-internals.mmd) and [an example enterprise target](diagrams/enterprise-target.mmd).

## Git identity and attribution

New agent-created commits must use the repository owner's configured name/email as author and committer, with no AI co-author trailers or generated-by credit. [AGENTS.md](AGENTS.md) contains the rule and the checks required before commits and pushes. Supply your own identity locally; this starter does not configure Git, create commits, or push anything.

## License decision

The MIT license is supplied as `LICENSE-MIT.template`, with a copyright-holder placeholder. It is an unselected template, not a statement that the project is already MIT-licensed.

If you choose MIT, replace `[COPYRIGHT HOLDER NAME]` with the correct person or organization, rename the file to `LICENSE`, and update this section to state the chosen license. MIT permits reuse, modification, distribution, and commercial use subject to its notice conditions. See [the MIT license summary and text](https://choosealicense.com/licenses/mit/).

Keep any existing repository license unless you deliberately choose to replace it. License choice and Git commit attribution are separate decisions.
