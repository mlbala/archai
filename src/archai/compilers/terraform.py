"""Reviewed Terraform roots and workload manifests compiled from canonical state.

The output is a starting point for a pipeline review: it never contains secret values, requires
user-owned images, and is never applied by ArchAI.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

import yaml

from archai.application.designer import has_rag
from archai.schemas.models import EnterpriseDesign, Service

WORKLOAD_KINDS = {
    "frontend",
    "application",
    "orchestration",
    "policy",
    "ai-gateway",
    "retrieval",
    "ingestion",
    "worker",
    "tool-executor",
    "integration",
}
QUEUE_KINDS = {"worker", "ingestion"}
PUBLIC_KINDS = {"application", "orchestration", "frontend"}


def hcl(value: str) -> str:
    """A safe HCL string literal (JSON escaping, interpolation disabled)."""
    return json.dumps(value).replace("${", "$${").replace("%{", "%%{")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", value.lower()).strip("-")[:40] or "svc"


def workloads(design: EnterpriseDesign) -> list[Service]:
    return [service for service in design.services if service.kind in WORKLOAD_KINDS]


def _max_replicas(design: EnterpriseDesign) -> int:
    workers = design.capacity.worker_count if design.capacity else 2
    return max(3, min(30, workers * 3))


def compile_infrastructure(design: EnterpriseDesign) -> dict[str, str]:
    """Relative path → file content for the selected deployment profile."""
    profile = design.requirements.profile
    if profile == "agnostic":
        return {}
    files: dict[str, str] = {}
    if profile.startswith("azure"):
        files.update(_azure(design, aks=profile == "azure-aks"))
    else:
        files.update(_aws(design))
    files["infrastructure/primary/README.md"] = _readme(design)
    if profile in {"azure-aks", "aws-eks"}:
        files.update(_kubernetes(design))
    return files


# ---------------------------------------------------------------- Azure


def _azure(design: EnterpriseDesign, *, aks: bool) -> dict[str, str]:
    req = design.requirements
    rag = has_rag(req) and any("search" in s.kind.lower() for s in design.data_stores)
    queue = design.queue_policy
    max_attempts = queue.max_attempts if queue else 5
    max_age = queue.max_age_seconds if queue else 3600
    retention = design.observability.log_retention_days if design.observability else 90
    retention = max(30, min(730, retention or 90))
    services = workloads(design)
    app_key = next((s.id for s in services if s.kind in PUBLIC_KINDS), None)
    peak_rpm = max(60, int(req.peak_rps * 60))
    zone_redundant = req.availability_target >= Decimal("99.95")
    uses_azure_openai = any("azure" in p.lower() for p in req.allowed_target_providers)

    versions = """terraform {
  required_version = ">= 1.7, < 2.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.20"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  # Configure a remote backend (for example azurerm) per environment before planning.
}

provider "azurerm" {
  features {}
  subscription_id     = var.subscription_id
  storage_use_azuread = true
}
"""

    images_doc = ", ".join(s.id for s in services) or "none"
    variables = f"""variable "subscription_id" {{
  description = "Target Azure subscription ID (account input)."
  type        = string
}}

variable "project" {{
  description = "Short project name used in resource names."
  type        = string
  default     = {hcl(_slug(design.project)[:16])}
}}

variable "environment" {{
  description = "Environment name (dev, test, prod). Use one state per environment."
  type        = string
  default     = "prod"
}}

variable "location" {{
  description = "Azure region; must stay within the approved data residency."
  type        = string
  default     = {hcl(req.region)}
  validation {{
    condition     = contains({json.dumps(sorted({req.region, *req.data_residency}))}, var.location)
    error_message = "Location must be one of the approved data-residency regions."
  }}
}}

variable "tags" {{
  description = "Additional resource tags."
  type        = map(string)
  default     = {{}}
}}

variable "service_images" {{
  description = "Immutable, user-owned image references keyed by service ID ({images_doc})."
  type        = map(string)
  validation {{
    condition = alltrue([
      for image in values(var.service_images) :
      length(trimspace(image)) > 0 && !startswith(image, "example") && !strcontains(image, "REPLACE")
    ])
    error_message = "Supply real, user-owned image references for every service."
  }}
}}

variable "public_network_access" {{
  description = "Allow public network access to data services (prefer false with private endpoints)."
  type        = bool
  default     = false
}}

variable "log_retention_days" {{
  description = "Log Analytics retention in days."
  type        = number
  default     = {retention}
}}

variable "postgres_sku_name" {{
  description = "PostgreSQL Flexible Server SKU."
  type        = string
  default     = "GP_Standard_D2ds_v5"
}}

variable "postgres_admin_object_id" {{
  description = "Object ID of the Entra group that administers PostgreSQL."
  type        = string
}}

variable "postgres_admin_principal_name" {{
  description = "Display name of the Entra administrator group."
  type        = string
}}

variable "servicebus_sku" {{
  description = "Service Bus tier (Premium is required for private endpoints)."
  type        = string
  default     = "Standard"
}}

variable "apim_publisher_name" {{
  description = "API Management publisher name."
  type        = string
}}

variable "apim_publisher_email" {{
  description = "API Management publisher email."
  type        = string
}}

variable "apim_sku_name" {{
  description = "API Management SKU, for example StandardV2_1."
  type        = string
  default     = "StandardV2_1"
}}

