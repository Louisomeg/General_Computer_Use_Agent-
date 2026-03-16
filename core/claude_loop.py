"""
Claude Computer Use Agentic Loop — drop-in alternative to the Gemini-based loop.

Uses Anthropic's Claude computer use API (computer_20250124) to control the
desktop via xdotool. Same interface as AgenticLoop for easy swapping.

Claude CU uses actual pixel coordinates (not 0-1000 normalized), so we send
screenshots at the real screen resolution and execute xdotool directly.
"""

import os
import time
import base64
import subprocess

import termcolor

from core.settings import (
    SCREEN_WIDTH, SCREEN_HEIGHT, SCREENSHOT_PATH,
    ACTION_DELAY, TYPING_DELAY, CLICK_DELAY,
)


# Key name mapping: Claude sends X11-style names but some need normalization
_KEY_ALIASES = {
    "Return": "Return",
    "enter": "Return",
    "Enter": "Return",
    "space": "space",
    "Space": "space",
    "BackSpace": "BackSpace",
    "backspace": "BackSpace",
    "Tab": "Tab",
    "tab": "Tab",
    "Escape": "Escape",
    "escape": "Escape",
    "Delete": "Delete",
    "delete": "Delete",
    "Home": "Home",
    "End": "End",
    "Page_Up": "Page_Up",
    "Page_Down": "Page_Down",
    "Up": "Up",
    "Down": "Down",
    "Left": "Left",
    "Right": "Right",
    "super": "Super_L",
    "Super_L": "Super_L",
}


def _normalize_key(key: str) -> str:
    """Normalize a key name for xdotool."""
    return _KEY_ALIASES.get(key.strip(), key.strip())


def _normalize_keys(keys: str) -> str:
    """Normalize a key combo like 'ctrl+a' or 'Return' for xdotool."""
    parts = keys.split("+")
    return "+".join(_normalize_key(p) for p in parts)


def _capture_screenshot_raw() -> bytes:
    """Capture screenshot at native resolution (no resize for Claude)."""
    subprocess.run(["scrot", SCREENSHOT_PATH, "-o"], check=True)
    with open(SCREENSHOT_PATH, "rb") as f:
        return f.read()


