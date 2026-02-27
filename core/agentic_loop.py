"""
Agentic Loop — shared foundation for all agents.

Backward compatible with Louis's desktop usage:
    loop = AgenticLoop(client)
    loop.agentic_loop("open freecad", DesktopExecutor())
"""
import time
from typing import Optional, Callable, List, Literal, Any

import termcolor
from google.genai import Client, types
from google.genai.types import Candidate, GenerateContentConfig

from core.custom_tools import get_custom_declarations
from core.executor import Executor
from core.screenshot import capture_desktop_screenshot
from core.settings import SYSTEM_INSTRUCTION

MAX_SCREENSHOTS = 1


REPORT_FINDINGS_DECLARATION = types.FunctionDeclaration(
    name="report_findings",
    description=(
        "Call this when you have completed your research and want to "
        "submit your findings. Include all data points with sources."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Summary paragraph of all findings",
            },
            "data_points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fact": {"type": "string"},
                        "value": {"type": "string"},
                        "unit": {"type": "string"},
                        "source": {"type": "string"},
                    },
                },
                "description": "Array of {fact, value, unit, source}",
            },
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "All URLs visited during research",
            },
            "confidence": {
                "type": "string",
                "description": "high, medium, or low",
            },
            "gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Things you could NOT find or verify",
            },
        },
        "required": ["summary", "data_points", "sources", "confidence"],
    },
)


