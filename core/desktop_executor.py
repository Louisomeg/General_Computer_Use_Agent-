import time
from core.freecad_functions import execute_system_shortcut, open_application, system_click, type_system_text, take_screenshot


def denormalize(value: int, screen_dimension: int) -> int:
    return int(value / 1000 * screen_dimension)


def do_scroll(page, x, y, direction, pixels):
    page.mouse.move(x, y)
    if direction == "down":
        page.mouse.wheel(0, pixels)
    elif direction == "up":
        page.mouse.wheel(0, -pixels)
    elif direction == "right":
        page.mouse.wheel(pixels, 0)
    elif direction == "left":
        page.mouse.wheel(-pixels, 0)


def execute_function_calls(candidate, page, screen_width, screen_height):
    results = []
    function_calls = []

    for part in candidate.content.parts:
        if part.function_call:
            function_calls.append(part.function_call)

    for function_call in function_calls:
        action_result = {}
        function_name = function_call.name
        args = function_call.args
        print(f"  -> Executing: {function_name}({dict(args) if args else ''})")

        try:
            if function_name == "system_shortcut":
                action_result = execute_system_shortcut(args["shortcut"])

            elif function_name == "open_application":
                action_result = open_application(args["name"])

            elif function_name == "system_click":
                actual_x = denormalize(args["x"], screen_width)
                actual_y = denormalize(args["y"], screen_height)
                action_result = system_click(actual_x, actual_y)

            elif function_name == "system_type":
                action_result = type_system_text(args["text"])

            elif function_name == "take_screenshot":
                action_result = take_screenshot()

            # Browser actions (existing)
            elif function_name == "open_web_browser":
                pass

            elif function_name == "wait_5_seconds":
                time.sleep(5)

            elif function_name == "go_back":
                page.go_back()

            elif function_name == "go_forward":
                page.go_forward()

            elif function_name == "search":
                page.goto("https://www.google.com")

            elif function_name == "navigate":
                page.goto(args["url"])

            elif function_name == "click_at":
                actual_x = denormalize(args["x"], screen_width)
                actual_y = denormalize(args["y"], screen_height)
                page.mouse.click(actual_x, actual_y)

            elif function_name == "hover_at":
                actual_x = denormalize(args["x"], screen_width)
                actual_y = denormalize(args["y"], screen_height)
                page.mouse.move(actual_x, actual_y)

            elif function_name == "type_text_at":
                actual_x = denormalize(args["x"], screen_width)
                actual_y = denormalize(args["y"], screen_height)
                text = args["text"]
                press_enter = args.get("press_enter", True)
                clear_before = args.get("clear_before_typing", True)

                page.mouse.click(actual_x, actual_y)

                if clear_before:
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")

                page.keyboard.type(text)

                if press_enter:
                    page.keyboard.press("Enter")

            elif function_name == "key_combination":
                page.keyboard.press(args["keys"])

            elif function_name == "scroll_document":
                direction = args["direction"]
                do_scroll(page, screen_width // 2, screen_height // 2, direction, 500)

            elif function_name == "scroll_at":
                actual_x = denormalize(args["x"], screen_width)
                actual_y = denormalize(args["y"], screen_height)
                direction = args["direction"]
                magnitude = args.get("magnitude", 800)
                scroll_pixels = int(magnitude / 1000 * max(screen_width, screen_height))
                do_scroll(page, actual_x, actual_y, direction, scroll_pixels)

            elif function_name == "drag_and_drop":
                start_x = denormalize(args["x"], screen_width)
                start_y = denormalize(args["y"], screen_height)
                end_x = denormalize(args["destination_x"], screen_width)
                end_y = denormalize(args["destination_y"], screen_height)

                page.mouse.move(start_x, start_y)
                page.mouse.down()
                page.mouse.move(end_x, end_y)
                page.mouse.up()

            else:
                print(f"  Warning: Unknown function '{function_name}'")
                action_result = {"error": f"Unknown function: {function_name}"}

            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except TimeoutError:
                pass
            time.sleep(0.5)

        except Exception as e:
            print(f"  Error executing {function_name}: {e}")
            action_result = {"error": str(e)}

        results.append((function_name, action_result))

    return results