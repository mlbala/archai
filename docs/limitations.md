# Limitations

- Generated assets are reviewed design inputs. They are not deployed, planned, or validated
  against a real account, region, quota, or SKU.
- Diagram files are Mermaid (`.mmd`) only. PNG, SVG, and draw.io are not exported.
- Architect-model output varies between runs. It is validated and normalized, but a human
  architect must still review it. Deterministic re-export of a saved revision is reproducible.
- Managed endpoint availability, deployment IDs, quotas, rate cards, licenses, and regions are
  account inputs. Endpoint deployment IDs are emitted as `USER_SUPPLIED_*` placeholders.
- APIM XML and LiteLLM YAML are native outputs; Kong and APISIX remain design-only.
- Terraform roots cover `azure-aca`, `azure-aks`, and `aws-eks`. They are checked for internal
  consistency in tests but have not been run through `terraform validate` unless you do so.
  Container Apps queue-scaler authentication must be configured for your provider version.
- `agnostic` produces portable contracts and intentionally emits no universal Terraform.
- The budget ledger simulator demonstrates invariants locally; production requires a
  transactional, authenticated service and reconciliation integration.
- The OWASP catalog contains the OWASP Top 10 for LLM Applications 2025 IDs only; unknown IDs
  proposed by a model are removed. Mappings are not compliance claims.
- Component commands use the complete requirements model; a standalone component still needs
  the core critical answers (asked in the interview).
