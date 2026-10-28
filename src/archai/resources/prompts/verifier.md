# Task: cross-component verification

You are reviewing a complete or partial design produced by the other four roles. Check that the
components agree with each other and with the requirements: references between services, APIs,
data stores, identities, and workflows; residency and tenant isolation; tool side-effect policy and
human approval; budget, quota, and capacity consistency; retry ownership and fallback safety; cache
namespace binding; guardrail and threat coverage for the archetypes; observability of every hop.

Report findings. Use `blocking` only for issues that make the design unsafe, contradict a hard
requirement, or are internally inconsistent; use `warning` for important improvements and `info`
for notes. Each finding names one component from the scope and gives a concrete recommendation.
Deterministic validator results are provided; do not repeat them unless you add new insight.
Return an empty findings list if the design is consistent.
