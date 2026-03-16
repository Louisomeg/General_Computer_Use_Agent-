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
                "clicking. The code is wrapped in try/except automatically — "
                "errors are captured and returned to you so you can fix them. "
                "IMPORTANT API NOTES:\n"
                "- New document: doc = FreeCAD.newDocument('Part')\n"
                "- Add body: body = doc.addObject('PartDesign::Body', 'Body')\n"
                "- Add sketch to body: sketch = body.newObject('Sketcher::SketchObject', 'Sketch')\n"
                "- Set sketch plane: sketch.AttachmentSupport = [(doc.getObject('XY_Plane'), '')]\n"
                "  or on a face: sketch.AttachmentSupport = [(pad, 'Face6')]\n"
                "- Sketch geometry:\n"
                "  sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(x1,y1,0), FreeCAD.Vector(x2,y2,0)))\n"
                "  sketch.addGeometry(Part.Circle(FreeCAD.Vector(cx,cy,0), FreeCAD.Vector(0,0,1), radius))\n"
                "- Sketch constraints:\n"
                "  sketch.addConstraint(Sketcher.Constraint('Coincident', edge1, vertex1, edge2, vertex2))\n"
                "  sketch.addConstraint(Sketcher.Constraint('DistanceX', edge, vertex, value))\n"
                "  sketch.addConstraint(Sketcher.Constraint('DistanceY', edge, vertex, value))\n"
                "  sketch.addConstraint(Sketcher.Constraint('Radius', edge, radius))\n"
                "  sketch.addConstraint(Sketcher.Constraint('Equal', edge1, edge2))\n"
                "- Pad: pad = body.newObject('PartDesign::Pad', 'Pad')\n"
                "  pad.Profile = sketch\n"
                "  pad.Length = 10  # mm\n"
                "- Pocket: pocket = body.newObject('PartDesign::Pocket', 'Pocket')\n"
                "  pocket.Profile = sketch2\n"
                "  pocket.Length = 5\n"
                "  pocket.Type = 1  # 0=Dimension, 1=ThroughAll\n"
                "- Hole: hole = body.newObject('PartDesign::Hole', 'Hole')\n"
                "  hole.Profile = sketch3  # sketch with a circle\n"
                "  hole.Diameter = 6.6\n"
                "  hole.Depth = 10  # or hole.HoleType = 1 for ThroughAll\n"
                "- Fillet: fillet = body.newObject('PartDesign::Fillet', 'Fillet')\n"
                "  fillet.Base = (pad, ['Edge1', 'Edge2'])\n"
                "  fillet.Radius = 2\n"
                "- ALWAYS call doc.recompute() after making changes.\n"
                "- ALWAYS import FreeCAD, Part, Sketcher at the top.\n"
                "- Face/Edge references like 'Face6' can change after recompute. "
                "When possible, create sketches on known planes (XY, XZ, YZ) instead."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            "FreeCAD Python code to execute. Errors are captured "
                            "automatically and returned to you. Always import "
                            "FreeCAD, Part, Sketcher. Always call doc.recompute() "
                            "at the end."
                        ),
                    },
                },
                "required": ["code"],
            },
        ),
    ]
