from google.genai import Client, types

from core.agentic_loop import AgenticLoop
from core.desktop_executor import DesktopExecutor

test_client = Client()
de_exec = DesktopExecutor()
excluded_functions = ["open_web_browser", "go_back", "go_forward", "search", "navigate"]
config = {
    "tools": [
        types.Tool(
            computer_use=types.ComputerUse(
                environment=types.Environment.ENVIRONMENT_BROWSER,
                excluded_predefined_functions=excluded_functions,
            )
        )
    ],
    "system_instructions": "just be you",
}
test_loop = AgenticLoop(test_client, config=config)
test_loop.agentic_loop(
    "open freecad with the functions you have. print the functions you know before.",
    de_exec,
)
