# ArchAI

ArchAI is a terminal architect for enterprise AI applications. You describe the application, or
point it at a requirements file. It interviews you for what is still missing, then a team of
specialist architects designs the system: requirements, microservices, APIs, model routing,
budgets, data, workflows, retrieval, identity, guardrails, security, observability, evaluation,
capacity, and cost.

Parts that do not fit the application are left out. A batch pandas job with no users does not
get a response cache or user RBAC. Saying `cache excluded`, `I don't need RBAC`, or
`deployment excluded` removes that part from the design. The core stays: services, APIs,
routing, budget, data, and security.

Every accepted design is an immutable revision. `arch auto` exports Markdown, PDF, diagrams,
Terraform, Kubernetes manifests, gateway config, and policy files. It also writes
`master_design/Master_Design.pdf`: the feature catalog, build order, and sprint slices for that
same revision.

The command is `arch`. `archai` is the same program. On macOS, `/usr/bin/arch` already exists,
so use `archai` if your shell still finds the system command. ArchAI never deploys or applies
infrastructure.

## Install

Python 3.12 or newer:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
hash -r
archai --help
```

`hash -r` makes the shell forget a cached `arch`. Check that you are on the project command:

```sh
archai --version
```

## Set up the model before you design

Do this once, before `arch auto`. Without an API key, ArchAI still runs, but only the
deterministic baseline, and every document says so. A real provider is what produces a
project-specific design.

Settings are read from the shell environment, then `~/.config/archai/.env`, then `./.env` in
the directory where you run the command. A variable already set in the shell wins over both
files.

### Guided setup

```sh
archai setup
```

The wizard asks for a provider, a model ID, and an API key. The key is hidden while you type
and is saved to `./.env` with mode `600`. Add `--global` to write `~/.config/archai/.env`
instead. It can also ask for a second provider to use as the Design Verifier.

`archai setup` needs a terminal. In a script, use `archai model use` or export the variables
below.

### API key variables

| Provider | Set this | Also accepted |
| --- | --- | --- |
| OpenAI | `ARCHAI_OPENAI_API_KEY` | `OPENAI_API_KEY` |
| Anthropic | `ARCHAI_ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY` |
| Gemini | `ARCHAI_GEMINI_API_KEY` | `GEMINI_API_KEY` |
| DeepSeek | `ARCHAI_DEEPSEEK_API_KEY` | `DEEPSEEK_API_KEY` |

Example, current shell only:

```sh
export ARCHAI_ARCHITECT_PROVIDER=gemini
export ARCHAI_ARCHITECT_MODEL=gemini-3.1-pro-preview
export ARCHAI_GEMINI_API_KEY=your-key
```

Example, saved for this project (do not commit `.env`):

```sh
umask 077
cat >> .env << 'EOF'
ARCHAI_ARCHITECT_PROVIDER=anthropic
ARCHAI_ARCHITECT_MODEL=claude-opus-5-5
ARCHAI_ANTHROPIC_API_KEY=your-key
EOF
```

Check what is configured. This never prints the key:

```sh
archai doctor
archai model show
```

### Switch provider and model

Default provider is OpenAI `gpt-6-sol`. These commands write `./.env`. `--key` prompts for the
secret. `--global` writes the user config file instead.

```sh
# OpenAI GPT
archai model use openai gpt-6-sol --key
archai model use openai gpt-6-luna          # cheaper OpenAI model

# Google Gemini
archai model use gemini gemini-3.1-pro-preview --key

# Anthropic Claude
archai model use anthropic claude-opus-5-5 --key
archai model use anthropic claude-sonnet-5-5

# DeepSeek
archai model use deepseek deepseek-v4-pro --key
```

One run can override the saved choice without editing `.env`:

```sh
arch auto -p notes --architect-provider gemini --architect-model gemini-3.1-pro-preview
arch auto -p notes --architect-provider anthropic --architect-model claude-sonnet-5-5
```

If `ARCHAI_ARCHITECT_PROVIDER` is already exported in the shell, it overrides `.env`. Unset it
when the switch does not appear to stick:

```sh
unset ARCHAI_ARCHITECT_PROVIDER ARCHAI_ARCHITECT_MODEL
archai model show
```

| Provider | Default model | Other models | How the call works |
| --- | --- | --- | --- |
| `openai` | `gpt-6-sol` | `gpt-6-luna`, `gpt-6-astra`, `gpt-5.5` | Responses API, strict structured output |
| `anthropic` | `claude-opus-5-5` | `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-fable-5-1` | Messages API, JSON schema, `effort=high` |
| `gemini` | `gemini-3.1-pro-preview` | `archai model list gemini --remote` | JSON schema; Pro preview needs a paid tier |
| `deepseek` | `deepseek-v4-pro` | `deepseek-flash` | OpenAI-compatible JSON mode at `ARCHAI_DEEPSEEK_BASE_URL` (default `https://api.deepseek.com`) |