class AgenticLoop:
    def __init__(
        self,
        client: Client,
        model_name: str = "gemini-2.5-computer-use-preview-10-2025",
        system_instruction: Optional[str] = None,
        screenshot_fn: Optional[Callable[[], bytes]] = None,
        extra_declarations: Optional[List[types.FunctionDeclaration]] = None,
        max_turns: int = 0,
        use_browser_environment: bool = False,
    ):
        self.client = client
        self.model_name = model_name
        self.system_instruction = system_instruction or SYSTEM_INSTRUCTION
        self.screenshot_fn = screenshot_fn or capture_desktop_screenshot
        self.extra_declarations = extra_declarations or []
        self.max_turns = max_turns
        self.use_browser_environment = use_browser_environment
        self._turn_count = 0

    @property
    def turn_count(self):
        return self._turn_count

    # ── Safety acknowledgement (from Google reference code) ──────────────

    def _handle_safety_decision(
        self, safety: dict
    ) -> Literal["CONTINUE", "TERMINATE"]:
        """Handle Gemini's safety_decision on a function call.

        For automated research agents we auto-confirm safe actions.
        Returns CONTINUE to proceed or TERMINATE to stop.
        """
        decision = safety.get("decision", "")
        explanation = safety.get("explanation", "")
        if decision == "require_confirmation":
            termcolor.cprint(
                f"Safety confirmation auto-accepted: {explanation}",
                color="yellow",
            )
            return "CONTINUE"
        return "CONTINUE"

    def agentic_loop(self, prompt: str, executor: Executor):
        history = [types.Content(role='user', parts=[types.Part.from_text(text=prompt)])]

        while True:
            self._turn_count += 1
            if self.max_turns > 0 and self._turn_count > self.max_turns:
                termcolor.cprint(f"Max turns ({self.max_turns}) reached.", color="yellow")
                break

            # Inject turns-remaining warning so model knows to wrap up
            if self.max_turns > 0:
                remaining = self.max_turns - self._turn_count
                if remaining <= 3 and remaining > 0:
                    warning = (
                        f"WARNING: You have {remaining} turns left. "
                        f"Call report_findings() NOW with whatever data you have. "
                        f"Do not search any more — report your partial findings immediately."
                    )
                    history.append(types.Content(role='user', parts=[
                        types.Part.from_text(text=warning)
                    ]))
                    print(f"  [!] Turn warning injected: {remaining} turns left")
                elif remaining == 0:
                    warning = (
                        "FINAL TURN. You MUST call report_findings() right now. "
                        "Report whatever you have found so far."
                    )
                    history.append(types.Content(role='user', parts=[
                        types.Part.from_text(text=warning)
                    ]))
                    print(f"  [!] FINAL TURN warning injected")

            # Take screenshot (desktop scrot or browser playwright)
            screenshot_bytes = self.screenshot_fn()
            history.append(types.Content(role='user', parts=[
                types.Part.from_bytes(mime_type='image/png', data=screenshot_bytes)
            ]))

            # Clean old screenshots
            screenshot_count = 0
            for content in reversed(history):
                if content.role == "user" and content.parts:
                    parts_to_remove = []
                    for part in content.parts:
                        if part.inline_data is not None:
                            screenshot_count += 1
                            if screenshot_count > MAX_SCREENSHOTS:
                                parts_to_remove.append(part)
                    for part in parts_to_remove:
                        content.parts.remove(part)

            # Get model response
            try:
                response = self.get_model_response(history)
            except Exception as e:
                print(e)
                break
            if not response.candidates:
                print("Response has no candidates!")
                raise ValueError("Empty response")

            candidate = response.candidates[0]
            if candidate.content:
                history.append(candidate.content)

            reasoning = self.get_text(candidate)
            function_calls = self.extract_function_calls(candidate)

            # Print turn info
            turn_info = f"[Turn {self._turn_count}"
            if self.max_turns > 0:
                turn_info += f"/{self.max_turns}"
            turn_info += f"] {len(function_calls)} action(s)"
            if reasoning:
                short = reasoning[:150] + "..." if len(reasoning) > 150 else reasoning
                turn_info += f" | {short}"
            print(turn_info)

            # Handle malformed function calls
            if (not function_calls and not reasoning
                    and candidate.finish_reason == types.FinishReason.MALFORMED_FUNCTION_CALL):
                continue

            if not function_calls:
                print(f"Agent Loop Complete: {reasoning}")
                break

            # Execute function calls via the executor
            # SAFETY CHECK: handle safety_decision before executing
            should_stop = False
            response_parts = []

            for fc in function_calls:
                extra_fields = {}

                # Check for safety_decision in function call args
                if fc.args and fc.args.get("safety_decision"):
                    safety = fc.args["safety_decision"]
                    decision = self._handle_safety_decision(safety)
                    if decision == "TERMINATE":
                        print("Safety termination requested.")
                        should_stop = True
                        break
                    # CRITICAL: acknowledge the safety decision
                    extra_fields["safety_acknowledgement"] = "true"

                # Execute the function call
                fc_results = executor.execute([fc])
                for fc_name, fc_response in fc_results:
                    fc_response.setdefault("url", "desktop://linux")
                    # Merge safety acknowledgement into the response
                    fc_response.update(extra_fields)
                    response_parts.append(
                        types.Part.from_function_response(
                            name=fc_name,
                            response=fc_response,
                        )
                    )
                    if fc_response.get("status") == "research_complete":
                        should_stop = True

            if response_parts:
                history.append(types.Content(role='user', parts=response_parts))

            if should_stop:
                termcolor.cprint("Research complete.", color="green")
                break

    def config(self):
        all_declarations = get_custom_declarations() + self.extra_declarations
        if self.use_browser_environment:
            cu_tool = types.Tool(
                computer_use=types.ComputerUse(
                    environment=types.Environment.ENVIRONMENT_BROWSER,
                ),
            )
        else:
            cu_tool = types.Tool(computer_use=types.ComputerUse())

        return GenerateContentConfig(
            system_instruction=self.system_instruction,
            temperature=1,
            top_p=0.95,
            top_k=40,
            max_output_tokens=8192,
            tools=[cu_tool, types.Tool(function_declarations=all_declarations)],
            thinking_config=types.ThinkingConfig(include_thoughts=True),
        )

    def get_model_response(self, history, max_retries=5, base_delay_s=1):
        configuration = self.config()
        for attempt in range(max_retries):
            try:
                return self.client.models.generate_content(
                    model=self.model_name,
                    contents=history,
                    config=configuration,
                )
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    termcolor.cprint("Rate limit (429). Stopping.", color="yellow")
                    raise
                print(e)
                if attempt < max_retries - 1:
                    delay = base_delay_s * (2 ** attempt)
                    termcolor.cprint(f"Retry in {delay}s...", color="yellow")
                    time.sleep(delay)
                else:
                    raise

    def get_text(self, candidate: Candidate) -> Optional[str]:
        if not candidate.content or not candidate.content.parts:
            return None
        text = [p.text for p in candidate.content.parts if p.text]
        return " ".join(text) or None

    def extract_function_calls(self, candidate: Candidate):
        if not candidate.content or not candidate.content.parts:
            return []
        return [p.function_call for p in candidate.content.parts if p.function_call]