variable "api_audience" {{
  description = "OAuth audience (application ID URI) that tokens must carry."
  type        = string
  default     = {hcl(f"api://{design.project}")}
}}

variable "openid_config_url" {{
  description = "OpenID configuration URL of the identity provider (defaults to Entra ID)."
  type        = string
  default     = null
}}

variable "token_issuer" {{
  description = "Expected token issuer (defaults to Entra ID v2 for this tenant)."
  type        = string
  default     = null
}}
"""
    if uses_azure_openai:
        variables += """
variable "azure_openai_resource_id" {
  description = "Existing Azure OpenAI / AI Foundry resource ID (account input); null to skip RBAC."
  type        = string
  default     = null
}
"""
    if aks:
        variables += """
variable "kubernetes_version" {
  description = "AKS Kubernetes version (null selects the regional default)."
  type        = string
  default     = null
}

variable "node_vm_size" {
  description = "AKS node VM size."
  type        = string
  default     = "Standard_D4ds_v5"
}

variable "kubernetes_namespace" {
  description = "Namespace for application workloads."
  type        = string
  default     = "ai-app"
}

variable "backend_url" {
  description = "Internal URL of the application service behind APIM (ingress controller)."
  type        = string
}
"""
    if rag:
        variables += """
variable "search_sku" {
  description = "Azure AI Search SKU."
  type        = string
  default     = "standard"
}
"""

    main: list[str] = [
        f"""# Generated by ArchAI for project {design.project!r}. Review before planning.
# ArchAI never runs terraform apply and never stores secret values in these files.

data "azurerm_client_config" "current" {{}}

resource "random_string" "suffix" {{
  length  = 5
  special = false
  upper   = false
}}

locals {{
  name    = "${{var.project}}-${{var.environment}}"
  compact = substr(replace(lower("${{var.project}}${{var.environment}}${{random_string.suffix.result}}"), "/[^a-z0-9]/", ""), 0, 20)
  tags = merge(var.tags, {{
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
    designed_by = "archai"
  }})
  openid_config_url = coalesce(var.openid_config_url, "https://login.microsoftonline.com/${{data.azurerm_client_config.current.tenant_id}}/v2.0/.well-known/openid-configuration")
  token_issuer      = coalesce(var.token_issuer, "https://login.microsoftonline.com/${{data.azurerm_client_config.current.tenant_id}}/v2.0")
}}

resource "azurerm_resource_group" "main" {{
  name     = "rg-${{local.name}}"
  location = var.location
  tags     = local.tags
}}

resource "azurerm_log_analytics_workspace" "main" {{
  name                = "log-${{local.name}}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  tags                = local.tags
}}

resource "azurerm_application_insights" "main" {{
  name                = "appi-${{local.name}}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  tags                = local.tags
}}

resource "azurerm_user_assigned_identity" "app" {{
  name                = "id-${{local.name}}-app"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}}

resource "azurerm_key_vault" "main" {{
  name                          = "kv${{local.compact}}"
  location                      = azurerm_resource_group.main.location
  resource_group_name           = azurerm_resource_group.main.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  enable_rbac_authorization     = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 90
  public_network_access_enabled = var.public_network_access
  tags                          = local.tags
}}

resource "azurerm_storage_account" "documents" {{
  name                            = "st${{local.compact}}"
  resource_group_name             = azurerm_resource_group.main.name
  location                        = azurerm_resource_group.main.location
  account_tier                    = "Standard"
  account_replication_type        = "ZRS"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  public_network_access_enabled   = var.public_network_access
  blob_properties {{
    versioning_enabled = true
    delete_retention_policy {{
      days = 30
    }}
  }}
  tags = local.tags
}}

resource "azurerm_storage_container" "documents" {{
  name                  = "source-documents"
  storage_account_id    = azurerm_storage_account.documents.id
  container_access_type = "private"
}}

resource "azurerm_servicebus_namespace" "main" {{
  name                = "sb-${{local.name}}-${{random_string.suffix.result}}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = var.servicebus_sku
  local_auth_enabled  = false
  minimum_tls_version = "1.2"
  tags                = local.tags
}}

resource "azurerm_servicebus_queue" "jobs" {{
  name                                    = "ai-jobs"
  namespace_id                            = azurerm_servicebus_namespace.main.id
  max_delivery_count                      = {max_attempts}
  lock_duration                           = "PT5M"
  default_message_ttl                     = "PT{max_age}S"
  dead_lettering_on_message_expiration    = true
  requires_duplicate_detection            = true
  duplicate_detection_history_time_window = "PT10M"
}}

resource "azurerm_postgresql_flexible_server" "main" {{
  name                          = "psql-${{local.name}}-${{random_string.suffix.result}}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  version                       = "16"
  sku_name                      = var.postgres_sku_name
  storage_mb                    = 65536
  backup_retention_days         = 35
  geo_redundant_backup_enabled  = {str(req.topology == "application-dr").lower()}
  public_network_access_enabled = var.public_network_access
  authentication {{
    active_directory_auth_enabled = true
    password_auth_enabled         = false
    tenant_id                     = data.azurerm_client_config.current.tenant_id
  }}
"""
        + (
            """  high_availability {
    mode = "ZoneRedundant"
  }
"""
            if zone_redundant
            else ""
        )
        + "  tags = local.tags\n  lifecycle {\n    ignore_changes = ["
        + ("zone, high_availability[0].standby_availability_zone" if zone_redundant else "zone")
        + """]
  }
}

