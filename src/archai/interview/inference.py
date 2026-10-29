"""Choose an interview answer from the project requirements when the user defers."""

from __future__ import annotations

import re
from typing import Any

from archai.interview.exclusions import suggested_exclusions
from archai.interview.questions import (
    IDPS,
    PROVIDERS,
    Question,
    _is_azure,
    is_missing,
    is_rag,
    parse_answer,
    uses_tools,
)

_REGION = re.compile(
    r"\b(westeurope|northeurope|eastus2|eastus|westus2|westus|centralus|"
    r"eu-west-1|eu-central-1|us-east-1|us-west-2)\b",
    re.IGNORECASE,
)
_RPS = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:rps|requests per second)\b", re.IGNORECASE)
_BUDGET = re.compile(
    r"(?:(?:usd|eur|gbp|\$|€|£)\s*)(\d[\d,]*(?:\.\d+)?)|"
    r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:usd|eur|gbp|per month|monthly|/month)\b",
    re.IGNORECASE,
)
_SYSTEMS = ("ServiceNow", "Salesforce", "SAP", "Jira")
_SOURCES = (
    ("sharepoint", "SharePoint"),
    ("confluence", "Confluence"),
    ("blob", "Blob"),
    ("s3", "S3"),
    ("sql", "SQL warehouse"),
)
_PLATFORMS = (
    ("apim", "APIM"),
    ("hub vnet", "hub VNet"),
    ("splunk", "Splunk"),
    ("datadog", "Datadog"),
    ("key vault", "Key Vault"),
)
_ARCHETYPE_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("enterprise-rag", ("rag", "retriev", "knowledge base", "grounded", "document")),
    ("tool-using-agent", ("tool", "refund", "ticket", "agent")),
    ("enterprise-copilot", ("copilot",)),
    ("multimodal-documents", ("multimodal", "image", "scan")),
    ("text-to-sql", ("text-to-sql", "text to sql", "sql")),
    ("realtime-voice", ("voice", "realtime", "real-time")),
    ("summarization", ("summar",)),
    ("classification-extraction", ("classif", "extract")),
    ("hybrid-integration", ("hybrid integration",)),
)


def project_text(data: dict[str, Any], *, include_users: bool = True) -> str:
    """Lowercased requirements already collected, used to pick a deferred answer."""
    parts: list[str] = []
    for key in ("idea", "business_outcome", "notes"):
        if data.get(key):
            parts.append(str(data[key]))
    keys = ["archetypes", "integrations", "data_sources", "client_channels"]
    if include_users:
        keys.insert(0, "users")
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value:
            parts.append(str(value))
    return " ".join(parts).lower()


def best_answer(question: Question, data: dict[str, Any]) -> tuple[Any, str] | None:
    """Return the best typed value and why, or None when the project does not decide it."""
    handler = _HANDLERS.get(question.field)
    if handler is not None:
        chosen = handler(data)
        if chosen is not None:
            value, rationale = chosen
            parsed = _parse(question, value, data)
            if parsed is None:
                return None
            return parsed, rationale
    fallback = question.default_value(data)
    if is_missing(fallback):
        return None
    parsed = _parse(question, fallback, data)
    if parsed is None or is_missing(parsed):
        return None
    return parsed, "planning default for this workload"


def _parse(question: Question, value: Any, data: dict[str, Any]) -> Any | None:
    try:
        return parse_answer(question, value, data)
    except ValueError:
        return None


