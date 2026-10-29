from dataclasses import dataclass


@dataclass(frozen=True)
class SpecialistRole:
    name: str
    prompt_version: str = "1.0.0"
    timeout_seconds: int = 120
    token_allowance: int = 10_000
    repair_attempts: int = 2


ROLES = (
    SpecialistRole("Enterprise Requirements Architect"),
    SpecialistRole("API Management and AI Routing Architect"),
    SpecialistRole("Cloud, Data, and Resilience Architect"),
    SpecialistRole("Identity, Security, and Observability Architect"),
    SpecialistRole("Design Verifier and Compiler"),
)

assert len(ROLES) == 5
