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
        # Execute a FreeCAD Python macro for precision operations
        types.FunctionDeclaration(
            name="execute_freecad_macro",
            description=(
                "Execute Python code directly in FreeCAD's Python console. "
                "Use this for precision operations that are hard to achieve by "
                "clicking (exact hole placement, precise dimensions, complex "
                "geometry). The code runs in FreeCAD's embedded Python "
                "interpreter with full access to FreeCAD, Part, PartDesign, "
                "and Sketcher modules. The macro is written to a temp file "
                "and executed via FreeCAD's RunMacro. Use this when GUI "
                "clicking is imprecise or when you need exact coordinates. "
                "Example: creating a hole at exact position (10, 15) with "
                "diameter 6.6mm."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            "FreeCAD Python code to execute. Has access to "
                            "FreeCAD, Part, PartDesign, Sketcher modules. "
                            "Example: "
                            "'import FreeCAD\\n"
                            "doc = FreeCAD.ActiveDocument\\n"
                            "body = doc.getObject(\"Body\")\\n"
                            "doc.recompute()'"
                        ),
                    },
                },
                "required": ["code"],
            },
        ),
    ]
