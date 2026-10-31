# Task: architecture plan

You are the chief architect. The PRD says what this application must do. Before the
specialists design components, decide the shape of the system: the architecture style, the
services and their ids, how they connect, and the few choices every specialist must follow.
The cloud, API, and security roles will design from your plan, so make it specific to this
application and short enough to follow.

`archai_defaults` is ArchAI's starting template for this application. Keep what fits. Where
this application needs something different, plan it and list the change in
`default_changes` with the reason. Do not plan anything `fixed_facts` or the requirements
rule out.

Return:

- `style`: the architecture style in one line, naming the journey that owns the latency
  target, for example "streaming Q&A over permission-trimmed retrieval, with an async intake
  pipeline".
- `summary`: two or three sentences a reviewer would accept as the design intent.
- `services`: 6-12 services with stable `svc-` ids, a kind, the purpose that justifies it,
  and the ids it calls. Include the four platform controls.
- `interfaces`: the important calls between services, with their style
  (`sync-http`, `streaming`, `async-queue`, `event`, `batch`, `tool-call`) and purpose.
- `key_choices`: 4-10 decisions the specialists must follow, each tied to the component that
  owns it (system, data, workflow, rag, infra, resilience, api, routing, budget, cache, auth,
  guard, security, observe, eval) and the requirement that forces it.
- `default_changes`: where you depart from `archai_defaults`, with the reason. Empty when the
  defaults fit.
- `risks`: the open questions or assumptions that could change the plan.
