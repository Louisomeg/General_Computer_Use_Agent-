# General Computer Use Agent

A multi-agent system that autonomously operates an Ubuntu Linux desktop to perform engineering design tasks. The system uses **Google Gemini's Computer Use API** (vision model) to see the screen, reason about what to do, and control the mouse/keyboard to drive applications like **FreeCAD** and **Google Chrome**.

Built for the Gemini API Developer Competition 2025.

## Table of Contents

- [Overview](#overview)
- [Key Insight: Model Sophistication Matters](#key-insight-model-sophistication-matters)
- [System Architecture](#system-architecture)
- [Demo](#demo)
- [Deployment](#deployment)
  - [One-Command GCP Deploy](#one-command-gcp-deploy)
  - [Local / Existing VM Setup](#local--existing-vm-setup)
- [Quick Start](#quick-start)
- [Agents](#agents)
  - [CAD Agent](#cad-agent)
  - [Research Agent](#research-agent)
  - [Documentation Agent](#documentation-agent)
- [Multi-Agent Workflow](#multi-agent-workflow)
- [The Agentic Loop](#the-agentic-loop)
- [Macro Execution Engine](#macro-execution-engine)
- [Planner Intelligence](#planner-intelligence)
- [Skill Learning Pipeline](#skill-learning-pipeline)
- [Coordinate System & Executors](#coordinate-system--executors)
- [Project Structure](#project-structure)
- [Configuration Reference](#configuration-reference)
- [Known Limitations & Lessons Learned](#known-limitations--lessons-learned)
- [Future Work](#future-work)
- [Troubleshooting](#troubleshooting)

---

## Overview

This project demonstrates a **general-purpose computer use agent** that can:

1. **Design 3D parts in FreeCAD** -- The CAD agent sees the FreeCAD GUI through screenshots, clicks menus, draws sketches, applies constraints, and performs Part Design operations (Pad, Pocket, Thickness, Fillet, etc.). It can also run Python macros directly in FreeCAD's console for precision geometry.

2. **Research information online** -- The Research agent opens a browser via Playwright, searches DuckDuckGo, reads pages, and extracts structured data with confidence scores and source URLs.

3. **Generate professional reports** -- The Documentation agent converts raw research data into formatted Word (.docx) and PDF documents with tables, sections, and citations.

4. **Chain agents together** -- The Planner can route a request like *"Make a bracket for an M6 bolt"* through Research (find bolt specs) -> Documentation (save report) -> CAD (build the 3D model with real dimensions).

### Key Technologies

| Component | Technology |
|-----------|-----------|
| Vision Model (Computer Use) | Google Gemini 3 Flash Preview (`gemini-3-flash-preview`) |
| Planning Model (Text-only) | Google Gemini 3.1 Pro Preview (`gemini-3.1-pro-preview`) |
| Desktop Control | xdotool (X11 input automation) |
| Macro Engine | Python -> FreeCAD console (via xclip paste) |
| Screenshots | scrot + PIL (resize to 1440x900) |
| Browser Control | Playwright (Chromium) |
| CAD Application | FreeCAD 1.0 |
| Document Generation | fpdf2 (PDF), python-docx (Word) |
| VM Environment | Ubuntu Linux, XFCE desktop, X11 display server |

---

## Key Insight: Model Sophistication Matters

Through extensive testing, we discovered that **complex engineering workflows are absolutely possible with Computer Use** -- but the quality of the output depends heavily on the model's reasoning capability, not just its ability to see and click.

### What We Learned

| Capability | Gemini 3 Flash (current) | Gemini 3.1 Pro (needed for CU) |
|-----------|--------------------------|------------------------|
| Open FreeCAD, navigate menus | Works reliably | Works reliably |
| Create simple shapes (cube, cylinder) | Works (~80% success) | Works |
| Draw sketches with constraints | Inconsistent | Reliable |
| Generate correct FreeCAD Python macros | Wrong API names, wrong face refs | Correct API usage |
| Multi-step designs (L-bracket + holes) | Fails silently, burns turns | Can reason through steps |
| Error recovery (undo, retry) | Repeats same mistake | Recognizes and adapts |
| Spatial reasoning (which face is "top"?) | Guesses Face6, Face12 | Understands geometry |

### The Core Problem

The vision model (`gemini-3-flash-preview`) can **see** the screen perfectly and **click** accurately. But CAD design requires **reasoning about 3D geometry from 2D screenshots** -- understanding which face is the "top face," how a pocket changes the shape, and what the correct FreeCAD Python API property name is. This is a reasoning task, not a vision task.

A more sophisticated model like `gemini-3.1-pro-preview` (when it supports Computer Use) would unlock:
- **Correct macro generation** -- right property names, right face selection logic
- **Multi-feature designs in one shot** -- L-brackets with holes, gears with teeth
- **Self-correction** -- recognizing when a macro failed and fixing the code
- **Spatial planning** -- knowing that after a Pocket, the face indices change

### Design Philosophy

Our architecture anticipates this: the **Planner** (already running on `gemini-3.1-pro`) generates detailed step-by-step workflows with correct FreeCAD API examples. The **CAD agent** (running on Flash) follows them. When a stronger model becomes available for Computer Use, the agent can handle more complex reasoning directly, and the Planner can send simpler instructions.

**Less instruction = better performance** with current vision models. The CAD agent uses a minimal system instruction (~130 lines) for desktop navigation. All task-specific intelligence comes from the Planner's action plans.

---

## System Architecture

```
                          +----------------+
                          |    main.py     |
                          |   (CLI/REPL)   |
                          +-------+--------+
                                  | user request
                                  v
                          +----------------+
                          |    Planner     |  <- Gemini 3.1 Pro (text-only)
                          | (Router +      |     classifies task, extracts
                          |  Plan Builder) |     params, generates workflow
                          +-------+--------+
                     +------------+------------+
                     v            v            v
              +--------+  +----------+  +----------------+
              |  CAD   |  | Research |  | Research -> CAD |
              | Agent  |  |  Agent   |  |   (chained)    |
              +---+----+  +----+-----+  +----------------+
                  |             |
                  v             v
           +-----------+ +------------+
           |  Desktop  | |  Browser   |
           | Executor  | | Executor   |
           | (xdotool) | |(Playwright)|
           +-----------+ +------------+
                  |             |
          +-------+-------+    |
          v               v    v
   +-----------+ +------+ +--------+
   |  FreeCAD  | |Macro | | Chrome |
   |   (GUI)   | |Engine| |(DuckDG)|
   +-----------+ +------+ +--------+

    +-------------------------------------------+
    |           Shared Agentic Loop             |
    |  screenshot -> Gemini -> function calls   |
    |  -> executor -> screenshot -> repeat...   |
    +-------------------------------------------+
```

### Data Flow: Research -> CAD Pipeline

```
User: "Make a bracket for an M6 bolt"
  |
  +- Planner._plan() -> Gemini classifies as "research+cad"
  |
  +- Phase 1: ResearchAgent
  |   +- Opens DuckDuckGo -> searches "M6 bolt dimensions"
  |   +- Reads multiple websites, extracts data points
  |   +- Returns: {data_points: [{fact: "clearance hole", value: "6.6", unit: "mm"}, ...]}
  |   +- DocumentationAgent auto-generates Word + PDF report
  |
  +- Phase 2: Planner._extract_dimensions()
  |   +- Gemini extracts CAD params: {hole_diameter: "6.6mm", wall_thickness: "3mm"}
  |
  +- Phase 3: Planner._generate_cad_goal()
  |   +- Gemini 3.1 Pro generates step-by-step FreeCAD workflow
  |   +- Includes correct API examples, face-finding patterns
  |
  +- Phase 4: CADAgent
      +- Gets enriched description + workflow + FreeCAD tips
      +- Runs macros and/or drives GUI to build the model
```

---

## Demo

### Demo Commands

```bash
# Full pipeline: research M6 bolt specs, then build bracket in FreeCAD
python3 main.py "Make a bracket for an M6 bolt"

# CAD only (skip research -- fast for testing/demos)
python3 main.py --cad "Make a bracket for an M6 bolt"

# CAD only with explicit dimensions
python3 main.py --cad --dims hole_diameter=6.6mm wall_thickness=3mm "L-bracket with bolt holes"

# Research only: find specs, generate report
python3 main.py "Research the standard dimensions of an M8 hex bolt"

# Simple CAD (auto-routes to CAD, no research needed)
python3 main.py "Create a 30mm cube in FreeCAD"
```

### What to Expect

**Research tasks (~3-5 minutes):**
1. Planner routes to Research agent
2. Browser opens DuckDuckGo, searches multiple queries
3. Agent visits 2-4 websites, extracts structured data points
4. Documentation agent generates Word + PDF reports in `outputs/research_results/`

**CAD tasks (~5-15 minutes depending on complexity):**
1. Planner generates a step-by-step FreeCAD workflow
2. CAD agent opens FreeCAD (or uses existing window)
3. Agent runs Python macros for precise geometry AND/OR uses GUI clicking
4. Stage budgets track progress (setup -> base_shape -> features -> cleanup)
5. Agent calls `task_complete()` when finished

**Chained tasks (Research -> CAD, ~8-20 minutes):**
1. Research phase finds real-world specifications
2. Planner extracts concrete dimensions from research data
3. CAD phase builds the model using researched specs

---

## Deployment

### One-Command GCP Deploy

Provision a fully configured Google Cloud VM with everything installed:

```bash
# Prerequisites: gcloud CLI installed + authenticated + project set
export GEMINI_API_KEY="your-key"

# Create VM with Ubuntu + XFCE + Xvfb + VNC + FreeCAD + agent
./scripts/deploy.sh --gcp

# Custom options
./scripts/deploy.sh --gcp --name my-agent --zone us-east1-b --machine-type e2-standard-8
```

**What it creates:**
- `e2-standard-4` Ubuntu 22.04 VM with 50GB SSD
- XFCE desktop on a virtual display (Xvfb at 1280x800)
- VNC server on port 5900 (watch the agent work remotely)
- FreeCAD, Chromium, Python venv, all dependencies
- Your API key injected into the environment
- `agent` alias for quick start

**After ~5-10 minutes setup:**
```bash
# SSH in
gcloud compute ssh engineering-agent-v2 --zone=us-central1-a

# Start
agent
python main.py --cad "Make a bracket for an M6 bolt"

# Watch via VNC (separate terminal)
gcloud compute ssh engineering-agent-v2 --zone=us-central1-a -- -L 5900:localhost:5900
# Then connect VNC client to localhost:5900
```

### Local / Existing VM Setup

#### VM Requirements

| Requirement | Specification |
|-------------|--------------|
| **OS** | Ubuntu 22.04+ LTS |
| **Desktop** | XFCE (lightweight, uses X11) |
| **Display Server** | X11 (NOT Wayland -- xdotool requires X11) |
| **Screen Resolution** | 1280x800 (16:10 aspect ratio) |
| **RAM** | 4 GB minimum, 8 GB recommended |
| **Disk** | 20 GB minimum |
| **Network** | Internet access for Gemini API + web research |

#### Automated Setup

```bash
git clone https://github.com/Louisomeg/General_Computer_Use_Agent-.git
cd General_Computer_Use_Agent-
git checkout design

# Full automated setup (system deps + python + verify)
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

#### Manual Setup

```bash
# 1. System dependencies
sudo apt install -y python3 python3-pip python3-venv scrot xdotool xclip ffmpeg git
sudo apt install -y freecad chromium-browser

# 2. Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# 3. API key
export GEMINI_API_KEY="your-key"

# 4. Verify
./scripts/deploy.sh --verify
```

#### Why These Display Settings?

- **1280x800 resolution**: Google recommends 1440x900 for Computer Use. 1280x800 is the closest available VM resolution with the same 16:10 aspect ratio. Screenshots are resized to 1440x900 before sending -- no distortion.
- **XFCE desktop**: Lightweight, X11-native, predictable UI layout. The system instruction teaches XFCE-specific navigation.
- **X11 display server**: Required by `xdotool` for mouse/keyboard input. Wayland is not supported.

---

## Quick Start

### Interactive Mode

```bash
python main.py
```

```
Agentic Planner -- type a request or 'quit' to exit
  Prefix with --cad to skip research

>>> Create a 50mm tall cylinder with radius 15mm
>>> --cad Make a bracket for an M6 bolt
>>> Research M6 bolt dimensions
>>> quit
```

### Direct CLI Mode

```bash
# Full pipeline (planner decides if research is needed)
python main.py "Make a bracket for an M6 bolt"

# CAD only -- skip research for fast iteration
python main.py --cad "Make a bracket for an M6 bolt"

# CAD only with explicit dimensions
python main.py --cad --dims hole_diameter=6.6mm wall_thickness=3mm "L-bracket"

# Research only
python main.py "What are the standard dimensions of an M8 hex bolt?"
```

---

## Agents

### CAD Agent

**File:** `agents/cad_agent.py`

The CAD agent drives FreeCAD through a combination of **GUI interaction** (clicking menus, drawing geometry) and **Python macro execution** (precise programmatic geometry). It sees the FreeCAD window through screenshots, reasons about what to do, and acts.

**Capabilities:**
- Create 3D parts from descriptions and dimensions
- Run Python macros in FreeCAD for precise geometry
- Draw 2D sketches with geometry and constraints via GUI
- Apply Part Design operations (Pad, Pocket, Hole, Thickness, Fillet, Chamfer)
- Navigate FreeCAD menus and dialogs
- Handle error recovery (undo mistakes, close unexpected dialogs)

**Stage Budgets** -- prevents the agent from burning all turns on one step:

| Stage | Budget | Description |
|-------|--------|-------------|
| setup | 10 turns | Open FreeCAD, create body, enter first sketch |
| base_shape | 25 turns | Draw base profile, constrain, Pad |
| features | 50 turns | Holes, pockets, fillets, chamfers |
| cleanup | 10 turns | Fit view, verify, save |
| reserve | 25 turns | Recovery budget for undo/retry |

**Key Design Decisions:**
- **Menu-driven interaction**: Always use menu bar (large text targets) instead of toolbar icons (~24px). This was one of our most impactful design decisions -- dramatically improves click accuracy.
- **Macro-first for geometry**: `execute_freecad_macro(code)` gives exact dimensions. GUI clicking is fallback.
- **One macro per feature**: Never put the entire design in one macro. If line 5 fails, lines 6-20 fail silently.
- **Dynamic face finding**: Never hardcode `Face6` or `Face12`. Find faces by position: `max(shape.Faces, key=lambda f: f.CenterOfMass.z)`.
- **Verification gate**: Agent must examine the screenshot before `task_complete()` is accepted.

### Research Agent

**File:** `agents/research_agent.py`

The Research agent browses the web using Playwright (Chromium). It uses **DuckDuckGo exclusively** -- most reliable for automated browsing (no CAPTCHAs, no cookie consent walls).

**Capabilities:**
- Web search via DuckDuckGo
- Multi-page browsing and data extraction
- Structured data output with confidence scoring and source URLs
- Automatic report generation via Documentation agent

**Output Format:**

```json
{
  "query": "M6 bolt dimensions",
  "findings": {
    "summary": "M6 bolts have a nominal diameter of 6mm...",
    "data_points": [
      {"fact": "Clearance hole (medium)", "value": "6.6", "unit": "mm", "source": "https://..."},
      {"fact": "Head width across flats", "value": "10", "unit": "mm", "source": "https://..."}
    ],
    "confidence": "high",
    "sources": ["https://...", "https://..."]
  }
}
```

### Documentation Agent

**File:** `agents/documentation_agent.py`

Converts raw research JSON into professionally formatted documents. Automatically called by the Research agent after data collection.

**Output Formats:**
- **Word Document (.docx)**: Full report with headers, tables, styled text, citations
- **PDF Document (.pdf)**: Matching PDF with tables and formatted sections

**Output Location:** `outputs/research_results/`

---

## Multi-Agent Workflow

The Planner (`core/agentic_planner.py`) orchestrates multi-agent workflows using Gemini 3.1 Pro (text-only) to classify requests and generate plans.

### Routing Logic

| Request Type | Route | Example |
|-------------|-------|---------|
| Exact dimensions provided | `cad` only | "Create a 50mm cylinder with 15mm radius" |
| Simple everyday object | `cad` only | "Make a box for storing pens" |
| Information lookup | `research` only | "What are M8 bolt specifications?" |
| Design needing real-world specs | `research+cad` | "Make a bracket for an M6 bolt" |
| Desktop operation | `cad` only | "Open FreeCAD and create a new body" |
| `--cad` flag used | `cad` only (skip research) | Any request |

### Quality Gates

The pipeline includes quality gates between phases:
1. **Research quality gate**: Checks if research produced data points with sufficient confidence. Fails fast if research returned nothing.
2. **Dimension extraction**: Gemini picks ONE concrete value per dimension (not ranges).
3. **Verification gate**: CAD agent must visually verify the result before declaring done.

---

## The Agentic Loop

**File:** `core/agentic_loop.py`

The core engine shared by all agents. Implements a multi-turn vision cycle:

```
+----------------------------------------------+
|              Agentic Loop Cycle               |
|                                               |
|  1. Capture screenshot (scrot -> PNG bytes)   |
|  2. Send to Gemini (screenshot + history)     |
|  3. Gemini returns function calls             |
|  4. Execute function calls via Executor       |
|  5. Append results to conversation history    |
|  6. Check stage budgets + turn warnings       |
|  7. Repeat until task_complete or max_turns   |
+----------------------------------------------+
```

### Error Recovery

| Scenario | Recovery |
|----------|----------|
| 400 INVALID_ARGUMENT | Reset history to initial prompt + fresh screenshot |
| Empty model response | Update screenshot in-place, retry (up to 3x) |
| Text-only response (no actions) | Inject nudge: "You must call a function" |
| Stage over budget | Inject warning to move to next stage |
| Max turns approaching | Inject countdown warnings (5, 4, 3, 2, 1) |
| Max consecutive API errors (5) | Return "api_error" status |

---

## Macro Execution Engine

**File:** `core/freecad_functions.py`

The macro executor bridges the gap between the agent's reasoning and FreeCAD's Python API. Instead of relying solely on GUI clicking (imprecise for exact dimensions), the agent can run Python code directly in FreeCAD's embedded console.

### How It Works

1. Agent calls `execute_freecad_macro(code)` with FreeCAD Python code
2. Code is wrapped in `try/except` that writes errors to `/tmp/agent_macro_log.txt`
3. Macro is saved to `/tmp/agent_macro.py`
4. FreeCAD window is found dynamically via `xdotool search --name FreeCAD`
5. Window geometry is used to calculate Python console input position
6. The run command is pasted via `xclip` (fast) or typed via `xdotool` (fallback)
7. Log file is read back to detect success or Python errors
8. Errors are returned to the agent so it can self-correct

### Error Capture

All user code is wrapped in error capture:

```python
import traceback as _tb
_log = open('/tmp/agent_macro_log.txt', 'w')
try:
    # user's FreeCAD code here
    _log.write('OK\n')
except Exception as _e:
    _log.write(f'ERROR: {_e}\n')
    _log.write(_tb.format_exc())
finally:
    _log.close()
```

Possible return values:
- `{"success": true}` -- macro ran without errors
- `{"error": "FreeCAD macro error: ..."}` -- Python exception with traceback
- `{"success": false, "warning": "Macro produced no output..."}` -- console wasn't focused

### Correct FreeCAD API Patterns

The macro tool description includes correct API examples so the model generates valid code:

```python
# Find faces by position (NEVER hardcode Face6, Face12)
top_face = max(body.Shape.Faces, key=lambda f: f.CenterOfMass.z)
face_idx = body.Shape.Faces.index(top_face) + 1

# Clearance hole (circle + Pocket ThroughAll -- more reliable than PartDesign::Hole)
hole_sk = body.newObject('Sketcher::SketchObject', 'HoleSketch')
hole_sk.AttachmentSupport = [(body.Tip, f'Face{face_idx}')]
hole_sk.MapMode = 'FlatFace'
hole_sk.addGeometry(Part.Circle(FreeCAD.Vector(cx,cy,0), FreeCAD.Vector(0,0,1), 3.3))
doc.recompute()
hole_cut = body.newObject('PartDesign::Pocket', 'HoleCut')
hole_cut.Profile = hole_sk
hole_cut.Type = 1  # ThroughAll
doc.recompute()
```

---

## Planner Intelligence

**File:** `core/agentic_planner.py`

The Planner does more than routing -- it generates **detailed FreeCAD workflows** using Gemini 3.1 Pro. This is critical because the vision model works best with clear, step-by-step instructions.

### LLM-Generated Workflows

Instead of hardcoded shape templates, the Planner uses Gemini 3.1 Pro to generate workflows dynamically:

```
Input:  "Make a bracket for an M6 bolt"
        + Research data: {hole_diameter: 6.6mm, wall_thickness: 3mm}

Output: Step 1: Create sketch on XY plane, 30x20mm rectangle, Pad 30mm
        Step 2: Create sketch on top face, 27x20mm rectangle offset 3mm, Pocket 27mm
        Step 3: Find top face of horizontal leg, circle r=3.3mm, Pocket ThroughAll
        Step 4: Find outer face of vertical leg, circle r=3.3mm, Pocket ThroughAll
        Step 5: Fillet inner corner 1mm radius
```

### Parameter Normalization

Research data comes with inconsistent key names. The Planner normalizes them:

```python
PARAM_ALIASES = {
    "length": "depth",
    "total_width": "width",
    "leg_thickness": "wall_thickness",
    "bolt_hole_diameter": "hole_diameter",
    "clearance_hole": "hole_diameter",
    ...
}
```

### Available Operations Vocabulary

The Planner tells Gemini 3.1 Pro exactly what FreeCAD operations exist, so it generates valid workflows:

```
Pad, Pocket, Hole, Fillet, Chamfer, Thickness, Mirrored,
Sketcher: Rectangle, Circle, Line, Arc, Point,
Constraints: Coincident, Horizontal, Vertical, DistanceX, DistanceY
```

---

## Skill Learning Pipeline

**Directory:** `pipeline/`

Converts YouTube FreeCAD tutorial videos into structured YAML skill files. Currently disabled in the CAD agent (minimal-instruction approach works better with Flash), but the infrastructure is ready for stronger models.

### Pipeline Stages

```
YouTube URL -> Download (yt-dlp) -> Transcribe (VTT/Whisper) -> Keyframes (OpenCV MOG2)
           -> Label (Gemini Vision) -> Filter (quality scoring) -> Build (YAML + PNG)
```

```bash
# Full pipeline
python -m pipeline.run_pipeline --url "https://www.youtube.com/watch?v=VIDEO_ID"

# Specific stages only
python -m pipeline.run_pipeline --url "VIDEO_ID" --stages keyframes,label,filter,build
```

### Pipeline Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold` | 15000 | MOG2 keyframe detection sensitivity |
| `min_score` | 3 | Minimum quality score (0-5) for filtering |
| `api_delay` | 1.0s | Delay between Gemini API calls |
| Video format | h264, <=720p | AV1 codec not supported on most VMs |

---

## Coordinate System & Executors

### Coordinate System

Gemini Computer Use outputs coordinates on a **normalized 0-1000 grid**:

```
screen_x = int(normalized_x / 1000 * SCREEN_WIDTH)   # 500/1000 * 1280 = 640
screen_y = int(normalized_y / 1000 * SCREEN_HEIGHT)   # 500/1000 * 800  = 400
```

### Desktop Executor Functions

| Function | Description |
|----------|-------------|
| `click_at(x, y)` | Left-click at normalized coordinates |
| `type_text_at(x, y, text)` | Click field, optionally clear, type text |
| `key_combination(keys)` | Key combo (e.g., "ctrl+z", "g+r" for rectangle) |
| `execute_freecad_macro(code)` | Run Python in FreeCAD console |
| `right_click_at(x, y)` | Right-click for context menus |
| `double_click_at(x, y)` | Double-click to open/select |
| `scroll_at(x, y, direction)` | Scroll at position |
| `drag_and_drop(...)` | Drag between two points |
| `task_complete(summary)` | Signal task completion |

---

## Project Structure

```
General_Computer_Use_Agent-/
|
+-- main.py                      # Entry point (CLI + interactive, --cad flag)
+-- requirements.txt             # Python dependencies
+-- scripts/
|   +-- deploy.sh                # Automated deployment (local + GCP VM)
|
+-- agents/                      # Agent implementations
|   +-- registry.py              # @register decorator + get_agent() factory
|   +-- cad_agent.py             # FreeCAD CAD agent (GUI + macros)
|   +-- research_agent.py        # Web research agent (DuckDuckGo + Playwright)
|   +-- documentation_agent.py   # Word + PDF report generator
|
+-- core/                        # Shared infrastructure
|   +-- agentic_loop.py          # Multi-turn vision loop (stage budgets, verification)
|   +-- agentic_planner.py       # Task router + LLM workflow generation
|   +-- executor.py              # Abstract Executor base class
|   +-- desktop_executor.py      # xdotool desktop executor
|   +-- browser_executor.py      # Playwright browser executor
|   +-- screenshot.py            # scrot capture + PIL resize
|   +-- settings.py              # Global config + system instruction
|   +-- models.py                # Task, TaskStatus data models
|   +-- custom_tools.py          # FreeCAD macro FunctionDeclaration
|   +-- freecad_functions.py     # Macro engine + xdotool wrappers
|   +-- skill_retrieval.py       # Demo skill matching (disabled)
|
+-- pipeline/                    # YouTube -> Skill learning pipeline
|   +-- run_pipeline.py          # Pipeline orchestrator
|   +-- crawl.py                 # yt-dlp download
|   +-- transcribe.py            # Subtitle extraction
|   +-- extract_keyframes.py     # OpenCV keyframe detection
|   +-- label_actions.py         # Gemini action labeling
|   +-- filter_quality.py        # Quality scoring
|   +-- build_skills.py          # YAML skill assembly
|
+-- skills/                      # FreeCAD knowledge base (reference)
+-- outputs/                     # Generated outputs
    +-- research_results/        # Research JSON + Word + PDF reports
    +-- cad_exports/             # Exported CAD files
```

---

## Configuration Reference

### `core/settings.py`

| Setting | Default | Description |
|---------|---------|-------------|
| `SCREEN_WIDTH` | 1280 | VM screen width in pixels |
| `SCREEN_HEIGHT` | 800 | VM screen height in pixels |
| `MODEL_SCREEN_WIDTH` | 1440 | Screenshot width sent to Gemini |
| `MODEL_SCREEN_HEIGHT` | 900 | Screenshot height sent to Gemini |
| `ACTION_DELAY` | 0.5s | Pause after each action |
| `TYPING_DELAY` | 30ms | Delay between keystrokes (xdotool) |
| `CLICK_DELAY` | 0.3s | Pause after mouse clicks |
| `DEFAULT_MODEL` | `gemini-3-flash-preview` | Computer Use model |
| `PLANNING_MODEL` | `gemini-3.1-pro-preview` | Text-only planning model |

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Google Gemini API key ([get one here](https://aistudio.google.com/apikey)) |
| `DISPLAY` | Yes (auto) | X11 display (usually `:0`, set automatically) |

---

## Known Limitations & Lessons Learned

### What Works Well

- **Research agent** is reliable -- DuckDuckGo avoids CAPTCHAs, structured data extraction works consistently
- **Documentation agent** produces professional reports every time
- **Simple CAD shapes** (cubes, cylinders, basic pads) succeed ~80% of the time
- **Menu-driven interaction** dramatically outperforms toolbar clicking
- **Macro execution** gives precise dimensions when the console is focused correctly
- **Stage budgets** prevent the agent from wasting all turns on one step
- **Two-model architecture** works well -- use the smartest model (3.1 Pro) for planning/reasoning, and the Computer Use model (Flash) for execution

### What Struggles

1. **FreeCAD Python API knowledge**: The vision model generates macros with wrong property names, wrong face references, and incorrect constraint syntax. The Planner mitigates this by providing correct API examples, but the model still hallucinates.

2. **Face selection after topology changes**: After a Pocket or Pad, face indices change. The model guesses `Face6` or `Face12` instead of using the dynamic face-finding pattern we provide.

3. **Silent macro failures**: Even with error capture, some failures are subtle -- a sketch might be created but with wrong constraints, or a Pad might succeed but with wrong dimensions.

4. **Long sessions (80+ turns)**: The vision model's accuracy degrades as the context window fills with screenshots.

5. **Rate limits**: Heavy Computer Use sessions (20-80+ turns) can exhaust free tier quotas. Typically resets within 30-60 minutes.

### Architecture Insights

- **Macro + GUI hybrid**: Best results come from using macros for precise geometry and GUI clicking for navigation/menus. Neither approach alone is sufficient.
- **One feature per macro**: Critical lesson. A single macro creating sketch + pad + pocket + hole will silently fail at the first error. One feature per call with screenshot verification between each.
- **Thickness over Pocket for hollowing**: For hollow shapes, the Thickness tool (~24 turns) massively outperforms Pocket workflows (65+ turns, low success rate).

---

## Future Work

### When Gemini 3.1 Pro Gets Computer Use

The architecture is ready. When a reasoning-class model supports Computer Use:

1. **Complex parts in one session**: L-brackets with holes, gears, multi-body assemblies
2. **Self-correcting macros**: Model reads error output, fixes API calls, retries
3. **Spatial reasoning**: Understands which face is "top" after a pocket changes geometry
4. **150+ turn sessions**: Maintains precision and coherence across long designs
5. **Reduced Planner dependency**: Model can figure out the workflow itself

### Expanding to Other Tools

- **KiCad** for PCB design
- **Blender** for 3D modeling and rendering
- **LibreOffice** for document editing
- General desktop automation beyond engineering

### Other Improvements

- Web interface for remote agent control and monitoring
- Better parallelism -- running multiple agents simultaneously
- More robust error recovery with learning from failure patterns
- Leveraging the Skill Learning Pipeline with stronger models
- Multi-part assemblies using FreeCAD's Assembly workbench

---

## Troubleshooting

### Common Issues

**"ERROR: Set GEMINI_API_KEY first!"**
```bash
export GEMINI_API_KEY="your-key"
```

**"FreeCAD window not found"** (macro execution)
- FreeCAD must be running and visible
- Check: `xdotool search --name FreeCAD` should return a window ID

**"Macro produced no output"**
- The Python console input wasn't focused. The agent should retry.
- Verify Python console is visible: View -> Panels -> Python console in FreeCAD
- Install xclip for more reliable paste: `sudo apt install xclip`

**FreeCAD "Document Recovery" dialog**
```bash
rm -rf ~/.local/share/FreeCAD/recovery/*
rm -rf ~/.FreeCAD/recovery/*
```

**Research agent fails**
- Should not happen with DuckDuckGo. Agent auto-retries on the same search engine.

**400 INVALID_ARGUMENT from Gemini API**
- Handled automatically by history reset in the agentic loop

**Rate limit errors (429)**
- Free tier quotas reset within 30-60 minutes
- Use `--cad` flag to skip research and reduce API calls

**CAD agent hits max_turns without finishing**
- Complex designs may need more turns
- Increase `max_turns` in `agents/cad_agent.py` (default: 120)
- Use `--cad` with explicit `--dims` for faster iteration

---

## Authors

- **Louis** -- Core framework, desktop executor, CAD agent, agentic loop, planner, macro engine
- **Emmanuel** -- Research agent, browser executor, documentation agent, parallel research

---

## License

This project is part of the Gemini API Developer Competition 2025. See repository for license details.
