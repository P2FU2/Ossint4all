"""Interface base de fontes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class FonteJudicial(ABC):
    name: str

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError
