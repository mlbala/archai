An enterprise AI architecture binds five decisions to one request path: caller scope, tool mutation, data residency, provider backoff, and a hard monthly budget.

That is the session I built ArchAI for.

ArchAI is an open-source terminal architect for enterprise AI applications. You describe the product, or hand it a requirements file. It interviews you for what is still open, then specialist roles design only the parts that belong to this system.

If a part does not fit, you say so. "Cache excluded." "I don't need RBAC." "Deployment excluded." That omission is recorded. The core stays. Every accepted design is an immutable revision you can lock and compare later.

You review three documents first: a high-level design, a low-level design, and a master delivery plan. Diagrams, policies, and infrastructure sketches come with them. ArchAI prepares the design. You decide what gets built. It never deploys.

You pick the model. OpenAI, Anthropic, Gemini, and DeepSeek all run it, and you can put a second provider on the verifier so one model drafts and another checks.

`arch auto` is the full process. Five specialists design in order. Requirements writes the product requirements. Cloud designs services, data, workflows, retrieval, infrastructure, and resilience. API designs APIs, routing, budgets, and cache, and it sees the cloud design. Security designs identity, guardrails, threats, observability, and evaluation, and it sees cloud and API. The verifier checks the result. A blocking finding goes back only to the owning role, at most twice.

Each role returns a structured proposal. A supervisor merges it into one design. The roles do not write the files. Cost, diagrams, and documents are filled in by code. If a role call fails, that part keeps the baseline already laid down.

You can design any one component alone: `arch api` for the API, `arch infra` for infrastructure, and the same for routing, data, security, retrieval, and the rest. Only the role that owns that component runs, and it may return only that piece. The accepted design is read-only context. Locked parts stay locked. The verifier checks only that slice. Dependents are marked stale and left for a later command. If the requirements say the part does not apply, no model is called. The revision stays partial until you run the rest.

Start here:

archai setup
archai auto

`archai model use` switches provider, or assigns a model to a single role.

This is the initial phase. Version 1.0.0 is usable on a real idea, and a lot is still to improve. Your locks and revisions survive the next run, and a human remains the architect of record.

I built ArchAI in Cursor with Grok 4.7 high fast. Thank you, Grok.

MIT licensed: https://github.com/mlbala/archai

If you design these systems, run it on one real idea and tell me which question the interview still fails to ask.
