"""Typed interview question bank shared by guided runs and non-interactive diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

QuestionKind = Literal["text", "list", "choice", "multichoice", "int", "decimal"]

ARCHETYPES = (
    "enterprise-rag",
    "tool-using-agent",
    "enterprise-copilot",
    "multimodal-documents",
    "text-to-sql",
    "realtime-voice",
    "summarization",
    "classification-extraction",
    "hybrid-integration",
)
PROVIDERS = ("Azure OpenAI", "AWS Bedrock", "OpenAI", "Anthropic", "Google Vertex AI")
CHANNELS = ("web app", "mobile app", "Microsoft Teams", "Slack", "public API", "internal API")
COMPLIANCE = ("GDPR", "SOC 2", "ISO 27001", "HIPAA", "PCI DSS", "EU AI Act", "none")
IDPS = ("Entra ID", "Okta", "Auth0", "AWS Cognito", "Keycloak", "Google Workspace")


@dataclass(frozen=True)
class Question:
    id: str
    field: str
    group: str
    prompt: str
    kind: QuestionKind
    critical: bool
    help: str = ""
    choices: tuple[str, ...] = ()
    allow_other: bool = True
    default: Callable[[dict[str, Any]], Any] | None = None
    when: Callable[[dict[str, Any]], bool] | None = None
    validate: Callable[[Any, dict[str, Any]], str | None] | None = None

    def applies(self, data: dict[str, Any]) -> bool:
        return self.when is None or self.when(data)

    def default_value(self, data: dict[str, Any]) -> Any:
        return self.default(data) if self.default else None


def is_rag(data: dict[str, Any]) -> bool:
    text = " ".join(str(item) for item in data.get("archetypes") or []).lower()
    return any(word in text for word in ("rag", "retriev", "knowledge", "search", "document"))


def uses_tools(data: dict[str, Any]) -> bool:
    text = " ".join(str(item) for item in data.get("archetypes") or []).lower()
    return "agent" in text or "tool" in text or "sql" in text or bool(data.get("integrations"))


def _is_azure(data: dict[str, Any]) -> bool:
    return str(data.get("profile") or "azure-aca").startswith("azure")


def keeps(component: str) -> Callable[[dict[str, Any]], bool]:
    def check(data: dict[str, Any]) -> bool:
        return component not in (data.get("excluded_components") or [])

    return check


def rag_in_scope(data: dict[str, Any]) -> bool:
    return is_rag(data) and keeps("rag")(data)


def _peak_check(value: Any, data: dict[str, Any]) -> str | None:
    avg = data.get("avg_rps")
    try:
        if avg is not None and Decimal(str(value)) < Decimal(str(avg)):
            return f"Peak RPS must be at least the average RPS ({avg})."
    except InvalidOperation:
        return None
    return None


def _currency_check(value: Any, data: dict[str, Any]) -> str | None:
    del data
    text = str(value)
    if len(text) != 3 or not text.isalpha():
        return "Use a three-letter ISO currency code such as USD or EUR."
    return None


def _availability_check(value: Any, data: dict[str, Any]) -> str | None:
    del data
    number = Decimal(str(value))
    if number <= 0 or number > 100:
        return "Availability is a percentage between 0 and 100, for example 99.9."
    return None


QUESTIONS: tuple[Question, ...] = (
    # ------------------------------------------------------------------ business
    Question(
        "REQ-BUSINESS_OUTCOME",
        "business_outcome",
        "Business goals and users",
        "What business outcome must this AI application achieve?",
        "text",
        True,
        "One or two sentences, e.g. 'Cut support resolution time by 30% without exposing "
        "other tenants' data'.",
    ),
    Question(
        "REQ-USERS",
        "users",
        "Business goals and users",
        "Who will use it? (comma-separated user groups)",
        "list",
        True,
        "Examples: support agents, finance approvers, customers, internal developers.",
    ),
    Question(
        "REQ-USER_ROLES",
        "user_roles",
        "Business goals and users",
        "Which application roles or permission levels are needed?",
        "list",
        False,
        "Used for the RBAC/ABAC design, e.g. reader, agent, approver, admin. "
        "Say 'no RBAC' or 'RBAC excluded' to leave user roles out of the design.",
        default=lambda data: ["user", "admin"],
        when=keeps("auth"),
    ),
    Question(
        "REQ-CLIENT_CHANNELS",
        "client_channels",
        "Business goals and users",
        "Which client channels will call the application?",
        "multichoice",
        False,
        "Pick numbers or type names, comma-separated.",
        CHANNELS,
        default=lambda data: ["web app"],
    ),
    # ------------------------------------------------------------------ AI capabilities
    Question(
        "REQ-ARCHETYPES",
        "archetypes",
        "AI capabilities",
        "Which AI workload types does it include?",
        "multichoice",
        True,
        "RAG = grounded answers over your documents; tool-using agent = calls APIs/tools.",
        ARCHETYPES,
    ),
    Question(
        "REQ-TOOL_SIDE_EFFECTS",
        "tool_side_effects",
        "AI capabilities",
        "May the AI perform actions that change external systems (refunds, emails, updates)?",
        "choice",
        True,
        "forbidden = read-only; approval = a human approves each exact action; allowed = "
        "autonomous within authorization.",
        ("forbidden", "approval", "allowed"),
        allow_other=False,
    ),
    Question(
        "REQ-EXCLUDED",
        "excluded_components",
        "Optional capabilities",
        "Which optional parts are not required for this application?",
        "multichoice",
        False,
        "cache, RBAC, cloud deployment, retrieval, observability, evaluation, workflows, "
        "guardrails, resilience. Enter takes the best fit for this workload. Type none to keep "
        "them all. 'cache excluded', 'I don't need RBAC', or 'deployment excluded' drops that part.",
        (
            "cache",
            "RBAC",
            "cloud deployment",
            "retrieval",
            "observability",
            "evaluation",
            "workflows",
            "guardrails",
            "resilience",
            "none",
        ),
    ),
    Question(
        "REQ-INTEGRATIONS",
        "integrations",
        "AI capabilities",
        "Which business systems or tools must it integrate with?",
        "list",
        False,
        "Examples: ServiceNow, Salesforce, SAP, Jira, internal REST APIs. "
        "Press Enter or type none and ArchAI picks the best fit from the project.",
        when=uses_tools,
    ),
    Question(
        "REQ-DATA_SOURCES",
        "data_sources",
        "AI capabilities",
        "Which knowledge sources feed retrieval?",
        "list",
        False,
        "Examples: SharePoint, Confluence, product PDFs in Blob/S3, a SQL warehouse. "
        "Say 'retrieval excluded' to leave RAG out of the design.",
        when=rag_in_scope,
    ),
    Question(
        "REQ-DOCUMENTS_PER_DAY",
        "documents_per_day",
        "AI capabilities",
        "Roughly how many documents are ingested or re-indexed per day?",
        "int",
        False,
        "Drives the asynchronous ingestion path and worker sizing.",
        default=lambda data: 500,
        when=rag_in_scope,
    ),
    # ------------------------------------------------------------------ traffic
    Question(
        "REQ-AVG_RPS",
        "avg_rps",
        "Traffic and workload",
        "Average requests per second at the application API?",
        "decimal",
        True,
        "1 RPS ≈ 86,400 requests/day. A team of 200 agents chatting is typically 0.5–2 RPS.",
        default=lambda data: "1",
    ),
    Question(
        "REQ-PEAK_RPS",
        "peak_rps",
        "Traffic and workload",
        "Peak requests per second?",
        "decimal",
        True,
        "Usually 3–5× the average for business-hours workloads.",
        default=lambda data: str(Decimal(str(data.get("avg_rps") or 1)) * 4),
        validate=_peak_check,
    ),
    Question(
        "REQ-INPUT_TOKENS",
        "input_tokens",
        "Traffic and workload",
        "Average input tokens per model call (prompt + retrieved context)?",
        "int",
        True,
        "RAG prompts with 4–6 retrieved chunks are often 1,500–4,000 tokens.",
        default=lambda data: 2500 if is_rag(data) else 1000,
    ),
    Question(
        "REQ-OUTPUT_TOKENS",
        "output_tokens",
        "Traffic and workload",
        "Average output tokens per model call?",
        "int",
        True,
        "Chat answers are commonly 300–800 tokens.",
        default=lambda data: 500,
    ),
    Question(
        "REQ-MODEL_CALLS_PER_REQUEST",
        "model_calls_per_request",
        "Traffic and workload",
        "Average model calls per user request?",
        "decimal",
        True,
        "1 for simple chat; agents and query rewriting typically need 2–4.",
        default=lambda data: "2" if uses_tools(data) else "1",
    ),
    # ------------------------------------------------------------------ providers
    Question(
        "REQ-ALLOWED_TARGET_PROVIDERS",
        "allowed_target_providers",
        "Managed AI providers",
        "Which managed model providers may the application call?",
        "multichoice",
        True,
        "Only approved providers are eligible for routing and fallback.",
        PROVIDERS,
        default=lambda data: ["Azure OpenAI"] if _is_azure(data) else ["AWS Bedrock"],
    ),
    Question(
        "REQ-TOPOLOGY",
        "topology",
        "Managed AI providers",
        "Which resilience topology do you need?",
        "choice",
        False,
        "single-cloud = one provider; provider-failover = fall back to another approved "
        "provider; application-dr = full secondary application environment.",
        ("single-cloud", "provider-failover", "application-dr"),
        allow_other=False,
        default=lambda data: (
            "provider-failover"
            if len(data.get("allowed_target_providers") or []) > 1
            else "single-cloud"
        ),
    ),
    # ------------------------------------------------------------------ cloud
    Question(
        "REQ-PROFILE",
        "profile",
        "Cloud and deployment",
        "Where will the application be hosted?",
        "choice",
        False,
        "azure-aca = Azure Container Apps; azure-aks = AKS; aws-eks = Amazon EKS; agnostic = "
        "portable design without cloud-specific Terraform.",
        ("azure-aca", "azure-aks", "aws-eks", "agnostic"),
        allow_other=False,
        default=lambda data: "azure-aca",
        when=keeps("infra"),
    ),
    Question(
        "REQ-REGION",
        "region",
        "Cloud and deployment",
        "Primary hosting region?",
        "text",
        True,
        "Cloud region name, e.g. westeurope, eastus2, eu-west-1.",
        default=lambda data: "eu-west-1" if data.get("profile") == "aws-eks" else "westeurope",
    ),
    Question(
        "REQ-DATA_RESIDENCY",
        "data_residency",
        "Cloud and deployment",
        "Which regions may store or process data? (comma-separated)",
        "list",
        True,
        "Model endpoints and data stores outside these regions are rejected.",
        default=lambda data: [data["region"]] if data.get("region") else None,
    ),
    Question(
        "REQ-EXISTING_SERVICES",
        "existing_services",
        "Cloud and deployment",
        "Any existing platform services the design must reuse?",
        "list",
        False,
        "Examples: existing APIM instance, hub VNet, Splunk, Datadog. "
        "Press Enter or type none and ArchAI picks the platform baseline for this deployment. "
        "Say 'deployment excluded' or 'I don't need cloud deployment' to leave hosting out.",
        when=keeps("infra"),
    ),
    # ------------------------------------------------------------------ identity and security
    Question(
        "REQ-IDENTITY_PROVIDER",
        "identity_provider",
        "Identity and security",
        "Which identity provider signs users in (OIDC/OAuth 2.0)?",
        "choice",
        False,
        "Drives the OAuth flows, token validation, and workload identity design. "
        "Say 'no RBAC' to leave user authorization out of the design.",
        IDPS,
        default=lambda data: "Entra ID",
        when=keeps("auth"),
    ),
    Question(
        "REQ-TENANT_ISOLATION",
        "tenant_isolation",
        "Identity and security",
        "Is it single-tenant or multi-tenant?",
        "choice",
        True,
        "multi = several customer organizations share the deployment with strict isolation.",
        ("single", "multi"),
        allow_other=False,
    ),
    Question(
        "REQ-DATA_CLASSIFICATION",
        "data_classification",
        "Identity and security",
        "Highest data classification the application handles?",
        "choice",
        False,
        "restricted disables semantic response caching by default.",
        ("public", "internal", "confidential", "restricted"),
        allow_other=False,
        default=lambda data: "confidential",
    ),
    Question(
        "REQ-COMPLIANCE",
        "compliance",
        "Identity and security",
        "Which compliance frameworks apply?",
        "multichoice",
        False,
        "Used for control mapping; ArchAI never claims compliance.",
        COMPLIANCE,
        default=lambda data: ["GDPR"] if "eu" in str(data.get("region", "")).lower() else [],
    ),
    # ------------------------------------------------------------------ reliability
    Question(
        "REQ-AVAILABILITY_TARGET",
        "availability_target",
        "Reliability",
        "Availability target (%)?",
        "decimal",
        True,
        "99.9% ≈ 43 minutes of downtime per month.",
        default=lambda data: "99.9",
        validate=_availability_check,
    ),
    Question(
        "REQ-LATENCY_P95_MS",
        "latency_p95_ms",
        "Reliability",
        "Target p95 end-to-end latency in milliseconds?",
        "int",
        False,
        "Streaming chat typically targets first token < 1500 ms and completion < 8000 ms.",
        default=lambda data: 8000,
    ),
    Question(
        "REQ-RTO_MINUTES",
        "rto_minutes",
        "Reliability",
        "Recovery time objective (RTO) in minutes?",
        "int",
        False,
        "How long the application may be unavailable after a regional failure.",
        default=lambda data: 60 if data.get("topology") == "application-dr" else 240,
    ),
    Question(
        "REQ-RPO_MINUTES",
        "rpo_minutes",
        "Reliability",
        "Recovery point objective (RPO) in minutes?",
        "int",
        False,
        "Maximum acceptable data loss window.",
        default=lambda data: 15 if data.get("topology") == "application-dr" else 60,
    ),
    # ------------------------------------------------------------------ budget
    Question(
        "REQ-CURRENCY",
        "currency",
        "Budget and governance",
        "Budget currency (ISO code)?",
        "text",
        True,
        "Example: USD, EUR, GBP.",
        default=lambda data: "EUR" if "eu" in str(data.get("region", "")).lower() else "USD",
        validate=_currency_check,
    ),
    Question(
        "REQ-MONTHLY_BUDGET",
        "monthly_budget",
        "Budget and governance",
        "Hard monthly spending limit for model usage?",
        "decimal",
        True,
        "A hard limit rejects new chargeable work when exhausted. Enter a number only.",
    ),
)

QUESTION_BY_FIELD = {question.field: question for question in QUESTIONS}
QUESTION_BY_ID = {question.id: question for question in QUESTIONS}


def is_missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def field_unanswered(question: Question, data: dict[str, Any]) -> bool:
    """True when this question still needs an answer.

    An empty exclusion list is an answer: it keeps every optional part.
    """
    if question.field == "excluded_components":
        return data.get("excluded_components") is None
    return is_missing(data.get(question.field))


def missing_questions(
    data: dict[str, Any], *, critical_only: bool = False, include_optional: bool = True
) -> list[Question]:
    """Questions whose fields are unanswered, in interview order."""
    result: list[Question] = []
    for question in QUESTIONS:
        if critical_only and not question.critical:
            continue
        if not include_optional and not question.critical:
            continue
        if not question.applies(data):
            continue
        if field_unanswered(question, data):
            result.append(question)
    return result


def _match_choice(question: Question, token: str) -> str:
    token = token.strip()
    if token.isdigit() and question.choices:
        index = int(token)
        if 1 <= index <= len(question.choices):
            return question.choices[index - 1]
        raise ValueError(f"choose a number between 1 and {len(question.choices)}")
    for choice in question.choices:
        if choice.lower() == token.lower():
            return choice
    if question.allow_other and token:
        return token
    raise ValueError("choose one of: " + ", ".join(question.choices))


def parse_answer(question: Question, raw: Any, data: dict[str, Any] | None = None) -> Any:
    """Convert raw text (or an already typed value) into the field's value."""
    context = data or {}
    if isinstance(raw, list) and question.kind in {"list", "multichoice"}:
        items = [str(item).strip() for item in raw if str(item).strip()]
        value: Any = (
            [_match_choice(question, item) for item in items]
            if question.kind == "multichoice"
            else items
        )
    else:
        text = str(raw).strip()
        if question.kind == "text":
            if not text:
                raise ValueError("an answer is required")
            value = text.upper() if question.field == "currency" else text
        elif question.kind == "list":
            value = [item.strip() for item in text.split(",") if item.strip()]
        elif question.kind == "multichoice":
            items = [_match_choice(question, item) for item in text.split(",") if item.strip()]
            value = [item for item in items if item.lower() != "none"]
        elif question.kind == "choice":
            value = _match_choice(question, text)
        elif question.kind == "int":
            cleaned = text.replace(",", "").replace("_", "")
            try:
                value = int(Decimal(cleaned))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError("enter a whole number") from exc
            if value < 0:
                raise ValueError("enter a positive number")
        else:
            cleaned = text.replace(",", "").replace("_", "")
            for symbol in ("$", "€", "£", "%"):
                cleaned = cleaned.replace(symbol, "")
            try:
                number = Decimal(cleaned.strip())
            except InvalidOperation as exc:
                raise ValueError("enter a number") from exc
            if number <= 0:
                raise ValueError("enter a number greater than zero")
            value = format(number.normalize(), "f")
    if question.kind in {"list", "multichoice"} and question.critical and not value:
        raise ValueError("at least one value is required")
    if question.validate is not None:
        problem = question.validate(value, context)
        if problem:
            raise ValueError(problem)
    return value


def format_value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "—"
    return str(value)
