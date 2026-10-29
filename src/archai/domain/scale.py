"""Workload scale-up contract shared by design documents and generated manifests.

Replica numbers are load-test starting points derived from peak capacity. They are not measured
limits, and provider quotas still bound model throughput. ArchAI never applies the autoscalers.
"""

from __future__ import annotations

from dataclasses import dataclass

from archai.schemas.models import EnterpriseDesign, Service

WORKLOAD_KINDS = frozenset(
    {
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
)
QUEUE_KINDS = frozenset({"worker", "ingestion"})
_KUBERNETES_PROFILES = frozenset({"azure-aks", "aws-eks"})


@dataclass(frozen=True)
class ScaleTarget:
    service_id: str
    name: str
    kind: str
    mode: str
    replicas: str
    trigger: str
    bound: str


def replica_ceiling(design: EnterpriseDesign) -> int:
    """Upper replica count written into generated autoscalers.

    Peak worker estimate times three, clamped to the range 3-30. Missing capacity uses 2 workers,
    which yields a ceiling of 6.
    """
    workers = design.capacity.worker_count if design.capacity else 2
    return max(3, min(30, workers * 3))


def minimum_replicas(design: EnterpriseDesign, kind: str) -> int:
    """Minimum replicas for a generated workload autoscaler."""
    if kind in QUEUE_KINDS:
        return 0
    if design.requirements.profile in _KUBERNETES_PROFILES:
        return 2
    return 1


def scale_targets(design: EnterpriseDesign) -> list[ScaleTarget]:
    ceiling = replica_ceiling(design)
    return [_target(design, service, ceiling) for service in design.services]


def _target(design: EnterpriseDesign, service: Service, ceiling: int) -> ScaleTarget:
    if service.kind not in WORKLOAD_KINDS:
        return ScaleTarget(
            service_id=service.id,
            name=service.name,
            kind=service.kind,
            mode="managed",
            replicas="managed",
            trigger=_managed_trigger(service.kind),
            bound=_bound(service.kind),
        )
    minimum = minimum_replicas(design, service.kind)
    mode = "queue" if service.kind in QUEUE_KINDS else "http"
    return ScaleTarget(
        service_id=service.id,
        name=service.name,
        kind=service.kind,
        mode=mode,
        replicas=f"{minimum}-{ceiling}",
        trigger=_workload_trigger(design.requirements.profile, mode),
        bound=_bound(service.kind),
    )


def _managed_trigger(kind: str) -> str:
    if kind == "gateway":
        return (
            "Managed gateway units sized for peak request rate; not a generated replica autoscaler"
        )
    return "Managed platform service; not a generated replica autoscaler"


def _workload_trigger(profile: str, mode: str) -> str:
    if mode == "queue":
        if profile == "azure-aca":
            return "Container Apps Service Bus scale rule at 20 messages; scale to zero when idle"
        if profile == "azure-aks":
            return (
                "KEDA Azure Service Bus scaler at 20 messages; no CPU autoscaler on this workload"
            )
        if profile == "aws-eks":
            return "KEDA SQS scaler at queue length 20; no CPU autoscaler on this workload"
        return "Queue-length autoscaler at 20 messages; no competing CPU scaler"
    if profile == "azure-aca":
        return "Container Apps HTTP scale rule at 50 concurrent requests"
    if profile in _KUBERNETES_PROFILES:
        return "HorizontalPodAutoscaler at 70% CPU"
    return "HTTP concurrency autoscaling"


def _bound(kind: str) -> str:
    if kind == "gateway":
        return "Gateway SKU is an account input; size it for peak RPS"
    if kind in {"ai-gateway", "policy", "worker", "ingestion"}:
        return "Provider request and token quotas, not replica count"
    if kind == "retrieval":
        return "Search-unit capacity and provider quotas"
    if kind == "operations":
        return "Managed telemetry service limits"
    return "Replica ceiling and downstream quotas"