resource "azurerm_postgresql_flexible_server_active_directory_administrator" "main" {
  server_name         = azurerm_postgresql_flexible_server.main.name
  resource_group_name = azurerm_resource_group.main.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  object_id           = var.postgres_admin_object_id
  principal_name      = var.postgres_admin_principal_name
  principal_type      = "Group"
}

resource "azurerm_postgresql_flexible_server_database" "ledger" {
  name      = "budget_ledger"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_postgresql_flexible_server_database" "state" {
  name      = "app_state"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}
"""
    ]
    if rag:
        main.append(
            """
resource "azurerm_search_service" "retrieval" {
  name                          = "srch-${local.name}-${random_string.suffix.result}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  sku                           = var.search_sku
  local_authentication_enabled  = false
  public_network_access_enabled = var.public_network_access
  identity {
    type = "SystemAssigned"
  }
  tags = local.tags
}
"""
        )
    roles = [
        (
            "servicebus_sender",
            "azurerm_servicebus_namespace.main.id",
            "Azure Service Bus Data Sender",
        ),
        (
            "servicebus_receiver",
            "azurerm_servicebus_namespace.main.id",
            "Azure Service Bus Data Receiver",
        ),
        (
            "blob_contributor",
            "azurerm_storage_account.documents.id",
            "Storage Blob Data Contributor",
        ),
        ("keyvault_secrets", "azurerm_key_vault.main.id", "Key Vault Secrets User"),
    ]
    if rag:
        roles += [
            ("search_reader", "azurerm_search_service.retrieval.id", "Search Index Data Reader"),
            (
                "search_contributor",
                "azurerm_search_service.retrieval.id",
                "Search Index Data Contributor",
            ),
        ]
    for name, scope, role in roles:
        main.append(
            f"""
resource "azurerm_role_assignment" "{name}" {{
  scope                = {scope}
  role_definition_name = {hcl(role)}
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}}
"""
        )
    if uses_azure_openai:
        main.append(
            """
resource "azurerm_role_assignment" "openai_user" {
  count                = var.azure_openai_resource_id == null ? 0 : 1
  scope                = var.azure_openai_resource_id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}
"""
        )
    if not aks:
        main.append(_container_apps(design, services))
    else:
        main.append(_aks())
    main.append(_apim(design, app_key if not aks else None, peak_rpm))
    outputs = """output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "workload_identity_client_id" {
  value = azurerm_user_assigned_identity.app.client_id
}

output "servicebus_namespace" {
  value = azurerm_servicebus_namespace.main.name
}

output "key_vault_uri" {
  value = azurerm_key_vault.main.vault_uri
}

output "postgres_fqdn" {
  value = azurerm_postgresql_flexible_server.main.fqdn
}

output "storage_account_name" {
  value = azurerm_storage_account.documents.name
}

output "api_gateway_url" {
  value = azurerm_api_management.main.gateway_url
}
"""
    if not aks:
        outputs += """
output "container_app_fqdns" {
  value = { for key, app in azurerm_container_app.service : key => app.latest_revision_fqdn }
}
"""
    else:
        outputs += """
output "aks_oidc_issuer_url" {
  value = azurerm_kubernetes_cluster.main.oidc_issuer_url
}
"""
    if rag:
        outputs += """
output "search_service_name" {
  value = azurerm_search_service.retrieval.name
}
"""
    return {
        "infrastructure/primary/versions.tf": versions,
        "infrastructure/primary/variables.tf": variables,
        "infrastructure/primary/main.tf": "".join(main),
        "infrastructure/primary/outputs.tf": outputs,
        "infrastructure/primary/policies/apim_api_policy.xml": apim_policy_xml(design),
        "infrastructure/primary/terraform.tfvars.example": _tfvars_azure(design, aks),
    }


def _container_apps(design: EnterpriseDesign, services: list[Service]) -> str:
    entries = []
    for service in services:
        queue = service.kind in QUEUE_KINDS
        entries.append(
            f"""    {hcl(service.id)} = {{
      ingress      = {str(not queue).lower()}
      queue_scaled = {str(queue).lower()}
      min_replicas = {0 if queue else 1}
      max_replicas = {_max_replicas(design)}
    }}"""
        )
    body = "\n".join(entries)
    return f"""
locals {{
  container_apps = {{
{body}
  }}
}}

resource "azurerm_container_app_environment" "main" {{
  name                       = "cae-${{local.name}}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.tags
}}