def _named(text: str, catalog: tuple[tuple[str, str], ...] | tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for item in catalog:
        if isinstance(item, tuple):
            needle, label = item
        else:
            needle, label = item.lower(), item
        if needle in text and label not in found:
            found.append(label)
    return found


def _business_outcome(data: dict[str, Any]) -> tuple[Any, str] | None:
    idea = str(data.get("idea") or "").strip()
    if len(idea) < 12:
        return None
    return idea[:400], "using the project description as the business outcome"


def _users(data: dict[str, Any]) -> tuple[Any, str] | None:
    text = project_text(data, include_users=False)
    groups: list[str] = []
    for needle, label in (
        ("support", "support agents"),
        ("finance", "finance approvers"),
        ("customer", "customers"),
        ("developer", "internal developers"),
        ("employee", "employees"),
    ):
        if needle in text and label not in groups:
            groups.append(label)
    if not groups:
        return None
    return groups, "user groups named by the project description"


def _user_roles(data: dict[str, Any]) -> tuple[Any, str] | None:
    text = project_text(data)
    roles = ["agent" if "agent" in text or "support" in text else "user"]
    if data.get("tool_side_effects") == "approval" or "approv" in text or "finance" in text:
        roles.append("approver")
    roles.append("admin")
    unique = list(dict.fromkeys(roles))
    why = (
        "approval actions need an approver alongside an operator and an admin"
        if "approver" in unique
        else "an operator role and an admin role cover the described users"
    )
    return unique, why


def _channels(data: dict[str, Any]) -> tuple[Any, str] | None:
    text = project_text(data)
    channels: list[str] = []
    for needle, label in (
        ("teams", "Microsoft Teams"),
        ("slack", "Slack"),
        ("mobile", "mobile app"),
        ("public api", "public API"),
        ("internal api", "internal API"),
        ("web", "web app"),
    ):
        if needle in text:
            channels.append(label)
    if not channels:
        return ["web app"], "no channel was named; a web app is the default client"
    return channels, "channels named by the project description"


def _archetypes(data: dict[str, Any]) -> tuple[Any, str] | None:
    text = project_text(data, include_users=False)
    matched = [
        name for name, needles in _ARCHETYPE_SIGNALS if any(needle in text for needle in needles)
    ]
    if not matched:
        return None
    return matched, "workload types matched from the project description"


def _side_effects(data: dict[str, Any]) -> tuple[Any, str] | None:
    text = project_text(data, include_users=False)
    if any(
        word in text for word in ("read-only", "read only", "must not change", "no side effect")
    ):
        return "forbidden", "the project describes a read-only assistant"
    if "autonomous" in text or "without approval" in text:
        return "allowed", "the project asks for autonomous actions"
    if any(word in text for word in ("refund", "email", "update", "ticket", "write", "approval")):
        return "approval", "actions that change other systems need a human approval"
    if uses_tools(data):
        return "approval", "tool use is in scope, so actions wait for human approval"
    if is_rag(data):
        return "forbidden", "the workload is retrieval without a described write action"
    return None


def _integrations(data: dict[str, Any]) -> tuple[Any, str] | None:
    text = project_text(data)
    found = _named(text, _SYSTEMS)
    if found:
        return found, "business systems named in the project description"
    if any(
        word in text for word in ("refund", "ticket", "itsm", "help desk", "helpdesk", "support")
    ):
        return ["ServiceNow"], "support work with actions fits a ticket system (ServiceNow)"
    if "crm" in text or "sales pipeline" in text:
        return ["Salesforce"], "sales work fits a CRM (Salesforce)"
    if uses_tools(data):
        return ["internal REST APIs"], "tools are in scope and no business system was named"
    return [], "no business system is in scope"


def _data_sources(data: dict[str, Any]) -> tuple[Any, str] | None:
    text = project_text(data)
    found = _named(text, _SOURCES)
    if found:
        return found, "knowledge sources named in the project description"
    if not is_rag(data):
        return None
    profile = str(data.get("profile") or "")
    if profile == "aws-eks":
        return ["S3"], "retrieval is in scope on AWS and no source was named"
    if _is_azure(data) or not profile:
        return ["SharePoint"], "retrieval is in scope on Azure and no source was named"
    return ["approved documents"], "retrieval is in scope and no source was named"


_DEPLOYMENT_BASELINE = {
    "azure-aca": ["Azure API Management", "Azure Container Apps"],
    "azure-aks": ["Azure API Management", "AKS"],
    "aws-eks": ["Amazon API Gateway", "Amazon EKS"],
    "agnostic": ["managed API gateway"],
}
_EXCLUSION_LABELS = {
    "cache": "cache",
    "auth": "RBAC",
    "infra": "cloud deployment",
    "rag": "retrieval",
    "observe": "observability",
    "eval": "evaluation",
    "workflow": "workflows",
    "guard": "guardrails",
    "resilience": "resilience",
}


def _existing_services(data: dict[str, Any]) -> tuple[Any, str] | None:
    if "infra" in (data.get("excluded_components") or []):
        return [], "cloud deployment is excluded"
    text = project_text(data)
    found = _named(text, _PLATFORMS)
    if found:
        return found, "platform services named in the project description"
    profile = str(data.get("profile") or "azure-aca")
    services = _DEPLOYMENT_BASELINE.get(profile, _DEPLOYMENT_BASELINE["azure-aca"])
    return services, f"no existing platform was named; use the {profile} deployment baseline"


def _excluded_components(data: dict[str, Any]) -> tuple[Any, str] | None:
    names = suggested_exclusions(data)
    if not names:
        return None
    labels = [_EXCLUSION_LABELS[name] for name in names if name in _EXCLUSION_LABELS]
    if not labels:
        return None
    return labels, "these optional parts are not required for this workload"


def _providers(data: dict[str, Any]) -> tuple[Any, str] | None:
    text = project_text(data)
    found = [name for name in PROVIDERS if name.lower() in text]
    if found:
        return found, "providers named in the project description"
    if _is_azure(data):
        return ["Azure OpenAI"], "Azure hosting uses Azure OpenAI as the managed provider"
    if data.get("profile") == "aws-eks":
        return ["AWS Bedrock"], "Amazon EKS hosting uses Amazon Bedrock as the managed provider"
    return None


def _topology(data: dict[str, Any]) -> tuple[Any, str] | None:
    text = project_text(data)
    if any(word in text for word in ("disaster recovery", "secondary region", "application-dr")):
        return "application-dr", "the project asks for a second application environment"
    providers = data.get("allowed_target_providers") or []
    if "failover" in text or (isinstance(providers, list) and len(providers) > 1):
        return "provider-failover", "more than one approved provider enables provider failover"
    return "single-cloud", "one approved provider keeps a single-cloud topology"


def _profile(data: dict[str, Any]) -> tuple[Any, str] | None:
    text = project_text(data)
    if any(word in text for word in ("agnostic", "portable", "cloud agnostic")):
        return "agnostic", "the project asks for a portable design"
    if "eks" in text or (re.search(r"\baws\b", text) and "azure" not in text):
        return "aws-eks", "the project targets Amazon EKS"
    if "aks" in text or "kubernetes" in text:
        return "azure-aks", "the project targets Kubernetes on Azure"
    if "container apps" in text or "azure" in text:
        return "azure-aca", "the project targets Azure Container Apps"
    return None


def _region(data: dict[str, Any]) -> tuple[Any, str] | None:
    match = _REGION.search(project_text(data))
    if match:
        return match.group(1), "region named in the project description"
    if data.get("profile") == "aws-eks":
        return "eu-west-1", "EU hosting on Amazon EKS uses eu-west-1 unless another region is named"
    if any(word in project_text(data) for word in ("eu", "europe", "gdpr")):
        return "westeurope", "EU requirements use westeurope unless another region is named"
    return None


def _residency(data: dict[str, Any]) -> tuple[Any, str] | None:
    region = data.get("region")
    if region:
        return [str(region)], "data stays in the primary hosting region"
    return None


def _identity(data: dict[str, Any]) -> tuple[Any, str] | None:
    text = project_text(data)
    for name in IDPS:
        if name.lower() in text:
            return name, "identity provider named in the project description"
    if data.get("profile") == "aws-eks":
        return "AWS Cognito", "Amazon EKS projects use Cognito when no other IdP is named"
    if str(data.get("profile") or "").startswith("azure") or not data.get("profile"):
        return "Entra ID", "Azure projects use Entra ID when no other IdP is named"
    return "Keycloak", "a portable project uses Keycloak when no other IdP is named"


def _classification(data: dict[str, Any]) -> tuple[Any, str] | None:
    text = project_text(data)
    if any(word in text for word in ("hipaa", "pci", "cardholder", "restricted", "secret")):
        return "restricted", "the project handles regulated or restricted data"
    if "public" in text and "customer" not in text:
        return "public", "the project describes public data"
    if "internal only" in text:
        return "internal", "the project describes internal data"
    return "confidential", "enterprise user and document data is treated as confidential"


def _compliance(data: dict[str, Any]) -> tuple[Any, str] | None:
    text = project_text(data)
    region = str(data.get("region") or "")
    frameworks: list[str] = []
    if "gdpr" in text or "eu" in region.lower() or "europe" in text:
        frameworks.append("GDPR")
    if "hipaa" in text or "health" in text:
        frameworks.append("HIPAA")
    if "pci" in text or "cardholder" in text:
        frameworks.append("PCI DSS")
    if "iso 27001" in text or "iso27001" in text:
        frameworks.append("ISO 27001")
    if "eu ai act" in text:
        frameworks.append("EU AI Act")
    if "soc" in text:
        frameworks.append("SOC 2")
    if not frameworks and "eu" not in region.lower():
        return ["SOC 2"], "no framework was named; SOC 2 is the enterprise baseline"
    if not frameworks:
        return ["GDPR"], "the hosting region is in the EU"
    return frameworks, "frameworks implied by the region and the project description"


def _budget(data: dict[str, Any]) -> tuple[Any, str] | None:
    match = _BUDGET.search(project_text(data))
    if match is None:
        return None
    amount = (match.group(1) or match.group(2)).replace(",", "")
    return amount, "monthly limit stated in the project description"


def _avg_rps(data: dict[str, Any]) -> tuple[Any, str] | None:
    match = _RPS.search(project_text(data))
    if match is None:
        return None
    return match.group(1), "request rate stated in the project description"


_HANDLERS = {
    "business_outcome": _business_outcome,
    "users": _users,
    "user_roles": _user_roles,
    "client_channels": _channels,
    "archetypes": _archetypes,
    "tool_side_effects": _side_effects,
    "integrations": _integrations,
    "data_sources": _data_sources,
    "existing_services": _existing_services,
    "excluded_components": _excluded_components,
    "allowed_target_providers": _providers,
    "topology": _topology,
    "profile": _profile,
    "region": _region,
    "data_residency": _residency,
    "identity_provider": _identity,
    "data_classification": _classification,
    "compliance": _compliance,
    "monthly_budget": _budget,
    "avg_rps": _avg_rps,
}