List models your key can actually call:

```sh
archai model list
archai model list gemini --remote
archai model list anthropic --remote
```

Use any model ID that supports structured output. Your provider bills the calls.

### Different model per role

Roles are `requirements`, `cloud`, `api`, `security`, and `verifier`. A second provider as the
verifier is the usual split: one model drafts, another checks.

```sh
archai model use anthropic claude-sonnet-5-5 --role verifier --key
archai model use gemini gemini-3.1-pro-preview --role cloud
archai model clear --role verifier
```

Or for a single run:

```sh
arch auto -p support \
  --role-model verifier=anthropic:claude-sonnet-5-5 \
  --role-model cloud=gemini:gemini-3.1-pro-preview
```

`ARCHAI_ROLE_MODELS` stores the same map, comma-separated:
`verifier=anthropic:claude-sonnet-5-5,cloud=gemini:gemini-3.1-pro-preview`.

If a provider hits quota, a rate limit, or a bad key, and another provider has a key, that role
moves to the other provider for the rest of the run.

Other useful variables:

| Variable | Meaning |
| --- | --- |
| `ARCHAI_OUTPUT_DIR` | Where projects are stored. Default `./output` |
| `ARCHAI_ANTHROPIC_EFFORT` | Claude effort. Default `high`. Empty string omits it |
| `ARCHAI_ANTHROPIC_FALLBACKS` | Claude refusal fallbacks. Set `false` to disable |
| `ARCHAI_DEEPSEEK_BASE_URL` | DeepSeek API base. Default `https://api.deepseek.com` |
| `ARCHAI_MAX_GENERATION_CALLS` | Call budget per run. Default 16 |
| `ARCHAI_MAX_GENERATION_TOKENS` | Token budget per run. Default 400000 |
| `ARCHAI_REQUEST_TIMEOUT_SECONDS` | Provider timeout. Default 300 |

## Run a design

Interactive, best path. You will be asked for a project name and a description if you do not
pass them:

```sh
archai auto
```

Same design from a file, still interviewing for anything the file does not answer:

```sh
archai auto -p notes -f requirements.yaml
```

No prompts, for a script. The file must already contain the critical answers, or the command
exits 2 and prints the missing question IDs:

```sh
archai auto -p eu-support -f examples/azure-enterprise-rag/requirements.yaml \
  --profile azure-aca --topology provider-failover --non-interactive --formats core
```

Baseline only, no model calls and no bill:

```sh
archai auto -p sketch -f requirements.yaml --offline --non-interactive --formats core
```

See the plan without writing files or calling a model:

```sh
archai auto -p notes -f requirements.yaml --dry-run
```

On a terminal, `arch auto`:

1. Asks for the project name and a description, unless you passed `-p`, `-i`, `-f`, or `--answers`.
2. Sends that description to the Enterprise Requirements Architect, which suggests answers and
   writes a few clarifying questions.
3. Interviews you for anything still missing: users, roles, workload type, tool side effects,
   traffic and tokens, providers, hosting, region, residency, identity, tenancy, classification,
   compliance, availability, latency, RTO/RPO, and the hard monthly budget. It also asks which
   optional parts are not required.
4. Runs the design team and shows a live status board.
5. Saves revision `0001` (then `0002`, and so on) and prints the export path.

Interview controls: Enter or `none` accepts the best fit from the requirements collected so far.
On the optional-parts question, `none` keeps every part. `skip` leaves an optional question
blank. `back` returns to the previous question. `?` shows help. `save` stops and keeps the
answers so you can resume. A review table is shown before the design starts; type a row number
to change an answer.

Optional parts you can drop: cache, RBAC, cloud deployment, retrieval, observability,
evaluation, workflows, guardrails, and resilience. Phrases that work on the related question:
`cache excluded`, `I don't need RBAC`, `deployment excluded`, `not required`. An empty answer
on existing platform services fills the baseline for the chosen hosting profile (for example
Azure API Management and Azure Container Apps). `deployment excluded` removes the cloud
deployment, including Terraform.

Resume a saved or blocked interview:

```sh
archai resume notes --run RUN_ID
```

The run ID is printed when a non-interactive design stops for missing answers, and by
`archai status notes`.

## Get a better design