class ClaudeAgenticLoop:
    """Agentic loop using Claude's computer use capability."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        system_instruction: str = "",
        max_turns: int = 120,
        max_output_tokens: int = 4096,
        finish_function_name: str = "task_complete",
    ):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic package required. Install with: pip install anthropic"
            )

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable not set. "
                "Export it before running: export ANTHROPIC_API_KEY=sk-ant-..."
            )

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.system_instruction = system_instruction
        self.max_turns = max_turns
        self.max_output_tokens = max_output_tokens
        self.finish_function_name = finish_function_name
        self._turn_count = 0

    @property
    def turn_count(self):
        return self._turn_count

    def _screenshot_b64(self) -> str:
        """Capture screenshot and return as base64 string."""
        img_bytes = _capture_screenshot_raw()
        return base64.standard_b64encode(img_bytes).decode("utf-8")

    def _execute_action(self, action: str, params: dict) -> str:
        """Execute a computer use action via xdotool."""
        coord = params.get("coordinate", [0, 0])
        x, y = int(coord[0]), int(coord[1])

        if action == "screenshot":
            return "screenshot"

        elif action in ("left_click", "click"):
            subprocess.run(
                f"xdotool mousemove --sync {x} {y} && xdotool click 1",
                shell=True, timeout=5,
            )
            print(f"  -> click({x}, {y})")
            time.sleep(CLICK_DELAY)

        elif action == "double_click":
            subprocess.run(
                f"xdotool mousemove --sync {x} {y} && "
                f"xdotool click --repeat 2 --delay 100 1",
                shell=True, timeout=5,
            )
            print(f"  -> double_click({x}, {y})")
            time.sleep(CLICK_DELAY)

        elif action == "right_click":
            subprocess.run(
                f"xdotool mousemove --sync {x} {y} && xdotool click 3",
                shell=True, timeout=5,
            )
            print(f"  -> right_click({x}, {y})")
            time.sleep(CLICK_DELAY)

        elif action == "middle_click":
            subprocess.run(
                f"xdotool mousemove --sync {x} {y} && xdotool click 2",
                shell=True, timeout=5,
            )
            print(f"  -> middle_click({x}, {y})")
            time.sleep(CLICK_DELAY)

        elif action == "type":
            text = params.get("text", "")
            escaped = text.replace("'", "'\\''")
            subprocess.run(
                f"xdotool type --delay {TYPING_DELAY} '{escaped}'",
                shell=True, timeout=30,
            )
            print(f"  -> type('{text[:50]}')")

        elif action == "key":
            key = _normalize_keys(params.get("text", ""))
            subprocess.run(
                f"xdotool key {key}",
                shell=True, timeout=5,
            )
            print(f"  -> key({key})")

        elif action == "scroll":
            direction = params.get("direction", "down")
            amount = params.get("amount", 3)
            btn = 5 if direction == "down" else 4
            subprocess.run(
                f"xdotool mousemove --sync {x} {y}",
                shell=True, timeout=5,
            )
            for _ in range(amount):
                subprocess.run(f"xdotool click {btn}", shell=True, timeout=5)
            print(f"  -> scroll({direction}, {amount}) at ({x}, {y})")

        elif action == "mouse_move":
            subprocess.run(
                f"xdotool mousemove --sync {x} {y}",
                shell=True, timeout=5,
            )
            print(f"  -> mouse_move({x}, {y})")

        elif action == "left_click_drag":
            start = params.get("start_coordinate", [0, 0])
            sx, sy = int(start[0]), int(start[1])
            subprocess.run(
                f"xdotool mousemove --sync {sx} {sy} && "
                f"xdotool mousedown 1 && "
                f"xdotool mousemove --sync {x} {y} && "
                f"xdotool mouseup 1",
                shell=True, timeout=10,
            )
            print(f"  -> drag({sx},{sy} -> {x},{y})")
            time.sleep(CLICK_DELAY)

        elif action == "cursor_position":
            result = subprocess.run(
                "xdotool getmouselocation",
                shell=True, capture_output=True, text=True, timeout=5,
            )
            print(f"  -> cursor_position: {result.stdout.strip()}")

        elif action == "wait":
            time.sleep(5)
            print(f"  -> wait(5s)")

        else:
            print(f"  -> Unknown action: {action}")

        time.sleep(ACTION_DELAY)
        return "action_executed"

    def agentic_loop(
        self, prompt: str, executor=None, images: list = None,
    ) -> str:
        """Run the Claude computer use agentic loop.

        Args:
            prompt: Task description for the agent.
            executor: Unused (kept for interface compatibility with Gemini loop).
            images: Optional demo images (unused for now).

        Returns:
            "completed", "max_turns", or "api_error"
        """
        self._turn_count = 0
        text_only_retries = 0

        # Tools: computer use + task_complete
        tools = [
            {
                "type": "computer_20250124",
                "name": "computer",
                "display_width_px": SCREEN_WIDTH,
                "display_height_px": SCREEN_HEIGHT,
                "display_number": 0,
            },
            {
                "name": self.finish_function_name,
                "description": (
                    "Call this when you have finished the design task or "
                    "when you need to stop. Include a brief summary of "
                    "what was created or what went wrong."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Brief summary of what was accomplished",
                        }
                    },
                    "required": ["summary"],
                },
            },
        ]

        # Initial message: prompt + screenshot
        screenshot_b64 = self._screenshot_b64()
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64,
                        },
                    },
                ],
            }
        ]

        while True:
            self._turn_count += 1
            if self.max_turns > 0 and self._turn_count > self.max_turns:
                termcolor.cprint(
                    f"Max turns ({self.max_turns}) reached.", color="yellow"
                )
                return "max_turns"

            # Call Claude
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_output_tokens,
                    system=self.system_instruction,
                    tools=tools,
                    messages=messages,
                    betas=["computer-use-2025-01-24"],
                )
            except Exception as e:
                termcolor.cprint(f"Claude API error: {e}", color="red")
                return "api_error"

            # Process response
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            # Count and log
            tool_uses = [b for b in assistant_content if b.type == "tool_use"]
            text_blocks = [b for b in assistant_content if b.type == "text"]
            reasoning = " ".join(b.text for b in text_blocks)[:150] if text_blocks else ""

            turn_info = f"[Turn {self._turn_count}"
            if self.max_turns > 0:
                turn_info += f"/{self.max_turns}"
            turn_info += f"] {len(tool_uses)} action(s)"
            if reasoning:
                turn_info += f" | {reasoning}"
            print(turn_info)

            # No tool calls — nudge or stop
            if not tool_uses:
                text_only_retries += 1
                if text_only_retries >= 3:
                    termcolor.cprint(
                        "No actions after 3 nudges — stopping.", color="yellow"
                    )
                    return "no_actions"
                termcolor.cprint(
                    f"Text-only response ({text_only_retries}/3). Nudging...",
                    color="yellow",
                )
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": (
                            "You MUST take action now. Use the computer tool to "
                            "interact with the screen, or call task_complete if done."
                        )},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": self._screenshot_b64(),
                            },
                        },
                    ],
                })
                self._turn_count -= 1
                continue

            # Reset text-only counter on action
            text_only_retries = 0

            # Execute tool uses
            tool_results = []
            should_stop = False

            for block in tool_uses:
                # task_complete
                if block.name == self.finish_function_name:
                    summary = block.input.get("summary", "")
                    print(f"  [Task Complete] {summary}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Task completed successfully.",
                    })
                    should_stop = True
                    continue

                # Computer use action
                if block.name == "computer":
                    action = block.input.get("action", "")
                    self._execute_action(action, block.input)

                    # Capture screenshot after action
                    time.sleep(0.3)
                    screenshot_b64 = self._screenshot_b64()
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": screenshot_b64,
                                },
                            }
                        ],
                    })

            # Inject turn warning if approaching budget
            if self.max_turns > 0:
                remaining = self.max_turns - self._turn_count
                if 0 < remaining <= 5:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_uses[-1].id,
                        "content": (
                            f"WARNING: {remaining} turns left. "
                            f"Finish up and call {self.finish_function_name}()."
                        ),
                    })

            messages.append({"role": "user", "content": tool_results})

            if should_stop:
                termcolor.cprint("Task complete.", color="green")
                return "completed"

        return "completed"
