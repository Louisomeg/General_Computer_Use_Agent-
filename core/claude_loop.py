"""
Claude Computer Use Agentic Loop — alternative to Gemini-based loop.

Uses Anthropic's Claude with the computer_20250124 tool for vision-based
desktop interaction. Shares the same Executor and screenshot infrastructure
as the Gemini loop.

Usage:
    loop = ClaudeAgenticLoop()
    loop.agentic_loop("open freecad and create a cube", executor)
"""
import base64
import subprocess
import time
from typing import Optional, Callable, List

import anthropic
import termcolor

from core.executor import Executor
from core.freecad_functions import (
    system_click, system_hover, right_click, double_click,
    system_scroll, execute_freecad_macro,
)
from core.screenshot import capture_desktop_screenshot
from core.settings import (
    MODEL_SCREEN_WIDTH, MODEL_SCREEN_HEIGHT,
    SCREEN_WIDTH, SCREEN_HEIGHT,
    CLAUDE_SYSTEM_INSTRUCTION, CLAUDE_MODEL,
    TYPING_DELAY, CLICK_DELAY,
)

# Claude Computer Use tool version and beta flag
COMPUTER_TOOL_VERSION = "computer_20250124"
COMPUTER_USE_BETA = "computer-use-2025-01-24"


class ClaudeAgenticLoop:
    """Agentic loop using Claude's Computer Use capability.

    Same interface as AgenticLoop so agents can swap backends without
    code changes. The key differences:
    - Uses Anthropic API instead of Google Gemini
    - Claude's built-in computer tool handles mouse/keyboard
    - Coordinates are in screenshot pixels (not normalized 0-1000)
    - Screenshots are sent as base64 in tool results
    """

    def __init__(
        self,
        model_name: str = CLAUDE_MODEL,
        system_instruction: Optional[str] = None,
        screenshot_fn: Optional[Callable[[], bytes]] = None,
        max_turns: int = 0,
        finish_function_name: str = "task_complete",
        stage_budgets: Optional[List[dict]] = None,
        verify_before_complete: bool = False,
        max_output_tokens: int = 4096,
        # Ignored params for API compat with AgenticLoop
        **kwargs,
    ):
        self.client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
        self.model_name = model_name
        self.system_instruction = system_instruction or CLAUDE_SYSTEM_INSTRUCTION
        self.screenshot_fn = screenshot_fn or capture_desktop_screenshot
        self.max_turns = max_turns
        self.finish_function_name = finish_function_name
        self.max_output_tokens = max_output_tokens
        self._turn_count = 0

        # Stage budgeting (same as Gemini loop)
        self._verify_before_complete = verify_before_complete
        self._stage_budgets = stage_budgets or []
        self._stage_turns = 0
        self._current_stage_idx = 0
        self._stage_warning_sent = False
        self._verification_requested = False

    @property
    def turn_count(self):
        return self._turn_count

    # ── Stage budget (shared logic with Gemini loop) ─────────────────────

    def _check_stage_budget(self) -> Optional[str]:
        """Check if the current stage has exceeded its turn budget."""
        if not self._stage_budgets:
            return None
        if self._current_stage_idx >= len(self._stage_budgets):
            return None

        self._stage_turns += 1
        stage = self._stage_budgets[self._current_stage_idx]
        budget = stage["budget"]
        name = stage["name"]

        if self._stage_turns > budget and not self._stage_warning_sent:
            self._stage_warning_sent = True
            remaining_stages = self._stage_budgets[self._current_stage_idx + 1:]
            next_desc = ""
            if remaining_stages:
                next_desc = f" Move on to: {remaining_stages[0]['description']}"
            warning = (
                f"STAGE BUDGET EXCEEDED: You have spent {self._stage_turns} turns "
                f"on '{name}' (budget was {budget}).{next_desc} "
                f"Close the current operation NOW and proceed to the next step."
            )
            print(f"  [!] Stage '{name}' over budget ({self._stage_turns}/{budget})")
            return warning
        return None

    def advance_stage(self):
        """Manually advance to the next stage."""
        if self._current_stage_idx < len(self._stage_budgets):
            stage = self._stage_budgets[self._current_stage_idx]
            print(f"  [Stage] Completed '{stage['name']}' in {self._stage_turns} turns")
            self._current_stage_idx += 1
            self._stage_turns = 0
            self._stage_warning_sent = False

    # ── Tool definitions ─────────────────────────────────────────────────

    def _build_tools(self):
        """Build Claude tool definitions including computer use."""
        return [
            # Claude's built-in computer use tool
            {
                "type": COMPUTER_TOOL_VERSION,
                "name": "computer",
                "display_width_px": MODEL_SCREEN_WIDTH,
                "display_height_px": MODEL_SCREEN_HEIGHT,
            },
            # Custom: FreeCAD macro execution
            {
                "name": "execute_freecad_macro",
                "description": (
                    "Execute Python code directly in FreeCAD's Python console. "
                    "Use this for precision operations where GUI clicking would be "
                    "imprecise. Errors are captured and returned.\n\n"
                    "## CRITICAL RULES\n"
                    "1. Write ONE SMALL MACRO per call (one feature at a time).\n"
                    "2. After each macro, CHECK THE SCREENSHOT for errors.\n"
                    "3. NEVER guess face names. Find faces by position.\n\n"
                    "## CORRECT API (FreeCAD 1.0)\n"
                    "  import FreeCAD, Part, Sketcher\n"
                    "  doc = FreeCAD.activeDocument()\n"
                    "  body = doc.getObject('Body')\n\n"
                    "### Sketch on a standard plane\n"
                    "  sketch = body.newObject('Sketcher::SketchObject', 'MySketch')\n"
                    "  sketch.AttachmentSupport = [(doc.getObject('XY_Plane'), '')]\n"
                    "  sketch.MapMode = 'FlatFace'\n\n"
                    "### Pad (extrude a sketch)\n"
                    "  pad = body.newObject('PartDesign::Pad', 'Pad')\n"
                    "  pad.Profile = sketch\n"
                    "  pad.Length = 10.0\n"
                    "  doc.recompute()\n\n"
                    "### Pocket (cut into solid)\n"
                    "  pocket = body.newObject('PartDesign::Pocket', 'Pocket')\n"
                    "  pocket.Profile = sketch\n"
                    "  pocket.Type = 1  # ThroughAll\n"
                    "  doc.recompute()\n\n"
                    "ALWAYS call doc.recompute() at the end."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "FreeCAD Python code to execute.",
                        },
                    },
                    "required": ["code"],
                },
            },
            # Custom: task complete signal
            {
                "name": "task_complete",
                "description": (
                    "Call this when you have finished the design task or need to stop. "
                    "Include a brief summary of what was created or what went wrong."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Brief description of what was accomplished.",
                        },
                    },
                    "required": ["summary"],
                },
            },
        ]

    # ── Screenshot helper ────────────────────────────────────────────────

    def _screenshot_b64(self, raw_bytes: bytes = None) -> str:
        """Capture a screenshot and return as base64 string."""
        if raw_bytes is None:
            raw_bytes = self.screenshot_fn()
        return base64.standard_b64encode(raw_bytes).decode("utf-8")

    def _screenshot_content_block(self, raw_bytes: bytes = None) -> dict:
        """Build a Claude image content block from a screenshot."""
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": self._screenshot_b64(raw_bytes),
            },
        }

    # ── Computer action execution ────────────────────────────────────────

    def _map_coordinates(self, x: int, y: int) -> tuple[int, int]:
        """Map Claude's screenshot-pixel coordinates to actual screen pixels.

        Claude outputs coordinates in the screenshot's resolution
        (MODEL_SCREEN_WIDTH x MODEL_SCREEN_HEIGHT). We need to map these
        to the actual screen resolution for xdotool.
        """
        screen_x = int(x / MODEL_SCREEN_WIDTH * SCREEN_WIDTH)
        screen_y = int(y / MODEL_SCREEN_HEIGHT * SCREEN_HEIGHT)
        print(f"     Coords: claude({x}, {y}) -> screen({screen_x}, {screen_y})")
        return screen_x, screen_y

    def _execute_computer_action(self, action_input: dict) -> dict:
        """Execute a Claude computer tool action via xdotool.

        Handles: click, double_click, right_click, type, key,
                 screenshot, scroll_up, scroll_down, mouse_move, drag.
        """
        action = action_input.get("action", "")
        coordinate = action_input.get("coordinate")
        text = action_input.get("text", "")

        try:
            if action == "screenshot":
                # Just return a screenshot, no action needed
                return {"success": True}

            elif action == "click":
                if not coordinate:
                    return {"error": "click requires coordinate"}
                sx, sy = self._map_coordinates(coordinate[0], coordinate[1])
                return system_click(sx, sy)

            elif action == "double_click":
                if not coordinate:
                    return {"error": "double_click requires coordinate"}
                sx, sy = self._map_coordinates(coordinate[0], coordinate[1])
                return double_click(sx, sy)

            elif action == "right_click":
                if not coordinate:
                    return {"error": "right_click requires coordinate"}
                sx, sy = self._map_coordinates(coordinate[0], coordinate[1])
                return right_click(sx, sy)

            elif action == "mouse_move":
                if not coordinate:
                    return {"error": "mouse_move requires coordinate"}
                sx, sy = self._map_coordinates(coordinate[0], coordinate[1])
                from core.freecad_functions import system_hover
                return system_hover(sx, sy)

            elif action == "type":
                if not text:
                    return {"error": "type requires text"}
                subprocess.run(
                    ["xdotool", "type", "--delay", str(TYPING_DELAY), text],
                    check=True,
                )
                return {"success": True}

            elif action == "key":
                if not text:
                    return {"error": "key requires text"}
                # Claude sends key combos like "ctrl+s", "Return", etc.
                # xdotool expects the same format
                subprocess.run(
                    ["xdotool", "key", "--clearmodifiers", text],
                    check=True,
                )
                return {"success": True}

            elif action in ("scroll_up", "scroll_down"):
                direction = "up" if action == "scroll_up" else "down"
                if coordinate:
                    sx, sy = self._map_coordinates(coordinate[0], coordinate[1])
                else:
                    sx, sy = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2
                clicks = action_input.get("amount", 3)
                return system_scroll(sx, sy, direction, clicks)

            elif action == "drag":
                start = action_input.get("start_coordinate", coordinate)
                end = action_input.get("end_coordinate")
                if not start or not end:
                    return {"error": "drag requires start and end coordinates"}
                sx1, sy1 = self._map_coordinates(start[0], start[1])
                sx2, sy2 = self._map_coordinates(end[0], end[1])
                subprocess.run(
                    ["xdotool", "mousemove", str(sx1), str(sy1)],
                    check=True,
                )
                subprocess.run(["xdotool", "mousedown", "1"], check=True)
                time.sleep(0.1)
                subprocess.run(
                    ["xdotool", "mousemove", "--sync", str(sx2), str(sy2)],
                    check=True,
                )
                subprocess.run(["xdotool", "mouseup", "1"], check=True)
                return {"success": True}

            elif action == "wait":
                time.sleep(5)
                return {"success": True}

            else:
                return {"error": f"Unknown computer action: {action}"}

        except subprocess.CalledProcessError as e:
            return {"error": f"xdotool failed: {e}"}

    # ── Main loop ────────────────────────────────────────────────────────

    def agentic_loop(
        self, prompt: str, executor: Executor, images: list[bytes] = None,
    ) -> str:
        """Run the agentic loop: screenshot -> Claude -> execute -> repeat.

        Same interface as AgenticLoop.agentic_loop() for drop-in swapping.

        Args:
            prompt: Initial text prompt for the model.
            executor: Desktop executor (used only for task_complete routing).
            images: Optional demonstration screenshots.

        Returns:
            "completed", "max_turns", "api_error", or "empty_responses"
        """
        self._turn_count = 0
        self._verification_requested = False
        self._text_only_retries = 0
        self._recent_actions = []
        empty_retries = 0

        # Build initial message with prompt + optional demo images + screenshot
        initial_content = [{"type": "text", "text": prompt}]
        if images:
            for img_bytes in images:
                initial_content.append(self._screenshot_content_block(img_bytes))
        screenshot_bytes = self.screenshot_fn()
        initial_content.append(self._screenshot_content_block(screenshot_bytes))

        messages = [{"role": "user", "content": initial_content}]
        tools = self._build_tools()

        while True:
            self._turn_count += 1
            if self.max_turns > 0 and self._turn_count > self.max_turns:
                termcolor.cprint(
                    f"Max turns ({self.max_turns}) reached.", color="yellow"
                )
                return "max_turns"

            # ── Get Claude response ──────────────────────────────────────
            try:
                response = self.client.beta.messages.create(
                    model=self.model_name,
                    max_tokens=self.max_output_tokens,
                    system=self.system_instruction,
                    tools=tools,
                    messages=messages,
                    betas=[COMPUTER_USE_BETA],
                )
            except anthropic.APIError as e:
                termcolor.cprint(f"Claude API error: {e}", color="red")
                if "rate_limit" in str(e).lower() or "429" in str(e):
                    return "api_error"
                empty_retries += 1
                if empty_retries >= 3:
                    return "api_error"
                time.sleep(2 ** empty_retries)
                continue

            # Reset retry counter on success
            empty_retries = 0

            # Parse response content blocks
            tool_uses = []
            reasoning_parts = []

            for block in response.content:
                if block.type == "text":
                    reasoning_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            reasoning = " ".join(reasoning_parts) if reasoning_parts else None

            # Print turn info
            turn_info = f"[Turn {self._turn_count}"
            if self.max_turns > 0:
                turn_info += f"/{self.max_turns}"
            turn_info += f"] {len(tool_uses)} action(s)"
            if reasoning:
                short = reasoning[:150] + "..." if len(reasoning) > 150 else reasoning
                turn_info += f" | {short}"
            print(turn_info)

            # No tool uses — nudge or stop
            if not tool_uses:
                self._text_only_retries += 1
                if self._text_only_retries >= 3:
                    print(f"Agent Loop Complete (no actions after 3 nudges)")
                    return "no_actions"
                termcolor.cprint(
                    f"Text-only response ({self._text_only_retries}/3). Nudging...",
                    color="yellow",
                )
                messages.append({"role": "assistant", "content": response.content})
                screenshot_bytes = self.screenshot_fn()
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": (
                            "STOP deliberating. You MUST use a tool NOW. "
                            "Pick the single best action and execute it."
                        )},
                        self._screenshot_content_block(screenshot_bytes),
                    ],
                })
                self._turn_count -= 1
                continue

            self._text_only_retries = 0

            # ── Add assistant message to history ─────────────────────────
            messages.append({"role": "assistant", "content": response.content})

            # ── Execute tool uses ────────────────────────────────────────
            should_stop = False
            tool_results = []

            for tool_use in tool_uses:
                tool_name = tool_use.name
                tool_id = tool_use.id
                tool_input = tool_use.input

                print(f"  -> Executing: {tool_name}({_summarize_input(tool_input)})")

                # ── Verification gate for task_complete ──────────────
                if (self._verify_before_complete
                        and tool_name == self.finish_function_name
                        and not self._verification_requested):
                    self._verification_requested = True
                    print("  [!] task_complete intercepted — requesting verification")
                    screenshot_bytes = self.screenshot_fn()
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": [
                            {"type": "text", "text": (
                                "BEFORE completing: Look at the screenshot carefully. "
                                "Does the 3D model match the task requirements? "
                                "Check: (1) correct shape, (2) all holes present, "
                                "(3) dimensions look right, (4) no error dialogs. "
                                "If OK, call task_complete() again. If wrong, fix it."
                            )},
                            self._screenshot_content_block(screenshot_bytes),
                        ],
                    })
                    continue

                # ── task_complete (accepted) ─────────────────────────
                if tool_name == self.finish_function_name:
                    summary = tool_input.get("summary", "Task completed")
                    print(f"  [Task Complete] {summary}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": [{"type": "text", "text": "Task complete acknowledged."}],
                    })
                    should_stop = True
                    continue

                # ── Computer tool ────────────────────────────────────
                if tool_name == "computer":
                    result = self._execute_computer_action(tool_input)
                    time.sleep(0.5)  # UI settling
                    screenshot_bytes = self.screenshot_fn()
                    content = [self._screenshot_content_block(screenshot_bytes)]
                    if result.get("error"):
                        content.insert(0, {
                            "type": "text",
                            "text": f"Error: {result['error']}",
                        })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": content,
                    })

                    # Track for repetition detection
                    action = tool_input.get("action", "")
                    coord = tool_input.get("coordinate")
                    if coord:
                        action_key = f"{action}({coord[0]},{coord[1]})"
                    else:
                        action_key = f"{action}({tool_input.get('text', '')[:20]})"
                    self._recent_actions.append(action_key)
                    continue

                # ── execute_freecad_macro ────────────────────────────
                if tool_name == "execute_freecad_macro":
                    code = tool_input.get("code", "")
                    if not code:
                        result = {"error": "No code provided"}
                    else:
                        result = execute_freecad_macro(code)
                    time.sleep(0.5)
                    screenshot_bytes = self.screenshot_fn()
                    content = [self._screenshot_content_block(screenshot_bytes)]
                    if result.get("error"):
                        content.insert(0, {
                            "type": "text",
                            "text": f"Macro error: {result['error']}",
                        })
                    elif result.get("warning"):
                        content.insert(0, {
                            "type": "text",
                            "text": f"Warning: {result['warning']}",
                        })
                    else:
                        content.insert(0, {
                            "type": "text", "text": "Macro executed successfully.",
                        })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": content,
                    })
                    continue

                # ── Unknown tool ─────────────────────────────────────
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                    "is_error": True,
                })

            # ── Append tool results to messages ──────────────────────────
            if tool_results:
                # Inject warnings into the last tool result
                warnings = []
                if self.max_turns > 0:
                    remaining = self.max_turns - self._turn_count
                    if 0 < remaining <= 5:
                        warnings.append(
                            f"WARNING: {remaining} turns left. "
                            f"Wrap up and call {self.finish_function_name}()."
                        )
                    elif remaining == 0:
                        warnings.append(
                            f"FINAL TURN. Call {self.finish_function_name}() NOW."
                        )

                stage_warning = self._check_stage_budget()
                if stage_warning:
                    warnings.append(stage_warning)

                if warnings:
                    tool_results[-1]["content"].append({
                        "type": "text",
                        "text": "\n".join(warnings),
                    })

                messages.append({"role": "user", "content": tool_results})

            if should_stop:
                termcolor.cprint("Task complete.", color="green")
                return "completed"

            # ── Repetitive action detection ──────────────────────────────
            self._recent_actions = self._recent_actions[-8:]
            is_stuck = False
            stuck_desc = ""

            if len(self._recent_actions) >= 4:
                last_4 = self._recent_actions[-4:]
                if len(set(last_4)) == 1:
                    is_stuck = True
                    stuck_desc = f"same action 4x: {last_4[0]}"

            if not is_stuck and len(self._recent_actions) >= 6:
                pair = tuple(self._recent_actions[-2:])
                prev_pairs = [
                    tuple(self._recent_actions[-4:-2]),
                    tuple(self._recent_actions[-6:-4]),
                ]
                if all(p == pair for p in prev_pairs):
                    is_stuck = True
                    stuck_desc = f"2-step cycle 3x: {pair[0]} -> {pair[1]}"

            if is_stuck:
                termcolor.cprint(f"  [!] STUCK: {stuck_desc}", color="red")
                # Add stuck warning to the last message
                if messages and messages[-1]["role"] == "user":
                    content = messages[-1]["content"]
                    if isinstance(content, list):
                        content.append({
                            "type": "text",
                            "text": (
                                f"STOP! You are stuck ({stuck_desc}). "
                                f"Try a COMPLETELY DIFFERENT approach. "
                                f"If stuck, call task_complete(summary='FAILED: stuck')."
                            ),
                        })
                self._recent_actions.clear()

            # ── Trim old messages to save context ────────────────────────
            # Keep first message + last 20 messages (10 turns)
            if len(messages) > 22:
                messages = [messages[0]] + messages[-20:]

        return "completed"


def _summarize_input(tool_input: dict) -> str:
    """Create a short summary of tool input for logging."""
    if not tool_input:
        return ""
    parts = []
    for key, value in tool_input.items():
        if key == "code":
            parts.append(f"code=...{len(str(value))}chars")
        elif isinstance(value, str) and len(value) > 30:
            parts.append(f"{key}='{value[:30]}...'")
        else:
            parts.append(f"{key}={value}")
    return ", ".join(parts)