resource "azurerm_container_app" "service" {{
  for_each                     = local.container_apps
  name                         = substr("ca-${{replace(each.key, "svc-", "")}}-${{var.environment}}", 0, 32)
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  tags                         = local.tags

  identity {{
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }}

  template {{
    min_replicas = each.value.min_replicas
    max_replicas = each.value.max_replicas

    container {{
      name   = "app"
      image  = var.service_images[each.key]
      cpu    = 0.5
      memory = "1Gi"

      env {{
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.app.client_id
      }}
      env {{
        name  = "SERVICEBUS_FQDN"
        value = "${{azurerm_servicebus_namespace.main.name}}.servicebus.windows.net"
      }}
      env {{
        name  = "KEY_VAULT_URI"
        value = azurerm_key_vault.main.vault_uri
      }}
      env {{
        name  = "OTEL_SERVICE_NAME"
        value = each.key
      }}

      liveness_probe {{
        transport = "HTTP"
        port      = 8080
        path      = "/healthz"
      }}
      readiness_probe {{
        transport = "HTTP"
        port      = 8080
        path      = "/readyz"
      }}
    }}

    dynamic "http_scale_rule" {{
      for_each = each.value.queue_scaled ? [] : [1]
      content {{
        name                = "http-concurrency"
        concurrent_requests = "50"
      }}
    }}

    # Queue-driven scaling. Configure scaler authentication (managed identity) per the
    # Container Apps documentation for your provider version before enabling.
    dynamic "custom_scale_rule" {{
      for_each = each.value.queue_scaled ? [1] : []
      content {{
        name             = "servicebus-queue"
        custom_rule_type = "azure-servicebus"
        metadata = {{
          queueName    = azurerm_servicebus_queue.jobs.name
          namespace    = azurerm_servicebus_namespace.main.name
          messageCount = "20"
        }}
      }}
    }}
  }}

  dynamic "ingress" {{
    for_each = each.value.ingress ? [1] : []
    content {{
      external_enabled = false
      target_port      = 8080
      transport        = "auto"
      traffic_weight {{
        latest_revision = true
        percentage      = 100
      }}
    }}
  }}
}}
"""


def _aks() -> str:
    return """
