from google.genai import Client, types

from core.agentic_loop import AgenticLoop
from core.desktop_executor import DesktopExecutor

test_client = Client()
de_exec = DesktopExecutor()
excluded_functions = [
    "click_at",
    "hover_at",
    "type_text_at",
    "scroll_document",
    "scroll_at",
    "wait_5_seconds",
    "key_combination",
    "drag_and_drop",
]
config = {
    "tools": [
        types.Tool(
            computer_use=types.ComputerUse(
                environment=types.Environment.ENVIRONMENT_BROWSER,
                excluded_predefined_functions=excluded_functions,
            )
        )
    ]
}
test_loop = AgenticLoop(test_client, config=config)
test_loop.agentic_loop(
    "print all the functions you have. then open freecad with these functions", de_exec
)
