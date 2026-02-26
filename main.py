from google import genai

from core.agentic_loop import AgenticLoop
from core.desktop_executor import DesktopExecutor

# Only run this block for Gemini Developer API
client = genai.Client()

agent_loop = AgenticLoop(client)
d_exec = DesktopExecutor()
agent_loop.agentic_loop('open free cad and tell me what you see', d_exec)
