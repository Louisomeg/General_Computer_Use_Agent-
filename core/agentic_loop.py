import time
from typing import Optional

import termcolor
from google.genai import Client, types
from google.genai.types import Candidate, GenerateContentConfig

from core.custom_tools import get_custom_declarations
from core.executor import Executor
from core.screenshot import capture_desktop_screenshot

MAX_SCREENSHOTS = 1 # FIX: this was random.

class AgenticLoop:
    def __init__(self, client: Client):
        self.client = client


    def agentic_loop(self, prompt: str, executor: Executor):
        """Please note"""
        # append initial prompt
        history = [types.Content(role='user', parts=[types.Part.from_text(text=prompt)])]
        while True:
            # take screenshot
            screenshot_bytes = capture_desktop_screenshot()

            # append screenshot
            history.append(types.Content(role='user', parts=[types.Part.from_bytes(mime_type='image/png', data=screenshot_bytes)]))

            # clean history — remove old screenshots to stay within API limits
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

            # get response safely
            try:
                response = self.get_model_response(history)
            except Exception as e:
                print(e)
                break
            if not response.candidates:
                print("Response has no candidates!")
                print(response)
                raise ValueError("Empty response")

            # Extract the text and function call from the response.
            candidate = response.candidates[0]

            # Append the model turn to conversation history.
            if candidate.content:
                history.append(candidate.content)

            reasoning = self.get_text(candidate)
            function_calls = self.extract_function_calls(candidate)

            # Retry the request in case of malformed FCs.
            if (
                    not function_calls
                    and not reasoning
                    and candidate.finish_reason == types.FinishReason.MALFORMED_FUNCTION_CALL
                    ):
                break
            
            if not function_calls:
                print(f"Agent Loop Complete: {reasoning}")
                break

            # handle function calls
            function_responses = executor.execute(function_calls)

            # Gemini Computer Use model requires every function response to
            # include a 'url' field.  For desktop actions we use a placeholder.
            # See: https://ai.google.dev/gemini-api/docs/computer-use
            response_parts = []
            for function_call, fc_response in function_responses:
                fc_response.setdefault("url", "desktop://linux")
                response_parts.append(
                    types.Part.from_function_response(
                        name=function_call,
                        response=fc_response,
                    )
                )

            new_responses = types.Content(role='user', parts=response_parts)
            history.append(new_responses)

    def config(self):
        content_config = GenerateContentConfig(
            temperature=1,
            top_p=0.95,
            top_k=40,
            max_output_tokens=8192,
            tools=[
                types.Tool(
                    computer_use=types.ComputerUse(
                        ),
                    ),
                types.Tool(function_declarations=get_custom_declarations()),
                ],
            thinking_config=types.ThinkingConfig(
                include_thoughts=True
                ),
            )
        return content_config

    def get_model_response(
            self, history, max_retries=5, base_delay_s=1
    ) -> types.GenerateContentResponse:
        configuration = self.config() 
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                        model='gemini-2.5-computer-use-preview-10-2025',
                        contents=history,
                        config=configuration
                        )
                return response  # Return response on success
            except Exception as e:
                print(e)
                if attempt < max_retries - 1:
                    delay = base_delay_s * (2**attempt)
                    message = (
                            f"Generating content failed on attempt {attempt + 1}. "
                            f"Retrying in {delay} seconds...\n"
                            )
                    termcolor.cprint(
                            message,
                            color="yellow",
                            )
                    time.sleep(delay)
                else:
                    termcolor.cprint(
                            f"Generating content failed after {max_retries} attempts.\n",
                            color="red",
                            )
                    raise

    def get_text(self, candidate: Candidate) -> Optional[str]:
        """Extracts the text from the candidate."""
        if not candidate.content or not candidate.content.parts:
            return None
        text = []
        for part in candidate.content.parts:
            if part.text:
                text.append(part.text)
        return " ".join(text) or None

    def extract_function_calls(self, candidate: Candidate) -> list[types.FunctionCall]:
        """Extracts the function call from the candidate."""
        if not candidate.content or not candidate.content.parts:
            return []
        ret = []
        for part in candidate.content.parts:
            if part.function_call:
                ret.append(part.function_call)
        return ret
