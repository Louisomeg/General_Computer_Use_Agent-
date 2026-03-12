from google.genai import types


def get_custom_declarations() -> list:
    """Build and return custom FunctionDeclaration objects for Gemini.

    These are passed alongside the computer_use Tool so Gemini knows
    what custom functions it can call beyond the predefined ones.
    """
    return [
        # Right-click at normalized coordinates (0-1000 grid)
        types.FunctionDeclaration(
            name="right_click_at",
            description=(
                "Perform a right-click at the specified coordinates to open "
                "context menus. Coordinates use the same 0-1000 normalized grid "
                "as click_at."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "X coordinate (0-1000 normalized)",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Y coordinate (0-1000 normalized)",
                    },
                },
                "required": ["x", "y"],
            },
        ),
        # Double-click at normalized coordinates (0-1000 grid)
        types.FunctionDeclaration(
            name="double_click_at",
            description=(
                "Perform a double-click at the specified coordinates to "
                "select or activate elements. Coordinates use the same 0-1000 "
                "normalized grid as click_at."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "X coordinate (0-1000 normalized)",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Y coordinate (0-1000 normalized)",
                    },
                },
                "required": ["x", "y"],
            },
        ),
        # Open application via Ubuntu launcher
        types.FunctionDeclaration(
            name="open_application",
            description=(
                "Launch an application by name using the Ubuntu desktop "
                "launcher. Presses Super key, types the application name, "
                "and presses Enter to launch it."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the application to launch (e.g. 'FreeCAD', 'Terminal', 'Firefox')",
                    },
                },
                "required": ["name"],
            },
        ),
    ]
