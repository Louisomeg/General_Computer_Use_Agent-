from typing import Optional, Set

from google.genai import types

from core.settings import (
    UBUNTU_SHORTCUTS,
    FREECAD_SHORTCUTS,
    EXCLUDED_PREDEFINED_FUNCTIONS,
)


def _build_shortcut_description(shortcuts: dict, prefix: str) -> str:
    """Build a description string listing all available shortcuts by category.

    The description is what Gemini reads to decide which shortcut_name to use.
    """
    lines = [prefix, "", "Available shortcuts:"]
    for name, info in shortcuts.items():
        lines.append(f"  {name}: {info['description']}")
    return "\n".join(lines)


def get_custom_declarations(
    ubuntu_filter: Optional[Set[str]] = None,
    freecad_filter: Optional[Set[str]] = None,
) -> list:
    """Build and return the 5 custom FunctionDeclaration objects for Gemini.

    These are passed alongside the computer_use Tool so Gemini knows
    what custom functions it can call beyond the 13 predefined ones.

    Args:
        ubuntu_filter: If provided, only include these Ubuntu shortcut names.
                       If None, include ALL Ubuntu shortcuts.
        freecad_filter: If provided, only include these FreeCAD shortcut names.
                        If None, include ALL FreeCAD shortcuts.
    """
    # Apply optional filters to reduce token overhead per turn
    ubuntu = UBUNTU_SHORTCUTS
    if ubuntu_filter is not None:
        ubuntu = {k: v for k, v in UBUNTU_SHORTCUTS.items() if k in ubuntu_filter}

    freecad = FREECAD_SHORTCUTS
    if freecad_filter is not None:
        freecad = {k: v for k, v in FREECAD_SHORTCUTS.items() if k in freecad_filter}

    system_shortcut_desc = _build_shortcut_description(
        ubuntu,
        "Execute an Ubuntu desktop keyboard shortcut by name.",
    )

    freecad_shortcut_desc = _build_shortcut_description(
        freecad,
        "Execute a FreeCAD keyboard shortcut by name. "
        "Use this for FreeCAD-specific operations like view changes, "
        "sketcher tools, constraints, and Part Design commands.",
    )

    declarations = [
        # 1. Ubuntu system shortcuts
        types.FunctionDeclaration(
            name="system_shortcut",
            description=system_shortcut_desc,
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "shortcut_name": {
                        "type": "string",
                        "description": "Name of the Ubuntu shortcut to execute",
                    },
                },
                "required": ["shortcut_name"],
            },
        ),
        # 2. FreeCAD shortcuts
        types.FunctionDeclaration(
            name="freecad_shortcut",
            description=freecad_shortcut_desc,
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "shortcut_name": {
                        "type": "string",
                        "description": "Name of the FreeCAD shortcut to execute",
                    },
                },
                "required": ["shortcut_name"],
            },
        ),
        # 3. Right-click at normalized coordinates
        types.FunctionDeclaration(
            name="right_click_at",
            description=(
                "Perform a right-click at the specified coordinates to open "
                "context menus. Coordinates are in the 0-999 normalized range."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "X coordinate (0-999 normalized)",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Y coordinate (0-999 normalized)",
                    },
                },
                "required": ["x", "y"],
            },
        ),
        # 4. Double-click at normalized coordinates
        types.FunctionDeclaration(
            name="double_click_at",
            description=(
                "Perform a double-click at the specified coordinates to "
                "select or activate elements. Coordinates are in the "
                "0-999 normalized range."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "X coordinate (0-999 normalized)",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Y coordinate (0-999 normalized)",
                    },
                },
                "required": ["x", "y"],
            },
        ),
        # 5. Open application via Ubuntu launcher
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

    return declarations


def get_excluded_functions() -> list:
    """Return the list of predefined Gemini functions to exclude.

    These are browser-only functions not needed for desktop execution.
    """
    return list(EXCLUDED_PREDEFINED_FUNCTIONS)
