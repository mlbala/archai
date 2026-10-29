# ArchAI

ArchAI is a terminal AI solutions architect. It interviews you about an AI application, then a
team of five specialist AI architects designs the complete system — microservices, APIs and API
management, model routing and fallback, token budgets, caching, workflows and human approval,
RAG, data stores, cloud infrastructure, resilience, identity and OAuth 2.0, guardrails, threat
model, observability, evaluation, and capacity/cost. It saves every design as an immutable
revision and exports Markdown and PDF documents, architecture diagrams, Terraform, Kubernetes
manifests, LiteLLM and APIM configuration, and policy files.

The primary command is `arch`; `archai` is an equivalent alias (macOS already has `/usr/bin/arch`).
ArchAI generates reviewed design assets. It never deploys or provisions anything.

## Install

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
hash -r
archai --help
```

An activated virtual environment normally puts this package's `arch` first on `PATH`; use
`archai` if your shell still resolves the system command.

## Choose your architect models

ArchAI works with four providers. Pick any of them after cloning; each needs only its API key.

| Provider | `--architect-provider` | Default model | Key variable | Other suggested models |
| --- | --- | --- | --- | --- |
| OpenAI (default) | `openai` | `gpt-6-sol` | `ARCHAI_OPENAI_API_KEY` or `OPENAI_API_KEY` | `gpt-6-luna` (cheaper), `gpt-6-astra` |
| Anthropic Claude | `anthropic` | `claude-opus-5-5` | `ARCHAI_ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY` | `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-fable-5-1` |
| Google Gemini | `gemini` | `gemini-3.1-pro-preview` (paid tier) | `ARCHAI_GEMINI_API_KEY` or `GEMINI_API_KEY` | see `archai model list gemini --remote` |
| DeepSeek | `deepseek` | `deepseek-v4-pro` | `ARCHAI_DEEPSEEK_API_KEY` or `DEEPSEEK_API_KEY` | `deepseek-flash` |

Switch from the terminal (writes a private `./.env`, mode 600; add `--global` for
`~/.config/archai/.env`):

```sh
archai model use anthropic --key                 # Claude Opus 5.5; prompts for the key
archai model use gemini gemini-3.8-flash --key   # any model ID your key can use
archai model use deepseek deepseek-v4-pro --key
archai model use openai gpt-6-luna               # switch back, cheaper OpenAI model
archai model show                                # which model each role uses, keys present
archai model list --remote                       # models your keys can actually use (free)
archai setup                                     # or the guided wizard
```

Settings come from environment variables, `~/.config/archai/.env`, then `./.env` (environment
variables win). Use any model ID that supports structured output; model calls are billed by your
provider. How each provider is used:

- **OpenAI**: Responses API with strict structured outputs.
- **Anthropic**: Messages API with JSON-schema output, streamed; `effort` is `high` by default
  (`ARCHAI_ANTHROPIC_EFFORT`, empty to omit) and server-side refusal fallbacks are on for
  Opus/Sonnet 5.5 and Fable 5.1 (`ARCHAI_ANTHROPIC_FALLBACKS=false` to disable).
- **Gemini**: JSON-schema output. Pro preview models need a paid tier.
- **DeepSeek**: OpenAI-compatible JSON mode at `ARCHAI_DEEPSEEK_BASE_URL`
  (default `https://api.deepseek.com`); the schema is enforced locally with repair retries.

**Mix models per role.** Any role can use a different provider, for example a second provider as
the cross-checking verifier:

```sh
archai model use anthropic claude-sonnet-5-5 --role verifier
archai model clear --role verifier
# or per run:
arch auto -p support --role-model verifier=anthropic:claude-sonnet-5-5 --role-model cloud=deepseek
```

Roles: `requirements`, `cloud`, `api`, `security`, `verifier`. If a provider runs out of quota,
rate-limits, or rejects its key and another provider has a key, the role switches to it for the
rest of the run. Without any API key ArchAI uses a deterministic baseline design (also available
with `--offline`) and labels every document as such.

## Complete design: `arch auto`

```sh
arch auto
```

On a terminal this:

1. asks for a project name and a description of the application (unless given with `-p`, `-i`,
   `-f`, or `--answers`);
2. sends the description to the **Enterprise Requirements Architect**, which pre-fills
   suggestions and writes app-specific clarifying questions;
3. interviews you about everything still missing — users and roles, AI workload types, tool side
   effects, traffic and tokens, allowed providers, hosting profile and region, data residency,
   identity provider and tenancy, data classification and compliance, availability, latency,
   RTO/RPO, and the hard monthly budget. Press Enter to accept a default or AI suggestion; type
   `back`, `skip` (optional questions), `?`, or `save` to stop and resume later. Answers are saved
   after every question. A review table lets you change any answer before the design starts;
4. runs the design team with a live status board:
   - Requirements Architect → PRD
   - Cloud, Data & Resilience Architect → microservices, data stores, workflows, RAG, infra,
     resilience
   - API Management & AI Routing Architect and Identity, Security & Observability Architect
     (in parallel) → APIs, routing, budgets, caching / OAuth flows, RBAC, workload identities,
     guardrails, STRIDE + OWASP LLM threat model, observability, evaluation
   - Design Verifier → cross-component review; blocking findings trigger at most two targeted
     revision passes
   - deterministic engines → capacity and cost, policy invariants, validation;