- Set a provider and key with `archai setup` or `archai model use` before `arch auto`.
  `--offline` is a useful sketch. It is not the design to review with a team.
- Describe the application in concrete terms: who uses it, what it must do, what it must not
  do, where data may live, and the monthly limit. One vague sentence produces a generic design.
- Press Enter when the suggested answer fits. Type the exclusion phrase when a part does not
  belong. Do not skip the monthly budget, tenant isolation, or data residency; those stay
  required when the description does not decide them.
- Read the review table and correct a wrong row before the design starts.
- Put a second provider on the `verifier` role when you want a cross-check.
- After the export, open `Complete_AI_System_Design.pdf` and
  `master_design/Master_Design.pdf`. Lock a component you want to keep, then run `arch auto`
  again; locked parts are not overwritten.
- Re-export with `archai export PROJECT` after you only need new files. That does not call a
  model.

## Where the output is

Projects are stored under `./output` unless `ARCHAI_OUTPUT_DIR` or `--output-dir` says
otherwise. The summary at the end of `arch auto` prints the bundle path. `archai status PROJECT`
prints the latest export.

```text
output/<project>/
  revisions/0001/                 immutable design (state JSON, documents, manifest)
  runs/<run-id>/                  interview progress, so a paused run can resume
  exports/0001/<bundle>/
    Complete_AI_System_Design.md
    Complete_AI_System_Design.pdf
    master_design/Master_Design.pdf
    requirements/AI_Enterprise_PRD.md
    documents/<Component>_Design.md
    diagrams/<view>.mmd .svg .png
    diagrams/architecture_diagram.drawio
    infrastructure/primary/*.tf
    workloads/kubernetes/*.yaml
    litellm.yaml
    apim_policies.xml
    policies/*.yaml
    integration_contracts.md
    enterprise_design.json
    architecture_graph.json
    validation_report.json
    manifest.json
```

Open `Complete_AI_System_Design.pdf` first. It is the architecture, each component, the
infrastructure bill of materials, and the scale-up table. Replica minimums and maximums in that
table are the same numbers written into the generated autoscalers. The ceiling is the peak
worker estimate times 3, clamped to 3–30. It is a load-test starting point. Provider quotas
still bound model throughput.

Open `master_design/Master_Design.pdf` for the feature list, the service build order, and four
sprint slices (foundation, core path, controls, operate). Sprints are build slices, not dates.

A component that was excluded is still listed. Its document says not applicable and why. Its
policy file and, for cloud deployment, its Terraform root are omitted.

`--formats all` (the default) writes Markdown, JSON, YAML, Mermaid, draw.io, SVG, Terraform,
XML, PNG, and PDF. `--formats core` skips PNG and PDF. A full PDF export is the one that
includes `master_design/Master_Design.pdf`.

Terraform is generated for `azure-aca`, `azure-aks`, and `aws-eks`. The `agnostic` profile and
an excluded deployment produce no Terraform. Kubernetes manifests are generated for AKS and EKS.
Nothing here is applied.

## Commands

`arch` and `archai` accept the same commands. Design commands share `-p` / `--project`,
`-f` / `--file`, `-i` / `--idea`, `--answers`, `--offline`, `--non-interactive`, `--dry-run`,
`--formats`, `--output-dir`, `--architect-provider`, `--architect-model`, and repeatable
`--role-model`.

### Start here

| Command | Use it when |
| --- | --- |
| `archai setup` | You need to choose a provider, model, and API key. |
| `archai doctor` | You want a secret-free check of Python, keys, and renderers. Add `--check-provider` to probe the network. |
| `archai model show` | You want to see which model each role uses and whether its key is set. |
| `archai model list [PROVIDER] [--remote]` | You want suggested models, or the models your key can call. |
| `archai model use PROVIDER [MODEL] [--key] [--role ROLE] [--global]` | You want to switch provider or model, or set one role. |
| `archai model clear [--role ROLE]` | You want to drop role overrides and use the default architect again. |
| `archai auto` | You want the complete design. This is the command to run. |
| `archai --version` | You want the installed version. |

### Design one part

Each command writes only that component, then the verifier for its role. `arch design` is
`arch system` and is not a complete design. `--mode auto` skips the interview for that command.
`--mode guided` is the default on a terminal.

