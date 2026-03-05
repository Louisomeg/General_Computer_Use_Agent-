"""
Agentic Loop — shared foundation for all agents.

Screenshot delivery follows Google's reference implementation:
  - Initial screenshot bundled with the prompt
  - Subsequent screenshots bundled with function responses
  (NOT as separate user messages)

Backward compatible with Louis's desktop usage:
    loop = AgenticLoop(client)
    loop.agentic_loop("open freecad", DesktopExecutor())
"""

import time
from abc import ABC, abstractmethod
from typing import Any, Optional

import termcolor
from google.genai import Client, types
from google.genai.types import Candidate, FunctionCall, GenerateContentConfig

from core.executor import Executor
from core.settings import SYSTEM_INSTRUCTION


# NOTE: This is the public interface of AgenticLoop.
# Please try to use this type
# If you are an agent(or human), please try to avoid modifying the main AgenticLoop class
# unless you really have reason too. If you do, make sure to change the interface accordingly
# and fix all other locations where this interface has been used
class BaseAgenticLoop(ABC):
    def __init__(
        self,
        client: Client,
        model_name: str = "gemini-2.5-computer-use-preview-10-2025",
        config: Optional[dict[str, Any]] = None,
    ):
        self.client = client
        self.model_name = model_name
        self.config = config

    @abstractmethod
    def agentic_loop(self, prompt: str, executor: Executor, max_turns: int = 0) -> int:
        raise NotImplementedError


