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
                "Use this for precision operations. Errors are captured and "
                "returned to you so you can fix them.\n\n"
                "## CRITICAL RULES\n"
                "1. Write ONE SMALL MACRO per call (one feature at a time). "
                "Do NOT put the entire design in one macro. If step 3 fails, "
                "steps 4-6 silently fail too.\n"
                "2. After each macro, CHECK THE SCREENSHOT for errors before "
                "continuing to the next step.\n"
                "3. NEVER guess face names (Face6, Face12). Use the helper "
                "below to find faces by position.\n\n"
                "## CORRECT API (FreeCAD 1.0)\n\n"
                "### Setup\n"
                "  import FreeCAD, Part, Sketcher\n"
                "  doc = FreeCAD.activeDocument()  # use existing doc\n"
                "  body = doc.getObject('Body')    # use existing body\n\n"
                "### Sketch on a standard plane\n"
                "  sketch = body.newObject('Sketcher::SketchObject', 'MySketch')\n"
                "  sketch.AttachmentSupport = [(doc.getObject('XY_Plane'), '')]\n"
                "  sketch.MapMode = 'FlatFace'\n\n"
                "### Sketch on a FACE (find face by position first!)\n"
                "  # Find the top face (highest Z center):\n"
                "  shape = body.Shape\n"
                "  top_face = max(shape.Faces, key=lambda f: f.CenterOfMass.z)\n"
                "  face_idx = shape.Faces.index(top_face) + 1\n"
                "  face_name = f'Face{face_idx}'\n"
                "  tip = body.Tip  # last feature in the body\n"
                "  sketch.AttachmentSupport = [(tip, face_name)]\n"
                "  sketch.MapMode = 'FlatFace'\n"
                "  # For front face: max y. For right face: max x.\n"
                "  # For bottom: min z. For back: min y. For left: min x.\n\n"
                "### Rectangle (4 lines + constraints)\n"
                "  sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(0,0,0), FreeCAD.Vector(W,0,0)))\n"
                "  sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(W,0,0), FreeCAD.Vector(W,H,0)))\n"
                "  sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(W,H,0), FreeCAD.Vector(0,H,0)))\n"
                "  sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(0,H,0), FreeCAD.Vector(0,0,0)))\n"
                "  # Add Coincident constraints to close corners:\n"
                "  sketch.addConstraint(Sketcher.Constraint('Coincident', 0, 2, 1, 1))\n"
                "  sketch.addConstraint(Sketcher.Constraint('Coincident', 1, 2, 2, 1))\n"
                "  sketch.addConstraint(Sketcher.Constraint('Coincident', 2, 2, 3, 1))\n"
                "  sketch.addConstraint(Sketcher.Constraint('Coincident', 3, 2, 0, 1))\n\n"
                "### Circle (for holes — use with Pocket ThroughAll)\n"
                "  sketch.addGeometry(Part.Circle(FreeCAD.Vector(cx,cy,0), FreeCAD.Vector(0,0,1), radius))\n\n"
                "### Pad (extrude a sketch)\n"
                "  pad = body.newObject('PartDesign::Pad', 'Pad')\n"
                "  pad.Profile = sketch\n"
                "  pad.Length = 10.0\n"
                "  doc.recompute()\n\n"
                "### Pocket (cut into solid)\n"
                "  pocket = body.newObject('PartDesign::Pocket', 'Pocket')\n"
                "  pocket.Profile = sketch\n"
                "  pocket.Length = 5.0         # for fixed depth\n"
                "  pocket.Type = 1             # 0=Dimension, 1=ThroughAll\n"
                "  doc.recompute()\n\n"
                "### CLEARANCE HOLE (circle + Pocket ThroughAll)\n"
                "  # This is MORE RELIABLE than PartDesign::Hole.\n"
                "  # Step 1: Find the face to put the hole on:\n"
                "  shape = body.Shape\n"
                "  top_face = max(shape.Faces, key=lambda f: f.CenterOfMass.z)\n"
                "  face_idx = shape.Faces.index(top_face) + 1\n"
                "  # Step 2: Create sketch with a circle on that face:\n"
                "  hole_sk = body.newObject('Sketcher::SketchObject', 'HoleSketch')\n"
                "  hole_sk.AttachmentSupport = [(body.Tip, f'Face{face_idx}')]\n"
                "  hole_sk.MapMode = 'FlatFace'\n"
                "  hole_sk.addGeometry(Part.Circle(FreeCAD.Vector(cx,cy,0), FreeCAD.Vector(0,0,1), 3.3))  # radius=3.3 for 6.6mm hole\n"
                "  doc.recompute()\n"
                "  # Step 3: Pocket ThroughAll:\n"
                "  hole_cut = body.newObject('PartDesign::Pocket', 'HoleCut')\n"
                "  hole_cut.Profile = hole_sk\n"
                "  hole_cut.Type = 1  # ThroughAll\n"
                "  doc.recompute()\n\n"
                "### Fillet\n"
                "  fillet = body.newObject('PartDesign::Fillet', 'Fillet')\n"
                "  fillet.Base = (body.Tip, ['Edge1'])\n"
                "  fillet.Radius = 2.0\n"
                "  doc.recompute()\n\n"
                "## COMMON MISTAKES TO AVOID\n"
                "- NEVER hardcode Face6, Face12, etc. Always find faces by position.\n"
                "- NEVER create a new document if one already exists. Use activeDocument().\n"
                "- NEVER put everything in one macro. One feature per call.\n"
                "- Use body.Tip (not pad or pocket) as AttachmentSupport for sketches "
                "on faces — Tip always points to the latest feature.\n"
                "- ALWAYS call doc.recompute() after creating/modifying features.\n"
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            "FreeCAD Python code to execute. Keep it SHORT — "
                            "one feature per call. Errors are captured and "
                            "returned. Always import FreeCAD, Part, Sketcher. "
                            "Always call doc.recompute() at the end."
                        ),
                    },
                },
                "required": ["code"],
            },
        ),
    ]
