from abc import ABC, abstractmethod


class Executor(ABC):

    @abstractmethod
    def execute(self, function_calls):
        raise NotImplementedError