| Command | Use it when |
| --- | --- |
| `archai requirements -p PROJECT` | You want the product requirements and PRD only. |
| `archai system -p PROJECT` | You want the microservice catalog. `archai design` is the same command. |
| `archai api -p PROJECT` | You want the API contracts and gateway responsibilities. |
| `archai routing -p PROJECT` | You want model aliases, fallback, and the AI gateway. |
| `archai budget -p PROJECT` | You want the hard monthly budget and reservation policy. |
| `archai cache -p PROJECT` | You want the response-cache policy. Omitted when cache is excluded. |
| `archai workflow -p PROJECT` | You want request and tool workflows, including human approval. |
| `archai rag -p PROJECT` | You want the retrieval pipeline. Omitted when the app has no knowledge sources. |
| `archai data -p PROJECT` | You want data stores, ownership, and residency. |
| `archai infra -p PROJECT --profile azure-aca` | You want the hosting profile and Terraform. Profiles: `azure-aca`, `azure-aks`, `aws-eks`, `agnostic`. Omitted when deployment is excluded. |
| `archai resilience -p PROJECT` | You want queue behavior, retries, and recovery targets. |
| `archai auth -p PROJECT` | You want OAuth flows, RBAC, and workload identity. Omitted when RBAC is excluded. |
| `archai guard -p PROJECT` | You want guardrail controls. |
| `archai security -p PROJECT` | You want the STRIDE and OWASP LLM threat model. |
| `archai observe -p PROJECT` | You want traces, metrics, and logs. |
| `archai eval -p PROJECT` | You want the evaluation plan for primary and fallback routes. |
| `archai cost -p PROJECT` | You want capacity and a cost scenario from the numbers you supplied. No model call. |
| `archai diagram -p PROJECT --view deployment` | You want to redraw diagrams from the saved revision. No model call. |
| `archai doc -p PROJECT` | You want to re-render documents from the saved revision. No model call. |

Diagram views: `architecture`, `deployment`, `request`, `ingestion`, `guardrails`, `workflow`,
`fallback`, `budget`, `recovery`, `oauth`, `data`, `async`, `scale`. `scaleup` is `scale`.
`system` is `architecture`.

```sh
archai infra -p support --profile azure-aks --region westeurope
archai auth -p support
archai guard -p support --override examples/azure-enterprise-rag/guard-overrides.yaml
archai diagram -p support --view scale
archai doc -p support --scope guard,infra --formats md,pdf
```

A component command on a new project still needs the critical requirements. Pass `-f` or answer
the interview. `arch auto` afterward fills whatever is still missing and keeps locked
components.

### After a design exists

| Command | Use it when |
| --- | --- |
| `archai list` | You want every project under the output directory. |
| `archai status [PROJECT]` | You want component status, completeness, the latest export, and a paused run. |
| `archai inspect PROJECT [--component NAME] [--revision N]` | You want the saved design JSON, or one component of it. |
| `archai export PROJECT [--revision N] [--formats all]` | You want a fresh bundle from a saved revision. No model call. |
| `archai validate PROJECT [--strict] [--revision N]` | You want the deterministic checks again. `--strict` requires every component current. |
| `archai diff PROJECT 1 2` | You want a unified diff of two revisions. |
| `archai update PROJECT -i "Only EU processing"` | You want a new complete revision from a changed requirement. |
| `archai resume PROJECT --run RUN_ID` | An interview was saved or a non-interactive run stopped for missing answers. |
| `archai lock -p PROJECT --component guard [--field PATH]` | A later `arch auto` must keep this component, or one field of it. |
| `archai unlock -p PROJECT --component guard` | That component may be redesigned. |
| `archai edit -p PROJECT --component NAME --file OVERRIDES.yaml [--yes]` | You want to apply a typed override and save a new revision. |
| `archai simulate PROJECT --scenario examples/provider-failover/timeout-and-429.yaml` | You want to run a local budget or failover scenario against the saved rules. |
| `archai catalog show` | You want the packaged capability and OWASP LLM Top 10 2025 catalogs. |
| `archai catalog validate` | You want those catalogs checked for structure. |

```sh
archai status support
archai export support --formats all
archai lock -p support --component infra
archai auto -p support
```

Exit codes: 0 success, 2 missing or invalid input, 3 provider or authentication failure,
4 validation failure, 5 an export file failed, 6 lock or state conflict, 130 interrupted or
interview saved.

## Limits

- Cost output is a scenario from your inputs, not a quotation. Missing prices stay unknown.
- Scale-up replica counts are starting points for a load test. ArchAI does not apply them.
- Terraform and manifests are generated, not validated or applied. Run `terraform validate` and
  `terraform plan` in your own pipeline.
- Deployment IDs are `USER_SUPPLIED` placeholders. Quotas and prices are account inputs.
- Catalogs are packaged snapshots. They are not a compliance claim.
- Budget reservation, object-level authorization, approval binding, and provider eligibility
  filtering are application work. They are listed in `integration_contracts.md`.

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
