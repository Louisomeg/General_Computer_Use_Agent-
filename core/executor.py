from abc import ABC, abstractmethod
from typing import Any


class Executor(ABC):

    @abstractmethod
    def execute(self, function_calls) -> list[tuple[str, dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    def screenshot(self) -> bytes:
        raise NotImplementedError