class AgenticLoop(BaseAgenticLoop):
    def __init__(
        self,
        client: Client,
        model_name: str = "gemini-2.5-computer-use-preview-10-2025",
        config: Optional[dict[str, Any]] = None,
    ):
        # NOTE: system_instructions and custom declarations should now be passed through config
        self.client = client
        self.model_name = model_name
        self._config = config or {}
        self.max_turns = 0
        self.history = []

    def agentic_loop(
        self, prompt: str, executor: Executor, max_turns: int = 25
    ) -> int:  # NOTE: it returns the number of turns used
        """Run the agentic loop: model → execute → screenshot → repeat.
        Returns number of turns used
        Throws http errors
        """
        turn_count = 0
        self.max_turns = max_turns
        initial_prompt_content = self.build_initial_prompt(executor, prompt)
        self.history = [initial_prompt_content]
        for turn_count in range(self.max_turns):
            response = self.get_model_response()
            candidate = self.get_and_validate_candidate(response)
            if not candidate:
                continue
            reasoning = self.get_text(candidate)
            function_calls = self.extract_function_calls(candidate)
            self.log_turn_info(reasoning, function_calls, turn_count)
            valid_fc = self.validate_function_calls(
                function_calls, reasoning, candidate
            )
            if not valid_fc:
                continue
            # No function calls → model is done talking
            if not function_calls:
                print(f"Agent Loop or Task Complete: {reasoning}")
                break
            response_parts = self.execute_functions(function_calls, executor)
            self.add_extra_messages(turn_count, response_parts)
            self.history.append(types.Content(role="user", parts=response_parts))

            # to save context window
            self.clean_old_screenshots()

        if turn_count + 1 == max_turns:
            termcolor.cprint(f"Max turns ({self.max_turns}) reached.", color="yellow")

        return turn_count

    def build_initial_prompt(self, executor: Executor, prompt: str) -> types.Content:
        screenshot_bytes = executor.screenshot()
        initial_prompt_screenshot_part = types.Part.from_bytes(
            mime_type="image/png", data=screenshot_bytes
        )
        initial_prompt_parts = [
            types.Part.from_text(text=prompt),
            initial_prompt_screenshot_part,
        ]
        initial_prompt_content = types.Content(role="user", parts=initial_prompt_parts)
        return initial_prompt_content

    def log_turn_info(
        self,
        reasoning: Optional[str],
        function_calls: list[types.FunctionCall],
        turn_count: int,
    ) -> None:
        turn_info = (
            f"[Turn {turn_count}/{self.max_turns}] {len(function_calls)} action(s)"
        )
        if reasoning:
            short = reasoning[:150] + "..." if len(reasoning) > 150 else reasoning
            turn_info += f" | {short}"
        print(turn_info)

    def validate_function_calls(
        self,
        function_calls: list[FunctionCall],
        reasoning: Optional[str],
        candidate: Candidate,
    ) -> bool:
        if (
            not function_calls
            and not reasoning
            and candidate.finish_reason == types.FinishReason.MALFORMED_FUNCTION_CALL
        ):
            # Re-send the last screenshot so the model can try again
            self.history.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text="The previous request returned no response. "
                            "Please look at the most recent screenshot and "
                            "continue with the next action."
                        ),
                    ],
                )
            )
            return False
        return True

    def execute_functions(
        self, function_calls: list[FunctionCall], executor: Executor
    ) -> list[types.Part]:
        response_parts = executor.execute(function_calls)
        response_parts = [
            types.Part.from_function_response(
                name=fc_name,
                response=fc_response,
            )
            for fc_name, fc_response in response_parts
        ]
        # wait for some time so ui responds to all function calls
        time.sleep(1.0)
        screenshot_bytes = executor.screenshot()
        response_parts.append(
            types.Part.from_bytes(mime_type="image/png", data=screenshot_bytes)
        )
        return response_parts

    def add_extra_messages(
        self, turn_count: int, response_parts: list[types.Part]
    ) -> None:
        # Inject turns-remaining warning if approaching budget
        remaining = self.max_turns - turn_count
        if 0 < remaining <= 5:
            warning = (
                f"WARNING: You have {remaining} turns left. "
                f"Wrap up your current work and finish the task NOW. "
                f"Call task_complete() with a summary of what you accomplished. "
                f"Do not start any new operations."
            )
            response_parts.append(types.Part.from_text(text=warning))
            print(f"  [!] Turn warning injected: {remaining} turns left")
        elif remaining == 0:
            warning = (
                "FINAL TURN. You MUST call task_complete() right now. "
                "Summarize what was accomplished and what failed."
            )
            response_parts.append(types.Part.from_text(text=warning))
            print(f"  [!] FINAL TURN warning injected")

    def get_and_validate_candidate(
        self, response: types.GenerateContentResponse
    ) -> Optional[types.Candidate]:
        if not response.candidates:
            termcolor.cprint(
                f"Response has no candidates... Retrying...",
                color="yellow",
            )
            # append a fresh message to alert the agent
            self.history.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text="The previous request returned no response. "
                            "Please look at the most recent screenshot and "
                            "continue with the next action."
                        ),
                    ],
                )
            )
            return

        candidate = response.candidates[0]
        if candidate and candidate.content:
            self.history.append(candidate.content)
        return candidate

    def clean_old_screenshots(self) -> None:
        """Remove old screenshots from history, keeping only the most recent.

        Walks backward through history and strips inline_data (images) from
        older turns to stay within context limits.
        """
        MAX_SCREENSHOTS = 2
        screenshot_count = 0
        for content in reversed(self.history):
            if content.role == "user" and content.parts:
                parts_to_remove = []
                for part in content.parts:
                    if part.inline_data is not None:
                        screenshot_count += 1
                        if screenshot_count > MAX_SCREENSHOTS:
                            parts_to_remove.append(part)
                for part in parts_to_remove:
                    content.parts.remove(part)

    def config(self) -> GenerateContentConfig:
        final_config = {
            "system_instruction": SYSTEM_INSTRUCTION,
            "temperature": 1,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
            "thinking_config": types.ThinkingConfig(include_thoughts=True),
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            **self._config,
        }
        return GenerateContentConfig(**final_config)

    def get_model_response(
        self, max_retries: int = 5, base_delay_s: int = 1
    ) -> types.GenerateContentResponse:
        configuration = self.config()
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=self.history,
                    config=configuration,
                )
                return response
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    termcolor.cprint("Rate limit (429). Stopping.", color="yellow")
                    raise
                print(e)
                if attempt < max_retries - 1:
                    delay = base_delay_s * (2**attempt)
                    termcolor.cprint(f"Retry in {delay}s...", color="yellow")
                    time.sleep(delay)
                else:
                    raise
        raise

    def get_text(self, candidate: Candidate) -> Optional[str]:
        if not candidate.content or not candidate.content.parts:
            return None
        text = [p.text for p in candidate.content.parts if p.text]
        return " ".join(text) or None

    def extract_function_calls(self, candidate: Candidate) -> list[FunctionCall]:
        if not candidate.content or not candidate.content.parts:
            return []
        return [p.function_call for p in candidate.content.parts if p.function_call]
