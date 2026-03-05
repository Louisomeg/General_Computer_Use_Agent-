from google.genai import Client, types

from core.agentic_loop import AgenticLoop
from core.desktop_executor import DesktopExecutor

test_client = Client()
de_exec = DesktopExecutor()
function_names = [
    de_exec._click_at,
    de_exec._hover_at,
    de_exec._type_text_at,
    de_exec._scroll_document,
    de_exec._scroll_at,
    de_exec._wait,
    de_exec._key_combination,
    de_exec._drag_and_drop,
]
functions = [
    types.FunctionDeclaration.from_callable(client=test_client, callable=c)
    for c in function_names
]
config = {"tools": [types.Tool(function_declarations=functions)]}
test_loop = AgenticLoop(test_client)
test_loop.agentic_loop(
    "print all the functions you have. then open freecad with these functions", de_exec
)
