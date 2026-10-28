from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class StructuredResult[T: BaseModel]:
    value: T
    usage: Usage


class ArchitectProvider(Protocol):
    def generate[T: BaseModel](self, prompt: str, output_type: type[T]) -> StructuredResult[T]: ...