5. saves an immutable revision and an export bundle, and prints a summary with the PDF path.

Model output is treated as an untrusted proposal: Python validates it, normalizes IDs, drops
dangling references, and enforces the rules that matter (data residency, hard-budget rejection,
cache namespace binding, no embedding fallback, human approval when side effects need approval,
required token claims). Prices, quotas, and deployment IDs are never invented.

For scripts and CI, nothing prompts:

```sh
arch auto -p eu-support -f examples/azure-enterprise-rag/requirements.yaml \
  --profile azure-aca --topology provider-failover --non-interactive --formats core
```

Missing critical answers stop a non-interactive run with exit code 2, the question IDs (text and
JSON), and a run ID. Continue with `archai resume PROJECT --run RUN_ID` (interactive on a
terminal) or supply `--answers answers.yaml`.

## What you get

```text
output/<project>/
  revisions/0001/                      immutable design: state/*.json, documents/*.md, manifest
  exports/0001/<bundle>/
    Complete_AI_System_Design.md|pdf   consolidated design with diagrams and traceability
    requirements/AI_Enterprise_PRD.md|pdf
    documents/<Component>_Design.md|pdf   one standalone document per component
    diagrams/<view>.{mmd,svg,png}      architecture, request flow, OAuth flows, deployment,
                                       data ownership, ingestion, workflows, budget lifecycle,
                                       provider fallback, async jobs, guardrails, recovery,
                                       scale-up
    diagrams/architecture_diagram.drawio
    infrastructure/primary/*.tf        Terraform root for the profile (azure-aca, azure-aks, aws-eks)
    workloads/kubernetes/*.yaml        Deployments, HPAs, KEDA ScaledObjects (AKS/EKS)
    litellm.yaml, apim_policies.xml    AI gateway and enterprise gateway configuration
    policies/*.yaml                    budgets, cache, queue, identity, guardrails
    integration_contracts.md           custom runtime contracts the app must implement
    enterprise_design.json, architecture_graph.json, validation_report.json, manifest.json
```

`--formats core` writes md, json, yaml, mmd, drawio, svg, tf, and xml. `--formats all` (default)
adds PNG and PDF.

## Component commands

Every component can be designed on its own and writes only its own fields and document:

```sh
arch system -p support -f requirements.yaml   # interviews on a terminal; --mode auto to skip
arch infra -p support --profile azure-aca
arch auth -p support                          # OAuth flows, RBAC, workload identities
arch guard -p support --override examples/azure-enterprise-rag/guard-overrides.yaml
arch lock -p support --component guard
arch auto -p support --formats core           # completes the rest; locked parts are preserved
```

Components: `requirements`, `system`, `api`, `routing`, `budget`, `cache`, `workflow`, `rag`,
`data`, `infra`, `resilience`, `auth`, `guard`, `security`, `observe`, `eval`, `cost`, `diagram`,
`doc`. `arch design` is an alias of `arch system`. A component command only dispatches its own
architect role plus the verifier.

## Project operations

```sh
arch status [PROJECT]          # component status, completeness, latest export, resumable runs
arch list
arch doc -p PROJECT [--scope guard,infra] [--formats md,pdf]   # re-render documents, no model calls
arch diagram -p PROJECT --view deployment
arch export PROJECT [--revision N] [--formats all]
arch inspect PROJECT [--component NAME]
arch edit -p PROJECT --component NAME --file OVERRIDES.yaml [--yes]
arch lock|unlock -p PROJECT --component NAME [--field PATH]
arch validate PROJECT [--strict]
arch diff PROJECT 1 2
arch simulate PROJECT --scenario examples/provider-failover/timeout-and-429.yaml
arch update PROJECT -i "Only EU processing" --answers update.yaml
```

Add `--dry-run` to any design command to see its scope, roles, writes, and documents without
writing files or calling a model.

Exit codes: 0 success, 2 missing/invalid input, 3 provider or authentication failure, 4 validation
failure, 5 requested export failed, 6 lock or state conflict, 130 interrupted or interview saved.

## Limits and honesty

- Cost output is a scenario from your inputs, not a quotation; missing prices stay unknown.
- Terraform and manifests are generated, not validated or applied. Run `terraform validate/plan`
  in your own pipeline with approved credentials.
- Catalogs (capabilities, OWASP LLM Top 10 2025) are packaged snapshots; verify before relying on
  them for compliance.
- A strict budget ledger, object-level authorization, approval binding, and provider eligibility
  filtering are application responsibilities listed in `integration_contracts.md`.

See [limitations](docs/limitations.md) and [security](SECURITY.md).

## Development

```sh
ruff format --check .
ruff check .
mypy src
pytest -q
python -m build
```

Tests never read your `.env` and never call a real model. The repository is MIT-licensed under
the existing owner's decision in [LICENSE](LICENSE). New commits must use the configured user
identity and contain no AI attribution; see [AGENTS.md](AGENTS.md).
