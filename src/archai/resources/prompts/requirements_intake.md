# Task: requirements intake

Read the application description and any structured inputs. Then:

1. `summary`: two or three sentences describing the application in architecture terms.
2. `suggestions`: propose a value for each interview field you can reasonably determine. Use
   only the field names listed under `interview_fields`. For list fields use a comma-separated
   string; for choice fields use one of the listed choices exactly. Copy an exact quote from the
   description into `source_quote` when the value is stated there; use an empty string when the
   value is your recommendation rather than a stated fact, and explain it in `rationale`.
   Never suggest values for `monthly_budget`, `tenant_isolation`, or `tool_side_effects` unless
   they are explicitly stated in the description.
3. `clarifying_questions`: up to five questions, specific to this application, whose answers would
   materially change the architecture and are NOT already covered by the interview fields (for
   example which ticketing system executes refunds, or whether answers may quote restricted
   documents). Do not repeat interview fields.
4. `detected_risks`: notable risks or conflicts you see in the description.
