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
from typing import Optional, Callable, List, Literal, Any

import termcolor
from google.genai import Client, types
from google.genai.types import Candidate, GenerateContentConfig

from core.custom_tools import get_custom_declarations
from core.executor import Executor
from core.screenshot import capture_desktop_screenshot
from core.settings import SYSTEM_INSTRUCTION

# Keep only the N most recent screenshots in conversation history.
# Older screenshots are stripped to save context window space.
MAX_SCREENSHOTS = 2


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
        model_name: str = "gemini-3.1-pro-preview",
        system_instruction: Optional[str] = None,
        screenshot_fn: Optional[Callable[[], bytes]] = None,
        extra_declarations: Optional[List[types.FunctionDeclaration]] = None,
        max_turns: int = 0,
        use_browser_environment: bool = False,
        custom_declarations: Optional[List[types.FunctionDeclaration]] = None,
    ):
        self.client = client
        self.model_name = model_name
        self.system_instruction = system_instruction or SYSTEM_INSTRUCTION
        self.screenshot_fn = screenshot_fn or capture_desktop_screenshot
        self.extra_declarations = extra_declarations or []
        self.max_turns = max_turns
        self.use_browser_environment = use_browser_environment
        # If custom_declarations is provided, it replaces get_custom_declarations().
        # This lets agents pass filtered shortcut sets to reduce per-turn overhead.
        self.custom_declarations = custom_declarations
        self._turn_count = 0
        self._empty_response_retries = 0
        self._cached_config = self._build_config()

    @property
    def turn_count(self):
        return self._turn_count

    # ── Safety acknowledgement (from Google reference code) ──────────────

    def _handle_safety_decision(
        self, safety: dict
    ) -> Literal["CONTINUE", "TERMINATE"]:
        """Handle Gemini's safety_decision on a function call.

        For automated agents we auto-confirm safe actions.
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

    # ── Screenshot management ────────────────────────────────────────────

    def _clean_old_screenshots(self, history: list):
        """Remove old screenshots from history, keeping only the most recent.

        Walks backward through history and strips inline_data (images) from
        older turns to stay within context limits.
        """
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

    # ── Main loop ────────────────────────────────────────────────────────

    def agentic_loop(self, prompt: str, executor: Executor):
        """Run the agentic loop: screenshot → model → execute → repeat.

        Screenshot delivery follows Google's reference implementation:
        1. Initial screenshot is bundled WITH the prompt
        2. Subsequent screenshots are bundled WITH function responses
        This matches the pattern the model was trained on.
        """
        self._turn_count = 0  # Reset per call so each invocation gets a fresh budget
        self._empty_response_retries = 0  # Reset retry counter for fresh run

        # ── Initial turn: prompt + screenshot ────────────────────────────
        screenshot_bytes = self.screenshot_fn()
        history = [
            types.Content(role='user', parts=[
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(mime_type='image/png', data=screenshot_bytes),
            ])
        ]

        while True:
            self._turn_count += 1
            if self.max_turns > 0 and self._turn_count > self.max_turns:
                termcolor.cprint(f"Max turns ({self.max_turns}) reached.", color="yellow")
                break

            # ── Get model response ───────────────────────────────────────
            try:
                response = self.get_model_response(history)
            except Exception as e:
                print(e)
                break

            # Handle empty responses (no candidates) — retry with a fresh
            # screenshot instead of crashing.  This can happen transiently
            # due to content-safety filters or API hiccups.
            if not response.candidates:
                self._empty_response_retries += 1
                if self._empty_response_retries >= 3:
                    termcolor.cprint(
                        "Empty response 3 times in a row — stopping.",
                        color="red",
                    )
                    break
                termcolor.cprint(
                    f"Response has no candidates (attempt "
                    f"{self._empty_response_retries}/3). "
                    f"Retrying with fresh screenshot...",
                    color="yellow",
                )
                time.sleep(2)  # Brief pause before retry
                screenshot_bytes = self.screenshot_fn()
                history.append(types.Content(role='user', parts=[
                    types.Part.from_text(
                        text="The previous request returned no response. "
                             "Please look at the current screenshot and "
                             "continue with the next action."
                    ),
                    types.Part.from_bytes(
                        mime_type='image/png', data=screenshot_bytes
                    ),
                ]))
                continue  # Re-enter the while loop (counts as a new turn)

            # Reset empty-response counter on any successful response
            self._empty_response_retries = 0

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

            # Handle malformed function calls — retry without breaking
            if (not function_calls and not reasoning
                    and candidate.finish_reason == types.FinishReason.MALFORMED_FUNCTION_CALL):
                # Re-send the last screenshot so the model can try again
                screenshot_bytes = self.screenshot_fn()
                history.append(types.Content(role='user', parts=[
                    types.Part.from_bytes(mime_type='image/png', data=screenshot_bytes),
                ]))
                continue

            # No function calls → model is done talking
            if not function_calls:
                print(f"Agent Loop Complete: {reasoning}")
                break

            # ── Execute function calls ───────────────────────────────────
            should_stop = False
            response_parts = []

            for fc in function_calls:
                extra_fields = {}

                # Check for safety_decision in function call args.
                # The API may use snake_case or camelCase depending on
                # the transport layer, so check both.
                safety = None
                if fc.args:
                    safety = (fc.args.get("safety_decision")
                              or fc.args.get("safetyDecision"))
                if safety:
                    decision = self._handle_safety_decision(
                        safety if isinstance(safety, dict) else {"decision": str(safety)}
                    )
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
                    if fc_response.get("status") in ("research_complete", "task_complete"):
                        should_stop = True

            # ── Build the response content: func responses + screenshot ──
            # This matches Google's reference implementation pattern:
            # function responses and the resulting screenshot go in ONE message.
            if response_parts:
                # Wait for the UI to settle before capturing the screenshot.
                # FreeCAD is a heavy Qt application and needs time after actions
                # (creating bodies, entering sketcher, opening dialogs) before
                # the screen accurately reflects the new state.
                time.sleep(1.0)
                # Capture screenshot AFTER executing all actions for this turn
                screenshot_bytes = self.screenshot_fn()
                response_parts.append(
                    types.Part.from_bytes(mime_type='image/png', data=screenshot_bytes)
                )

                # Inject turns-remaining warning if approaching budget
                if self.max_turns > 0:
                    remaining = self.max_turns - self._turn_count
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

                history.append(types.Content(role='user', parts=response_parts))

            # Clean old screenshots to save context window
            self._clean_old_screenshots(history)

            if should_stop:
                termcolor.cprint("Task complete.", color="green")
                break

    def config(self):
        """Return the cached GenerateContentConfig (identical across turns)."""
        return self._cached_config

    def _build_config(self):
        """Build the GenerateContentConfig once at init time."""
        base = self.custom_declarations if self.custom_declarations is not None else get_custom_declarations()
        all_declarations = base + self.extra_declarations
        if self.use_browser_environment:
            cu_tool = types.Tool(
                computer_use=types.ComputerUse(
                    environment=types.Environment.ENVIRONMENT_BROWSER,
                ),
            )
        else:
            cu_tool = types.Tool(computer_use=types.ComputerUse(
                excluded_predefined_functions=[
                    "navigate", "go_back", "go_forward",
                    "search", "open_web_browser",
                ],
            ))

        return GenerateContentConfig(
            system_instruction=self.system_instruction,
            temperature=1,
            top_p=0.95,
            top_k=40,
            max_output_tokens=8192,
            tools=[cu_tool, types.Tool(function_declarations=all_declarations)],
            thinking_config=types.ThinkingConfig(include_thoughts=True),
            # Highest available resolution for computer use screenshots.
            media_resolution=getattr(
                types.MediaResolution, "MEDIA_RESOLUTION_ULTRA_HIGH",
                types.MediaResolution.MEDIA_RESOLUTION_HIGH,
            ),
            # Disable AFC — we handle function calls manually in the agentic loop.
            # This suppresses the "Tools at indices [1] are not compatible with AFC" warning.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
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
                # 400 INVALID_ARGUMENT is a permanent error (e.g. malformed
                # history, missing safety_acknowledgement).  Retrying won't help.
                if "400" in error_str and "INVALID_ARGUMENT" in error_str:
                    termcolor.cprint(f"Permanent API error (400): {error_str[:200]}", color="red")
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
        text = [p.text for p in candidate.content.parts
                if p.text and not getattr(p, "thought", False)]
        return " ".join(text) or None

    def extract_function_calls(self, candidate: Candidate):
        if not candidate.content or not candidate.content.parts:
            return []
        return [p.function_call for p in candidate.content.parts if p.function_call]
