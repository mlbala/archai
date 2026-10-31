# Task: enterprise PRD

Turn the confirmed requirements and clarification answers into the product contract the rest
of the architecture team will implement. Do not reopen decisions the requirements already
fixed. Do not smuggle in a design. Services, model names, and cloud products belong to later
roles. This document says what must be true and how it will be accepted.

Write it for this application:

- `summary` states who uses the system, what job they finish, and which data or system of
  record they may touch.
- `problem_statement` is the current way of working that fails, for the users named in the
  requirements. Include the cost of that failure when the business outcome states one.
- `goals` are outcomes, not features. Each goal names a metric. Use the stated business
  outcome, availability, latency, and budget. If a baseline was not given, keep the target
  and put the missing baseline in `open_questions`.
- `non_goals` close doors. Always include managed-API-only operation (no training or
  self-hosted inference) when that matches the product rules, and explicitly exclude any
  tool behavior, data class, channel, or region the requirements do not allow. Add the
  product non-goals that would otherwise tempt a larger platform.
- `personas` are the stated users and roles. `needs` is the job they are trying to finish
  and the constraint they care about (speed, not seeing another tenant's data, an approval
  before money moves).
- `journeys` are the real tasks, four to ten steps each, ending in a visible outcome. Include
  the unhappy path that matters for this application: no grounding, a policy refusal, an
  approval wait, or a provider failure. Steps are user and system actions, not component names.
- `functional_requirements` use ids `FR-1`, `FR-2`, and so on. Each statement is testable,
  names the actor, and has a MoSCoW priority. `must` is only what the stated outcome cannot
  ship without. Cover the archetypes that were selected: grounded answers, tool use, voice,
  extraction, text-to-SQL, or whatever this application actually is.
- `non_functional_requirements` use ids `NFR-1` and so on. `category` is one of security,
  privacy, reliability, performance, cost, compliance, or operability. `target` is copied
  from the requirements (residency, tenant isolation, availability, latency, RTO, RPO,
  monthly budget and currency, classification, compliance). The monthly budget is the
  model-call hard limit only. Do not describe it as the cap on total operating spend.
  Platform and data cost stay outside that limit and need their own forecast. Do not invent
  a tighter number.
- `acceptance_metrics` are the release checks for the goals: what is measured, on which
  journey, and what failure means. Include safety and tenancy checks when the data is not public.
- `open_questions` are only unresolved items that would change services, data, approval, or
  scope. If the requirements and clarifications already settle it, it is not open.

A weak requirement says "the system should be secure and scalable." A requirement you can
build from says who is allowed to see which records, what happens when the model provider
is down, and which number the design must meet.