resource "azurerm_kubernetes_cluster" "main" {
  name                      = "aks-${local.name}"
  location                  = azurerm_resource_group.main.location
  resource_group_name       = azurerm_resource_group.main.name
  dns_prefix                = local.name
  kubernetes_version        = var.kubernetes_version
  sku_tier                  = "Standard"
  oidc_issuer_enabled       = true
  workload_identity_enabled = true
  local_account_disabled    = true
  azure_policy_enabled      = true

  default_node_pool {
    name                 = "system"
    vm_size              = var.node_vm_size
    auto_scaling_enabled = true
    min_count            = 2
    max_count            = 6
    zones                = ["1", "2", "3"]
    upgrade_settings {
      max_surge = "10%"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  azure_active_directory_role_based_access_control {
    azure_rbac_enabled = true
    tenant_id          = data.azurerm_client_config.current.tenant_id
  }

  network_profile {
    network_plugin = "azure"
    network_policy = "azure"
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  }

  workload_autoscaler_profile {
    keda_enabled = true
  }

  tags = local.tags
}

resource "azurerm_federated_identity_credential" "app" {
  name                = "fic-${local.name}-app"
  resource_group_name = azurerm_resource_group.main.name
  parent_id           = azurerm_user_assigned_identity.app.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.main.oidc_issuer_url
  subject             = "system:serviceaccount:${var.kubernetes_namespace}:ai-app"
}
"""


def _apim(design: EnterpriseDesign, app_key: str | None, peak_rpm: int) -> str:
    operations = []
    for contract in design.api_contracts:
        params = re.findall(r"\{([^}]+)\}", contract.path)
        operations.append(
            f"""    {hcl(contract.id)} = {{
      display_name = {hcl((contract.summary or contract.id)[:100])}
      method       = {hcl(contract.method)}
      url_template = {hcl(contract.path)}
      params       = {json.dumps(params)}
    }}"""
        )
    service_url = (
        f'"https://${{azurerm_container_app.service[{hcl(app_key)}].ingress[0].fqdn}}"'
        if app_key
        else "var.backend_url"
    )
    return f"""
resource "azurerm_api_management" "main" {{
  name                = "apim-${{local.name}}-${{random_string.suffix.result}}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  publisher_name      = var.apim_publisher_name
  publisher_email     = var.apim_publisher_email
  sku_name            = var.apim_sku_name
  identity {{
    type = "SystemAssigned"
  }}
  tags = local.tags
}}

locals {{
  apim_named_values = {{
    "entra-openid-config-url" = local.openid_config_url
    "token-issuer"            = local.token_issuer
    "api-audience"            = var.api_audience
    "rpm-limit"               = "{peak_rpm}"
  }}
  api_operations = {{
{chr(10).join(operations)}
  }}
}}

resource "azurerm_api_management_named_value" "settings" {{
  for_each            = local.apim_named_values
  name                = each.key
  display_name        = each.key
  resource_group_name = azurerm_resource_group.main.name
  api_management_name = azurerm_api_management.main.name
  value               = each.value
}}

resource "azurerm_api_management_api" "app" {{
  name                  = "ai-application"
  resource_group_name   = azurerm_resource_group.main.name
  api_management_name   = azurerm_api_management.main.name
  revision              = "1"
  display_name          = {hcl(f"{design.project} AI application")}
  path                  = "ai"
  protocols             = ["https"]
  service_url           = {service_url}
  subscription_required = false
}}

resource "azurerm_api_management_api_operation" "operation" {{
  for_each            = local.api_operations
  operation_id        = each.key
  api_name            = azurerm_api_management_api.app.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = each.value.display_name
  method              = each.value.method
  url_template        = each.value.url_template

  dynamic "template_parameter" {{
    for_each = each.value.params
    content {{
      name     = template_parameter.value
      required = true
      type     = "string"
    }}
  }}

  response {{
    status_code = 200
  }}
}}

resource "azurerm_api_management_api_policy" "app" {{
  api_name            = azurerm_api_management_api.app.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  xml_content         = file("${{path.module}}/policies/apim_api_policy.xml")
  depends_on          = [azurerm_api_management_named_value.settings]
}}
"""


def apim_policy_xml(design: EnterpriseDesign) -> str:
    single_tenant = design.requirements.tenant_isolation == "single"
    tenant_claim = (
        """      <required-claims>
        <claim name="tid" match="any">
          <value>{{allowed-tenant-id}}</value>
        </claim>
      </required-claims>
"""
        if single_tenant
        else ""
    )
    return f"""<policies>
  <inbound>
    <base />
    <set-header name="x-correlation-id" exists-action="skip">
      <value>@(context.RequestId.ToString())</value>
    </set-header>
    <validate-jwt header-name="Authorization" failed-validation-httpcode="401" failed-validation-error-message="Unauthorized" require-expiration-time="true" require-scheme="Bearer" require-signed-tokens="true">
      <openid-config url="{{{{entra-openid-config-url}}}}" />
      <audiences>
        <audience>{{{{api-audience}}}}</audience>
      </audiences>
      <issuers>
        <issuer>{{{{token-issuer}}}}</issuer>
      </issuers>
{tenant_claim}    </validate-jwt>
    <rate-limit-by-key calls="{{{{rpm-limit}}}}" renewal-period="60" counter-key="@(context.Request.Headers.GetValueOrDefault(&quot;Authorization&quot;,&quot;&quot;).AsJwt()?.Subject ?? context.Request.IpAddress)" />
  </inbound>
  <backend>
    <forward-request timeout="120" buffer-response="false" />
  </backend>
  <outbound>
    <base />
    <set-header name="x-correlation-id" exists-action="override">
      <value>@(context.RequestId.ToString())</value>
    </set-header>
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>
"""


def _tfvars_azure(design: EnterpriseDesign, aks: bool) -> str:
    images = "\n".join(
        f'  {hcl(service.id)} = "REPLACE_WITH_IMMUTABLE_IMAGE_REFERENCE"'
        for service in workloads(design)
    )
    extra = '\nbackend_url = "https://REPLACE_WITH_INGRESS_HOST"\n' if aks else "\n"
    return f"""# Example values only. Copy to terraform.tfvars and replace every placeholder.
# Never commit secrets; this file contains none.
subscription_id               = "00000000-0000-0000-0000-000000000000"
environment                   = "dev"
postgres_admin_object_id      = "00000000-0000-0000-0000-000000000000"
postgres_admin_principal_name = "pg-admins"
apim_publisher_name           = "Platform team"
apim_publisher_email          = "platform@example.com"
service_images = {{
{images}
}}{extra}"""


# ---------------------------------------------------------------- AWS


def _aws(design: EnterpriseDesign) -> dict[str, str]:
    req = design.requirements
    rag = has_rag(req)
    queue = design.queue_policy
    max_attempts = queue.max_attempts if queue else 5
    max_age = max(60, min(1_209_600, queue.max_age_seconds if queue else 3600))
    retention = design.observability.log_retention_days if design.observability else 90
    retention = _cloudwatch_retention(retention or 90)
    multi_az = req.availability_target >= Decimal("99.95")
    versions = """terraform {
  required_version = ">= 1.7, < 2.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
  # Configure a remote backend (for example S3 with locking) per environment before planning.
}

provider "aws" {
  region = var.region
  default_tags {
    tags = local.tags
  }
}
"""
    variables = f"""variable "project" {{
  description = "Short project name used in resource names."
  type        = string
  default     = {hcl(_slug(design.project)[:16])}
}}

variable "environment" {{
  description = "Environment name. Use one state per environment."
  type        = string
  default     = "prod"
}}

variable "region" {{
  description = "AWS region; must stay within the approved data residency."
  type        = string
  default     = {hcl(req.region)}
  validation {{
    condition     = contains({json.dumps(sorted({req.region, *req.data_residency}))}, var.region)
    error_message = "Region must be one of the approved data-residency regions."
  }}
}}

variable "tags" {{
  description = "Additional resource tags."
  type        = map(string)
  default     = {{}}
}}

variable "vpc_id" {{
  description = "Existing VPC ID (account input)."
  type        = string
}}

variable "private_subnet_ids" {{
  description = "Private subnet IDs across at least two availability zones."
  type        = list(string)
}}

variable "kubernetes_version" {{
  description = "EKS Kubernetes version."
  type        = string
  default     = null
}}

variable "node_instance_types" {{
  description = "EKS managed node group instance types."
  type        = list(string)
  default     = ["m7g.large"]
}}

variable "eks_public_endpoint" {{
  description = "Expose the EKS API endpoint publicly (prefer false)."
  type        = bool
  default     = false
}}

variable "db_instance_class" {{
  description = "RDS PostgreSQL instance class."
  type        = string
  default     = "db.m7g.large"
}}

variable "kubernetes_namespace" {{
  description = "Namespace for application workloads."
  type        = string
  default     = "ai-app"
}}

variable "log_retention_days" {{
  description = "CloudWatch log retention in days."
  type        = number
  default     = {retention}
}}
"""
    main = [
        f"""# Generated by ArchAI for project {design.project!r}. Review before planning.
# ArchAI never runs terraform apply and never stores secret values in these files.

data "aws_caller_identity" "current" {{}}
data "aws_partition" "current" {{}}

locals {{
  name = "${{var.project}}-${{var.environment}}"
  tags = merge(var.tags, {{
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
    designed_by = "archai"
  }})
}}

resource "aws_kms_key" "main" {{
  description             = "${{local.name}} encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}}

resource "aws_sqs_queue" "jobs_dlq" {{
  name                      = "${{local.name}}-ai-jobs-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}}

resource "aws_sqs_queue" "jobs" {{
  name                       = "${{local.name}}-ai-jobs"
  visibility_timeout_seconds = 900
  message_retention_seconds  = {max_age}
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({{
    deadLetterTargetArn = aws_sqs_queue.jobs_dlq.arn
    maxReceiveCount     = {max_attempts}
  }})
}}

resource "aws_s3_bucket" "documents" {{
  bucket_prefix = "${{local.name}}-documents-"
}}

resource "aws_s3_bucket_public_access_block" "documents" {{
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}}

resource "aws_s3_bucket_versioning" "documents" {{
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {{
    status = "Enabled"
  }}
}}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {{
  bucket = aws_s3_bucket.documents.id
  rule {{
    apply_server_side_encryption_by_default {{
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }}
  }}
}}

resource "aws_cloudwatch_log_group" "app" {{
  name              = "/${{local.name}}/application"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}}

# ---------------------------------------------------------------- EKS

data "aws_iam_policy_document" "eks_assume" {{
  statement {{
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {{
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }}
  }}
}}

resource "aws_iam_role" "cluster" {{
  name               = "${{local.name}}-eks-cluster"
  assume_role_policy = data.aws_iam_policy_document.eks_assume.json
}}

resource "aws_iam_role_policy_attachment" "cluster" {{
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:${{data.aws_partition.current.partition}}:iam::aws:policy/AmazonEKSClusterPolicy"
}}

resource "aws_eks_cluster" "main" {{
  name     = local.name
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version

  vpc_config {{
    subnet_ids              = var.private_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = var.eks_public_endpoint
  }}

  access_config {{
    authentication_mode = "API"
  }}

  encryption_config {{
    resources = ["secrets"]
    provider {{
      key_arn = aws_kms_key.main.arn
    }}
  }}

  depends_on = [aws_iam_role_policy_attachment.cluster]
}}

data "aws_iam_policy_document" "node_assume" {{
  statement {{
    actions = ["sts:AssumeRole"]
    principals {{
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }}
  }}
}}

resource "aws_iam_role" "node" {{
  name               = "${{local.name}}-eks-node"
  assume_role_policy = data.aws_iam_policy_document.node_assume.json
}}

resource "aws_iam_role_policy_attachment" "node" {{
  for_each = toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEKS_CNI_Policy",
    "AmazonEC2ContainerRegistryReadOnly",
  ])
  role       = aws_iam_role.node.name
  policy_arn = "arn:${{data.aws_partition.current.partition}}:iam::aws:policy/${{each.value}}"
}}

resource "aws_eks_node_group" "main" {{
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${{local.name}}-default"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids
  instance_types  = var.node_instance_types
  ami_type        = "AL2023_ARM_64_STANDARD"

  scaling_config {{
    min_size     = 2
    desired_size = 3
    max_size     = 8
  }}

  update_config {{
    max_unavailable = 1
  }}

  depends_on = [aws_iam_role_policy_attachment.node]
}}

resource "aws_eks_addon" "pod_identity" {{
  cluster_name = aws_eks_cluster.main.name
  addon_name   = "eks-pod-identity-agent"
}}

data "aws_iam_policy_document" "pod_assume" {{
  statement {{
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {{
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }}
  }}
}}

resource "aws_iam_role" "app" {{
  name               = "${{local.name}}-app"
  assume_role_policy = data.aws_iam_policy_document.pod_assume.json
}}

data "aws_iam_policy_document" "app" {{
  statement {{
    sid       = "Queue"
    actions   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.jobs.arn]
  }}
  statement {{
    sid       = "Documents"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${{aws_s3_bucket.documents.arn}}/*"]
  }}
  statement {{
    sid       = "Kms"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.main.arn]
  }}
  statement {{
    sid       = "DatabaseSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_db_instance.main.master_user_secret[0].secret_arn]
  }}
  statement {{
    sid       = "ManagedModels"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["*"]
  }}
}}

resource "aws_iam_role_policy" "app" {{
  name   = "${{local.name}}-app"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app.json
}}

resource "aws_eks_pod_identity_association" "app" {{
  cluster_name    = aws_eks_cluster.main.name
  namespace       = var.kubernetes_namespace
  service_account = "ai-app"
  role_arn        = aws_iam_role.app.arn
}}

# ---------------------------------------------------------------- PostgreSQL ledger and state

resource "aws_db_subnet_group" "main" {{
  name       = "${{local.name}}-db"
  subnet_ids = var.private_subnet_ids
}}

resource "aws_security_group" "db" {{
  name        = "${{local.name}}-db"
  description = "PostgreSQL access from EKS workloads only"
  vpc_id      = var.vpc_id
}}

resource "aws_vpc_security_group_ingress_rule" "db_from_eks" {{
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}}

resource "aws_db_instance" "main" {{
  identifier                          = "${{local.name}}-ledger"
  engine                              = "postgres"
  engine_version                      = "16"
  instance_class                      = var.db_instance_class
  allocated_storage                   = 50
  max_allocated_storage               = 500
  storage_encrypted                   = true
  kms_key_id                          = aws_kms_key.main.arn
  username                            = "ledger_admin"
  manage_master_user_password         = true
  iam_database_authentication_enabled = true
  multi_az                            = {str(multi_az).lower()}
  backup_retention_period             = 35
  deletion_protection                 = true
  skip_final_snapshot                 = false
  final_snapshot_identifier           = "${{local.name}}-ledger-final"
  db_subnet_group_name                = aws_db_subnet_group.main.name
  vpc_security_group_ids              = [aws_security_group.db.id]
  performance_insights_enabled        = true
}}
"""
    ]
    if rag:
        main.append(
            """
# ---------------------------------------------------------------- OpenSearch Serverless (vector)

resource "aws_security_group" "search" {
  name        = "${local.name}-search"
  description = "OpenSearch Serverless VPC endpoint"
  vpc_id      = var.vpc_id
}

resource "aws_opensearchserverless_vpc_endpoint" "search" {
  name               = "${local.name}-search"
  vpc_id             = var.vpc_id
  subnet_ids         = var.private_subnet_ids
  security_group_ids = [aws_security_group.search.id]
}

resource "aws_opensearchserverless_security_policy" "encryption" {
  name = "${local.name}-enc"
  type = "encryption"
  policy = jsonencode({
    Rules       = [{ ResourceType = "collection", Resource = ["collection/${local.name}-rag"] }]
    AWSOwnedKey = true
  })
}

resource "aws_opensearchserverless_security_policy" "network" {
  name = "${local.name}-net"
  type = "network"
  policy = jsonencode([{
    Rules           = [{ ResourceType = "collection", Resource = ["collection/${local.name}-rag"] }]
    AllowFromPublic = false
    SourceVPCEs     = [aws_opensearchserverless_vpc_endpoint.search.id]
  }])
}

resource "aws_opensearchserverless_access_policy" "app" {
  name = "${local.name}-app"
  type = "data"
  policy = jsonencode([{
    Rules = [{
      ResourceType = "index"
      Resource     = ["index/${local.name}-rag/*"]
      Permission   = ["aoss:ReadDocument", "aoss:WriteDocument", "aoss:CreateIndex", "aoss:DescribeIndex", "aoss:UpdateIndex"]
    }]
    Principal = [aws_iam_role.app.arn]
  }])
}

resource "aws_opensearchserverless_collection" "rag" {
  name       = "${local.name}-rag"
  type       = "VECTORSEARCH"
  depends_on = [aws_opensearchserverless_security_policy.encryption, aws_opensearchserverless_security_policy.network]
}
"""
        )
    outputs = """output "eks_cluster_name" {
  value = aws_eks_cluster.main.name
}

output "jobs_queue_url" {
  value = aws_sqs_queue.jobs.url
}

output "documents_bucket" {
  value = aws_s3_bucket.documents.bucket
}

output "ledger_endpoint" {
  value = aws_db_instance.main.address
}

output "app_role_arn" {
  value = aws_iam_role.app.arn
}
"""
    if rag:
        outputs += """
output "vector_collection_endpoint" {
  value = aws_opensearchserverless_collection.rag.collection_endpoint
}
"""
    tfvars = """# Example values only. Copy to terraform.tfvars and replace every placeholder.
environment        = "dev"
vpc_id             = "vpc-REPLACE"
private_subnet_ids = ["subnet-REPLACE-a", "subnet-REPLACE-b", "subnet-REPLACE-c"]
"""
    return {
        "infrastructure/primary/versions.tf": versions,
        "infrastructure/primary/variables.tf": variables,
        "infrastructure/primary/main.tf": "".join(main),
        "infrastructure/primary/outputs.tf": outputs,
        "infrastructure/primary/terraform.tfvars.example": tfvars,
    }


def _cloudwatch_retention(days: int) -> int:
    allowed = [1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192]
    return next((value for value in allowed if value >= days), 2192)


# ---------------------------------------------------------------- Kubernetes


def _kubernetes(design: EnterpriseDesign) -> dict[str, str]:
    azure = design.requirements.profile.startswith("azure")
    files: dict[str, str] = {}
    namespace = "ai-app"
    service_account: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {"name": "ai-app", "namespace": namespace},
    }
    if azure:
        service_account["metadata"]["annotations"] = {
            "azure.workload.identity/client-id": "REPLACE_WITH_workload_identity_client_id_OUTPUT"
        }
    files["workloads/kubernetes/00-namespace.yaml"] = yaml.safe_dump_all(
        [
            {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace}},
            service_account,
        ],
        sort_keys=False,
    )
    if any(service.kind in QUEUE_KINDS for service in design.services):
        trigger_auth: dict[str, Any] = {
            "apiVersion": "keda.sh/v1alpha1",
            "kind": "TriggerAuthentication",
            "metadata": {"name": "queue-identity", "namespace": namespace},
            "spec": {"podIdentity": {"provider": "azure-workload" if azure else "aws"}},
        }
        files["workloads/kubernetes/01-keda-auth.yaml"] = yaml.safe_dump(
            trigger_auth, sort_keys=False
        )
    for number, service in enumerate(workloads(design), start=10):
        name = _slug(service.id)
        labels = {"app.kubernetes.io/name": name, "app.kubernetes.io/part-of": design.project}
        pod_labels = dict(labels)
        if azure:
            pod_labels["azure.workload.identity/use"] = "true"
        queue = service.kind in QUEUE_KINDS
        container: dict[str, Any] = {
            "name": "app",
            "image": f"${{IMAGE_{name.upper().replace('-', '_')}}}",
            "ports": [{"containerPort": 8080, "name": "http"}],
            "env": [{"name": "OTEL_SERVICE_NAME", "value": service.id}],
            "resources": {
                "requests": {"cpu": "250m", "memory": "512Mi"},
                "limits": {"memory": "1Gi"},
            },
            "startupProbe": {
                "httpGet": {"path": "/healthz", "port": "http"},
                "failureThreshold": 30,
                "periodSeconds": 2,
            },
            "livenessProbe": {"httpGet": {"path": "/healthz", "port": "http"}, "periodSeconds": 10},
            "readinessProbe": {"httpGet": {"path": "/readyz", "port": "http"}, "periodSeconds": 5},
            "securityContext": {
                "runAsNonRoot": True,
                "allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True,
                "capabilities": {"drop": ["ALL"]},
            },
        }
        documents: list[dict[str, Any]] = [
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": name, "namespace": namespace, "labels": labels},
                "spec": {
                    "replicas": 2,
                    "selector": {"matchLabels": labels},
                    "template": {
                        "metadata": {"labels": pod_labels},
                        "spec": {
                            "serviceAccountName": "ai-app",
                            "terminationGracePeriodSeconds": 60,
                            "containers": [container],
                        },
                    },
                },
            },
            {
                "apiVersion": "policy/v1",
                "kind": "PodDisruptionBudget",
                "metadata": {"name": name, "namespace": namespace},
                "spec": {"minAvailable": 1, "selector": {"matchLabels": labels}},
            },
        ]
        if queue:
            trigger: dict[str, Any] = (
                {
                    "type": "azure-servicebus",
                    "metadata": {
                        "queueName": "ai-jobs",
                        "namespace": "REPLACE_WITH_servicebus_namespace_OUTPUT",
                        "messageCount": "20",
                    },
                }
                if azure
                else {
                    "type": "aws-sqs-queue",
                    "metadata": {
                        "queueURL": "REPLACE_WITH_jobs_queue_url_OUTPUT",
                        "queueLength": "20",
                        "awsRegion": design.requirements.region,
                    },
                }
            )
            trigger["authenticationRef"] = {"name": "queue-identity"}
            documents.append(
                {
                    "apiVersion": "keda.sh/v1alpha1",
                    "kind": "ScaledObject",
                    "metadata": {"name": name, "namespace": namespace},
                    "spec": {
                        "scaleTargetRef": {"name": name},
                        "minReplicaCount": 0,
                        "maxReplicaCount": _max_replicas(design),
                        "triggers": [trigger],
                    },
                }
            )
        else:
            documents.append(
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {"name": name, "namespace": namespace, "labels": labels},
                    "spec": {"selector": labels, "ports": [{"port": 80, "targetPort": "http"}]},
                }
            )
            documents.append(
                {
                    "apiVersion": "autoscaling/v2",
                    "kind": "HorizontalPodAutoscaler",
                    "metadata": {"name": name, "namespace": namespace},
                    "spec": {
                        "scaleTargetRef": {
                            "apiVersion": "apps/v1",
                            "kind": "Deployment",
                            "name": name,
                        },
                        "minReplicas": 2,
                        "maxReplicas": _max_replicas(design),
                        "metrics": [
                            {
                                "type": "Resource",
                                "resource": {
                                    "name": "cpu",
                                    "target": {"type": "Utilization", "averageUtilization": 70},
                                },
                            }
                        ],
                    },
                }
            )
        files[f"workloads/kubernetes/{number:02d}-{name}.yaml"] = yaml.safe_dump_all(
            documents, sort_keys=False
        )
    files["workloads/kubernetes/README.md"] = (
        "# Kubernetes workload manifests\n\n"
        "Replace `${IMAGE_*}` with immutable, user-owned image references (for example with "
        "`envsubst` or Kustomize) and `REPLACE_WITH_*` values with Terraform outputs. Queue "
        "workers scale only through KEDA ScaledObjects; HTTP services use CPU HPAs, so no "
        "workload has competing autoscalers. Verify the KEDA authentication provider against "
        "your KEDA version. ArchAI never applies these manifests.\n"
    )
    return files


def _readme(design: EnterpriseDesign) -> str:
    req = design.requirements
    return f"""# Infrastructure for {design.project}

Profile `{req.profile}` in `{req.region}` (topology `{req.topology}`).

These files are **reviewed design assets**. ArchAI generated them from the canonical design and
never runs `terraform apply`. Validation level: generated only; run the checks below in your
pipeline with approved credentials and network access.

## Prerequisites (account inputs)

- Subscription/account, networks, and quotas approved for the target region.
- Immutable application images for every service (`service_images`).
- Managed model deployments (IDs, quotas) for: {", ".join(req.allowed_target_providers)}.
- Identity provider configuration (audience, issuer) and administrator groups.

## Commands

```sh
cp terraform.tfvars.example terraform.tfvars   # then replace every placeholder
terraform init -backend=false
terraform fmt -check
terraform validate
terraform plan
```

`terraform validate` does not prove that resources will deploy in a particular account or region.
"""
