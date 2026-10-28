# Limitations

- Generated assets are design scaffolds and are not deployed or account-validated.
- Managed endpoint availability, deployment IDs, quotas, rate cards, licenses, and regions require
  account-owner verification.
- APIM XML and LiteLLM YAML are supported native outputs; Kong and APISIX remain design-only.
- The budget ledger simulator demonstrates invariants locally; production requires a transactional,
  authenticated service and reconciliation integration.
- PNG and PDF need optional renderer dependencies. Terraform static validation needs the Terraform CLI
  and may require approved network access for provider initialization.
- `agnostic` produces portable contracts and intentionally does not emit fake universal Terraform.

