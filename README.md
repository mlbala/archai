# ArchAI

ArchAI is a Python 3.12+ terminal application that turns complete requirements into a coherent managed-
API enterprise AI design, or designs one component at a time. The primary command is `arch`; `archai`
is an equivalent alias for macOS and other environments where `arch` resolves to a system executable.

ArchAI is the local **designer**. The systems it describes may use APIM, LiteLLM, Container Apps/AKS/EKS,
Service Bus/SQS, PostgreSQL, vector search, object storage, managed model APIs, and enterprise identity.
The CLI generates reviewed assets but never provisions or deploys them.

## Install

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev,render]'
hash -r
archai --help
```

On macOS, `/usr/bin/arch` already exists. An activated virtual environment normally puts this package's
`arch` first on `PATH`; use `archai` if shell resolution still selects the system command. Both entrypoints
invoke `archai.cli:app`.

Run the setup wizard to choose OpenAI or Gemini, select a model and optionally save an API key
in the local, gitignored `.env` file (permissions are restricted to the current user):

```sh
archai setup
archai doctor
```

Alternatively set `ARCHAI_ARCHITECT_PROVIDER=openai`, `OPENAI_API_KEY`, and optionally
`ARCHAI_ARCHITECT_MODEL`; or use `gemini` and `GEMINI_API_KEY`. The provider-specific defaults are
`gpt-6-luna` and `gemini-3.1-pro-preview`; supply a model available to your account that supports
structured output. Gemini 3.1 Pro is a preview model and requires a paid Gemini API tier. Both defaults
can incur API charges; check your provider's current prices and account access. Per-command `--architect-provider` and
`--architect-model` override these settings.

With a configured key, prose requirements (`.md`, `.txt`, `--idea`, or `--stdin`) are sent to the
chosen provider for extraction of explicitly stated business outcomes, users, and archetypes. API calls
may incur charges. Critical permissions, data location, budgets, traffic, and other required fields must
still be supplied as structured answers; model output does not authorize them. The current architecture
design itself uses deterministic templates rather than model-generated designs. Fully structured YAML/JSON
input, dry runs, validation, simulation, diffs, and exports do not make model calls. Never commit credentials.

## Complete design

Running `archai auto` alone prints an example and exits with code 2 because it needs a project name.
Given a project and complete structured requirements, it creates a revision and export bundle. Missing
critical inputs produce question IDs and a resumable run; it does not prompt or invent the answers.

```sh
arch auto -p eu-support \
  -f examples/azure-enterprise-rag/requirements.yaml \
  --profile azure-aca --topology provider-failover \
  --non-interactive --formats core
```

The command writes immutable design state under `output/eu-support/revisions/` and a separate export
bundle under `output/eu-support/exports/`. `core` needs no external renderer. `all` additionally requests
PNG and PDF and returns exit code 5 if a requested optional renderer is missing while retaining usable
outputs.

## Component control

Every component command accepts `-p`, requirements inputs, `--mode guided|auto`, scoped overrides,
`--dry-run`, `--output-dir`, and formats. It writes only that component and creates its standalone design
document.

```sh
arch system -p support -f examples/azure-enterprise-rag/requirements.yaml
arch infra -p support --profile azure-aca
arch guard -p support --override examples/azure-enterprise-rag/guard-overrides.yaml
arch lock -p support --component guard
arch auto -p support --formats core
```

Components are `requirements`, `system`, `api`, `routing`, `budget`, `cache`, `workflow`, `rag`, `data`,
`infra`, `resilience`, `auth`, `guard`, `security`, `observe`, `eval`, `cost`, `diagram`, and `doc`.
`arch design` is an alias of `arch system`, not the complete workflow.

Project operations include `update`, `inspect`, `list`, `edit`, `lock`, `unlock`, `validate`, `export`,
`diff`, `simulate`, `doctor`, and `catalog`. Use `arch COMMAND --help` for exact options. Dry-run makes no
writes, model calls, or renderer executions.

## Output support and assumptions

Core outputs include canonical JSON, Markdown, YAML policies, Mermaid, Draw.io, SVG, APIM XML when
selected, LiteLLM YAML when routes exist, and profile-specific Terraform scaffolds. PDF/PNG are optional.
Kong/APISIX remain explicitly design-only. A strict budget ledger, object authorization, HITL binding,
and provider eligibility enforcement are custom-runtime contracts, not invented gateway fields.

Cost output uses transparent workload arithmetic and user/account rate cards. Unknown prices remain
unknown and produce a known subtotal plus warnings; no catalog sample is presented as a live quote.
Generated Terraform requires an actual user-owned image and approved account/network/SKU inputs.

Catalogs are versioned packaged snapshots with provenance/status notices. They are not live entitlement,
price, quota, or regional availability feeds. See [limitations](docs/limitations.md) and
[security](SECURITY.md).

## Development validation

```sh
ruff format --check .
ruff check .
mypy src
pytest -q
python -m build
```

The repository is MIT-licensed under the existing owner's decision in [LICENSE](LICENSE). New commits
must use the configured user identity and contain no AI attribution; see [AGENTS.md](AGENTS.md).
