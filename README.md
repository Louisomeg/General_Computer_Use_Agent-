# General Computer Use Agent

A multi-agent system that autonomously operates an Ubuntu Linux desktop to perform engineering design tasks. The system uses **Google Gemini's Computer Use API** (vision model) to see the screen, reason about what to do, and control the mouse/keyboard to drive applications like **FreeCAD** and **Google Chrome** — all without any application-specific APIs or scripting.

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
- [Demo](#demo)
- [VM Environment Setup](#vm-environment-setup)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Agents](#agents)
  - [CAD Agent](#cad-agent)
  - [Research Agent](#research-agent)
  - [Documentation Agent](#documentation-agent)
- [Multi-Agent Workflow](#multi-agent-workflow)
- [The Agentic Loop](#the-agentic-loop)
- [Shape Decomposition & Planner Intelligence](#shape-decomposition--planner-intelligence)
- [Skill Learning Pipeline](#skill-learning-pipeline)
- [Coordinate System & Executors](#coordinate-system--executors)
- [Project Structure](#project-structure)
- [Configuration Reference](#configuration-reference)
- [Known Limitations](#known-limitations)
- [Future Work — Stronger Models](#future-work--stronger-models)
- [Troubleshooting](#troubleshooting)

---

## Overview

This project demonstrates a **general-purpose computer use agent** that can:

1. **Design 3D parts in FreeCAD** — The CAD agent sees the FreeCAD GUI through screenshots, clicks menus, draws sketches, applies constraints, and performs Part Design operations (Pad, Pocket, Thickness, Fillet, etc.) just like a human would.

2. **Research information online** — The Research agent opens Google Chrome via Playwright, searches the web, reads pages, and extracts structured data with confidence scores and source URLs.

3. **Generate professional reports** — The Documentation agent converts raw research data into formatted Word (.docx) and PDF documents with tables, sections, and citations.

4. **Chain agents together** — The Planner can route a request like *"Make a phone holder for a bicycle"* through Research (find handlebar/phone dimensions) → Documentation (save report) → CAD (build the 3D model with real dimensions).

### Design Philosophy

Through extensive testing, we discovered that **less instruction = better performance** with vision-based computer use models. The CAD agent uses a minimal system instruction (~130 lines) that teaches basic desktop navigation and FreeCAD menu usage. All task-specific intelligence comes from the **Planner**, which generates detailed action plans with step-by-step workflows tailored to each shape.

This "minimal instruction + smart planning" approach outperforms longer, more detailed system prompts because the model can focus on what it sees rather than reconciling conflicting instructions.

### Key Technologies

| Component | Technology |
|-----------|-----------|
| Vision Model (Computer Use) | Google Gemini 3 Flash Preview (`gemini-3-flash-preview`) |
| Planning Model (Text-only) | Google Gemini 3.1 Pro Preview (`gemini-3.1-pro-preview`) |
| Desktop Control | xdotool (X11 input automation) |
| Screenshots | scrot + PIL (resize to 1440x900) |
| Browser Control | Playwright (Chromium) |
| CAD Application | FreeCAD 1.0 |
| Document Generation | fpdf2 (PDF), python-docx (Word) |
| VM Environment | Ubuntu Linux, XFCE desktop, X11 display server |

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
                  v             v
           +-----------+ +------------+
           |  FreeCAD  | |   Chrome   |
           |   (GUI)   | | (headless) |
           +-----------+ +------------+

    +-------------------------------------------+
    |           Shared Agentic Loop             |
    |  screenshot -> Gemini -> function calls   |
    |  -> executor -> screenshot -> repeat...   |
    +-------------------------------------------+
```

### Data Flow: Research -> CAD Pipeline

```
User: "Make a phone holder for a bicycle"
  |
  +- Planner._plan() -> Gemini classifies as "research+cad"
  |
  +- Phase 1: ResearchAgent
  |   +- Opens Chrome -> Googles "bicycle handlebar dimensions"
  |   +- Reads multiple websites, extracts data points
  |   +- Returns: {data_points: [{fact: "handlebar diameter", value: "25.4", unit: "mm"}, ...]}
  |   +- DocumentationAgent auto-generates Word + PDF report
  |
  +- Phase 2: Planner._extract_dimensions()
  |   +- Gemini extracts CAD-relevant params: {handlebar_diameter: "25.4mm", phone_width: "73mm"}
  |
  +- Phase 3: CADAgent
      +- Gets enriched description + real dimensions
      +- Opens FreeCAD, creates sketches, applies constraints
      +- Builds 3D model using researched specifications
```

---

## Demo

The demo showcases the full multi-agent system:

1. **Research Agent** — browses the web in Chrome to find real-world dimensions and specifications
2. **Documentation Agent** — automatically generates a Word + PDF report from research findings
3. **CAD Agent** — drives FreeCAD autonomously through pure GUI interaction to build 3D models

### Demo Commands

```bash
# Research + Documentation: find real-world specs, generate report
python3 main.py "Research the standard dimensions of an M8 hex bolt"

# Research -> CAD pipeline: research dimensions, then build in FreeCAD
python3 main.py "Make a phone holder for a bicycle"

# CAD only (dimensions already provided): build directly in FreeCAD
python3 main.py "Make a simple box for storing items 25x25mm"

# CAD only: cylinder with hole
python3 main.py "Make a cylinder with a 30mm diameter hole through the center"
```

### What to Expect

**Research tasks:**
1. The Planner routes to the Research agent
2. Chrome opens, the agent searches Google, reads multiple pages
3. Structured data points are extracted with confidence scores and sources
4. The Documentation agent automatically generates Word (.docx) and PDF reports in `outputs/research_results/`

**CAD tasks:**
1. The Planner classifies the request and extracts dimensions
2. FreeCAD opens (or the agent opens it via the Applications menu)
3. The agent creates a new Body, enters the Sketcher, draws geometry
4. Constrains dimensions, closes the sketch, applies Pad/Pocket/Thickness
5. Calls `task_complete()` when finished

**Chained tasks (Research -> CAD):**
1. The Planner detects missing dimensions and routes to `research+cad`
2. Research agent finds real-world specs (e.g., handlebar diameter, phone sizes)
3. Documentation agent saves the report
4. Planner extracts CAD-relevant dimensions from research data
5. CAD agent builds the model using researched specifications

---

## VM Environment Setup

The agent runs on an **Ubuntu Linux virtual machine** with specific display requirements for the Gemini Computer Use model.

### VM Requirements

| Requirement | Specification |
|-------------|--------------|
| **OS** | Ubuntu 22.04+ LTS (Desktop edition) |
| **Desktop** | XFCE (lightweight, uses X11) |
| **Display Server** | X11 (NOT Wayland — xdotool requires X11) |
| **Screen Resolution** | 1280x800 (16:10 aspect ratio) |
| **RAM** | 4 GB minimum, 8 GB recommended |
| **Disk** | 20 GB minimum |
| **Network** | Internet access for Gemini API + web research |

### Why These Specific Settings?

- **1280x800 resolution**: Google recommends 1440x900 for Computer Use. 1280x800 is the closest available VM resolution with the same 16:10 aspect ratio. Screenshots are resized to 1440x900 before sending to Gemini, introducing no distortion.
- **XFCE desktop**: Lightweight, X11-native, predictable UI layout. The system instruction teaches the agent XFCE-specific navigation (Applications menu in top-left, taskbar at top).
- **X11 display server**: Required by `xdotool` for mouse/keyboard input automation. Wayland is not supported.

### Step-by-Step VM Setup

#### 1. Create the VM

Using VirtualBox, VMware, or a cloud provider (GCP, AWS):

```bash
# If using a cloud VM, ensure X11 forwarding or VNC access
# Set display resolution to 1280x800
```

#### 2. Install XFCE Desktop (if not pre-installed)

```bash
sudo apt update
sudo apt install -y xfce4 xfce4-goodies
# Set XFCE as default session at login
```

#### 3. Set Display Resolution

```bash
# Check current resolution
xrandr

# Set to 1280x800
xrandr --output <display-name> --mode 1280x800

# To make permanent, add to ~/.profile or use XFCE Display Settings
```

#### 4. Install System Dependencies

```bash
# Screenshot tool
sudo apt install -y scrot

# X11 input automation
sudo apt install -y xdotool

# Python 3.10+
sudo apt install -y python3 python3-pip python3-venv

# Chromium browser (for Research agent)
sudo apt install -y chromium-browser

# FreeCAD 1.0
sudo apt install -y freecad

# FFmpeg (for video pipeline)
sudo apt install -y ffmpeg
```

#### 5. Verify Display Setup

```bash
# Verify X11 is running
echo $DISPLAY   # Should output ":0" or ":1"

# Verify xdotool works
xdotool getdisplaygeometry   # Should output: 1280 800

# Verify scrot works
scrot /tmp/test_screenshot.png -o
```

### Display Resolution Reference

If you change the VM resolution, update these values in `core/settings.py`:

```python
# Actual VM screen dimensions
SCREEN_WIDTH = 1280    # <- Change to match your VM
SCREEN_HEIGHT = 800    # <- Change to match your VM

# Model screenshot dimensions (keep at 1440x900 for best results)
MODEL_SCREEN_WIDTH = 1440
MODEL_SCREEN_HEIGHT = 900
```

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/Louisomeg/General_Computer_Use_Agent-.git
cd General_Computer_Use_Agent-
git checkout design
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

**Key Dependencies:**

| Package | Purpose |
|---------|---------|
| `google-genai` | Google Gemini API client (Computer Use, vision, text generation) |
| `termcolor` | Colored terminal output for agent logs |
| `pyyaml` | YAML skill file parsing |
| `playwright` | Browser automation for Research agent |
| `fpdf2` | PDF report generation |
| `python-docx` | Word document generation |
| `Pillow` | Screenshot resizing (1280x800 -> 1440x900) |

### 4. Install Playwright Browsers

```bash
python -m playwright install chromium
```

### 5. Set Up API Key

```bash
export GEMINI_API_KEY="your-google-gemini-api-key"

# Add to ~/.bashrc for persistence:
echo 'export GEMINI_API_KEY="your-key"' >> ~/.bashrc
```

Get your API key from [Google AI Studio](https://aistudio.google.com/apikey).

### 6. Verify Installation

```bash
# Test executor (works on any OS -- no xdotool needed)
python test_executor.py

# Test research agent (needs API key + Playwright)
python test_research.py --quick
```

---

## Quick Start

### Interactive Mode

```bash
python main.py
```

This opens an interactive REPL where you can type requests:

```
Agentic Planner -- type a request or 'quit' to exit

>>> Create a 50mm tall cylinder with radius 15mm
>>> Research M6 bolt dimensions
>>> Design a phone holder for a bicycle handlebar
>>> quit
```

### Direct CLI Mode

```bash
# CAD task (dimensions provided -> routes to CAD agent directly)
python main.py "Create a 30mm cube in FreeCAD"

# Research task (information lookup -> routes to Research agent)
python main.py "What are the standard dimensions of an M8 hex bolt?"

# Design task without dimensions (-> Research + CAD pipeline)
python main.py "Make a phone holder for a bicycle"
```

---

## Agents

### CAD Agent

**File:** `agents/cad_agent.py`

The CAD agent drives FreeCAD through the desktop GUI using vision-based interaction. It sees the FreeCAD window through screenshots, reasons about what to do next, and clicks menus, draws geometry, and applies operations.

**Capabilities:**
- Create 3D parts from descriptions and dimensions
- Draw 2D sketches with geometry and constraints
- Apply Part Design operations (Pad, Pocket, Thickness, Fillet, Chamfer)
- Navigate FreeCAD menus and dialogs
- Handle error recovery (undo mistakes, close unexpected dialogs)

**Key Design Decisions:**
- **Menu-driven interaction**: The agent is instructed to ALWAYS use FreeCAD's menu bar (large text targets) instead of tiny toolbar icons (~24px). This dramatically improves click accuracy.
- **Minimal system instruction**: Only ~130 lines of base desktop navigation. All FreeCAD-specific intelligence comes from the Planner's action plan.
- **Thickness over Pocket for hollowing**: For hollow shapes (boxes, trays, U-channels), the Planner generates workflows using the Thickness tool (select face -> one click) rather than Pocket (sketch on face -> draw rectangle -> constrain -> pocket). Thickness completes in ~24 turns; Pocket regularly fails at 65+ turns.

**Configuration:**
- `max_turns`: 120 (maximum screenshot-action cycles before stopping)
- Model: `gemini-3-flash-preview` (via Computer Use API)

**How It Works:**

```
1. Planner creates a Task with description + dimensions + step-by-step workflow
2. CAD agent cleans FreeCAD recovery files (prevents recovery dialog)
3. Builds prompt from task description and dimensions
4. Runs agentic loop: screenshot -> Gemini -> function calls -> execute -> repeat
5. Agent calls task_complete() when done, or stops at max_turns
```

### Research Agent

**File:** `agents/research_agent.py`

The Research agent browses the web using a Playwright-controlled Chrome browser. It searches Google, clicks links, reads pages, and extracts structured data points.

**Capabilities:**
- Web search and multi-page browsing
- Structured data extraction with confidence scoring
- Source URL tracking for citations
- Parallel mode: multiple browsers researching different sub-questions simultaneously
- Automatic report generation via Documentation agent

**Output Format:**

```json
{
  "query": "M6 bolt dimensions",
  "findings": {
    "summary": "Standard M6 hex bolt dimensions...",
    "data_points": [
      {"fact": "Thread diameter", "value": "6", "unit": "mm", "source": "https://..."},
      {"fact": "Head width (across flats)", "value": "10", "unit": "mm", "source": "https://..."}
    ],
    "confidence": "high",
    "sources": ["https://...", "https://..."],
    "gaps": ["Torque specifications not found"]
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

The Planner (`core/agentic_planner.py`) orchestrates multi-agent workflows. It uses Gemini 3.1 Pro (text-only model) to classify incoming requests and route them to the appropriate agent(s).

### Routing Logic

| Request Type | Route | Example |
|-------------|-------|---------|
| Exact dimensions provided | `cad` only | "Create a 50mm cylinder with 15mm radius" |
| Information lookup | `research` only | "What are M8 bolt specifications?" |
| Design without dimensions | `research+cad` | "Make a phone holder for a bicycle" |
| Desktop operation | `cad` only | "Open FreeCAD and create a new body" |

### Research -> CAD Pipeline

When the Planner detects a design task without specific dimensions:

1. **Classify**: Gemini reads the request and returns `AGENT: research+cad`
2. **Research Phase**: ResearchAgent browses the web, collects data points
3. **Quality Gate**: Planner checks if research produced useful data
4. **Dimension Extraction**: Gemini reads research data and extracts CAD-relevant dimensions
5. **CAD Phase**: CADAgent receives enriched description + extracted dimensions
6. **Report**: Research results saved to `outputs/research_results/`

### Fallback Routing

If the Gemini API is unavailable for planning, a keyword-based fallback activates:
- "research", "look up", "what is", "specifications" -> `research`
- "design", "make", "build", "create" (without mm/numbers) -> `research+cad`
- Everything else -> `cad` (default to desktop interaction)

---

## The Agentic Loop

**File:** `core/agentic_loop.py`

The agentic loop is the core engine shared by all agents. It implements a multi-turn cycle:

```
+----------------------------------------------+
|              Agentic Loop Cycle               |
|                                               |
|  1. Capture screenshot (scrot -> PNG bytes)   |
|  2. Send to Gemini (screenshot + history)     |
|  3. Gemini returns function calls             |
|  4. Execute function calls via Executor       |
|  5. Append results to conversation history    |
|  6. Repeat until task_complete or max_turns   |
+----------------------------------------------+
```

### Gemini Computer Use Integration

The loop uses Gemini's **Computer Use** tool, which allows the model to:
- See desktop screenshots as images
- Output function calls like `click_at(x=450, y=300)`, `type_text_at(x=200, y=150, text="30 mm")`
- Use a normalized 0-1000 coordinate grid for all mouse actions
- Reason visually about UI state and plan next actions

### Error Recovery Mechanisms

| Scenario | Recovery |
|----------|----------|
| 400 INVALID_ARGUMENT | Reset history to initial prompt + fresh screenshot |
| Empty model response | Update screenshot in-place, retry |
| Malformed function calls | Pop orphaned model content, update screenshot |
| Stuck (same screenshot repeated) | Inject warning message |
| Max empty retries (3) | Return "empty_responses" status |
| Max consecutive errors (5) | Return "api_error" status |
| Max turns reached | Return "max_turns" status |

---

## Shape Decomposition & Planner Intelligence

The Planner does more than route requests — it generates **detailed action plans** tailored to each shape type. This is critical because the vision model (Gemini Flash) works best with clear, step-by-step instructions.

### How the Planner Builds CAD Plans

1. **Shape Classification**: Gemini 3.1 Pro analyzes the user request and identifies the shape type (box, cylinder, L-bracket, U-channel, etc.)
2. **Dimension Extraction**: Pulls out all numeric dimensions and assigns semantic meaning
3. **Workflow Generation**: Creates a step-by-step FreeCAD workflow specific to that shape
4. **Decomposition**: Complex shapes are broken into sequences of simple operations

### Shape Decomposition Examples

**L-Bracket (50x30x5mm):**
```
Step 1: Create body -> Sketch on XY plane -> Rectangle 50x30mm -> Close -> Pad 5mm
Step 2: Sketch on top face -> Rectangle for cutout -> Close -> Pocket (cut away material)
Result: L-shaped bracket from two operations on a single block
```

**U-Channel / Tray (50x30x5mm walls):**
```
Step 1: Create body -> Sketch on XY plane -> Rectangle 50x30mm -> Close -> Pad 30mm
Step 2: Click the top face -> Thickness tool -> Set to 5mm -> OK
Result: Open-top U-channel with 5mm thick walls
```

**Hollow Box (25x25mm):**
```
Step 1: Sketch rectangle -> Pad to height -> Click top face -> Thickness tool -> OK
Result: Storage box in ~24 turns
```

### Why Thickness Over Pocket

For hollow shapes, we discovered that **Thickness** (one-click face hollowing) massively outperforms **Pocket** (sketch-on-face workflow):

| Approach | Steps | Turns | Success Rate |
|----------|-------|-------|-------------|
| Thickness | Select face -> Thickness tool -> set value -> OK | ~24 | High |
| Pocket | Sketch on face -> draw rectangle -> constrain all edges -> close -> pocket | 65+ | Low |

The Pocket approach fails because the model struggles with:
- Creating a sketch on an existing face (coordinate precision)
- Drawing a properly offset rectangle inside the face
- Constraining all four edges with correct offsets

---

## Skill Learning Pipeline

**Directory:** `pipeline/`

The Skill Learning Pipeline converts YouTube FreeCAD tutorial videos into structured YAML skill files. These skills provide the agent with FreeCAD knowledge, tips, troubleshooting guidance, and visual demonstrations.

### Pipeline Stages

```
YouTube URL
    |
    v
+---------------------------------------------+
| Stage 1: CRAWL                              |
| Download video + subtitles via yt-dlp       |
| Format: h264 <=720p (AV1 not supported)    |
| Output: pipeline/downloads/<video_id>/      |
+---------------------+-----------------------+
                      v
+---------------------------------------------+
| Stage 2: TRANSCRIBE                         |
| Extract subtitles from VTT files            |
| Fallback: Whisper ASR (speech-to-text)      |
| Output: segments with timestamps            |
+---------------------+-----------------------+
                      v
+---------------------------------------------+
| Stage 3: KEYFRAMES                          |
| OpenCV MOG2 background subtraction          |
| Detect GUI state changes (menus, dialogs)   |
| Mask FreeCAD 3D viewport (ignore rotation)  |
| Output: numbered PNG keyframes              |
+---------------------+-----------------------+
                      v
+---------------------------------------------+
| Stage 4: LABEL                              |
| Send consecutive keyframe pairs to Gemini   |
| + transcript context for that time range    |
| Ask: "What action happened between frames?" |
| Output: labeled action descriptions         |
+---------------------+-----------------------+
                      v
+---------------------------------------------+
| Stage 5: FILTER                             |
| Gemini Vision scores each action 0-5        |
| Filter out low-quality actions (< 3)        |
| Output: filtered action list                |
+---------------------+-----------------------+
                      v
+---------------------------------------------+
| Stage 6: BUILD                              |
| Assemble into YAML skill file + PNG dir     |
| Update skills/freecad/demos/index.yaml      |
| Output: skills/freecad/demos/<name>/        |
|         +-- skill.yaml                      |
|         +-- *.png (keyframe screenshots)    |
+---------------------------------------------+
```

### Running the Pipeline

```bash
# Full pipeline from YouTube URL
python -m pipeline.run_pipeline --url "https://www.youtube.com/watch?v=VIDEO_ID"

# Run specific stages only
python -m pipeline.run_pipeline --url "VIDEO_ID" --stages keyframes,label,filter,build

# From already-downloaded video
python -m pipeline.run_pipeline --dir pipeline/downloads/VIDEO_ID

# Rebuild skill index only
python -m pipeline.run_pipeline --rebuild-index
```

### Pipeline Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold` | 15000 | MOG2 keyframe detection sensitivity |
| `min_score` | 3 | Minimum quality score (0-5) for filtering |
| `api_delay` | 1.0s | Delay between Gemini API calls |
| `max_duration_s` | 1200 | Maximum video length (20 minutes) |
| Video format | h264, <=720p | AV1 codec not supported on most VMs |

### Skill Types

| Type | Purpose |
|------|---------|
| `tutorial` | General FreeCAD workflows with tips and troubleshooting |
| `knowledge` | Specific operation details (Pad, Sketch, constraints) |
| `demonstration` | Visual examples from processed tutorials (YAML + PNGs) |
| `enrichments` | Additional tips/troubleshooting from tutorials |

### Current Status

The skill system is currently **disabled in the CAD agent** because testing showed that the minimal-instruction approach (short system prompt + detailed Planner action plans) outperforms injecting large skill references into the prompt. However, the pipeline and skill infrastructure remain fully functional and will become increasingly valuable as stronger models (capable of processing longer contexts without confusion) become available for Computer Use.

---

## Coordinate System & Executors

### Coordinate System

The Gemini Computer Use model uses a **normalized 0-1000 grid** for all coordinates:

```
(0, 0) -------------------- (999, 0)
  |                              |
  |     Normalized 1000x1000     |
  |          Grid                |
  |        (500, 500)            |
  |         = center             |
  |                              |
(0, 999) ------------------ (999, 999)
```

These are converted to actual screen pixels by the executor:

```
screen_x = int(normalized_x / 1000 * SCREEN_WIDTH)   # e.g., 500/1000 * 1280 = 640
screen_y = int(normalized_y / 1000 * SCREEN_HEIGHT)   # e.g., 500/1000 * 800  = 400
```

### Desktop Executor

**File:** `core/desktop_executor.py`

Controls the Ubuntu desktop via `xdotool` subprocess calls.

**Supported Functions:**

| Function | Description |
|----------|-------------|
| `click_at(x, y)` | Left-click at normalized coordinates |
| `hover_at(x, y)` | Move mouse to coordinates |
| `type_text_at(x, y, text)` | Click field, optionally clear, type text |
| `key_combination(keys)` | Press key combo (e.g., "ctrl+z", "escape") |
| `scroll_at(x, y, direction, magnitude)` | Scroll at position |
| `drag_and_drop(x, y, dest_x, dest_y)` | Drag from one point to another |
| `right_click_at(x, y)` | Right-click (custom function) |
| `double_click_at(x, y)` | Double-click (custom function) |
| `wait_5_seconds()` | Wait for UI to settle |
| `task_complete(summary)` | Signal task completion |

### Browser Executor

**File:** `core/browser_executor.py`

Controls a Playwright Chromium browser for the Research agent. Same Executor interface but translates function calls to browser actions.

---

## Project Structure

```
General_Computer_Use_Agent-/
|
+-- main.py                      # Entry point (CLI + interactive REPL)
+-- requirements.txt             # Python dependencies
+-- test_executor.py             # Desktop executor unit tests
+-- test_research.py             # Research agent integration test CLI
|
+-- agents/                      # Agent implementations
|   +-- registry.py              # @register decorator + get_agent() factory
|   +-- cad_agent.py             # FreeCAD CAD design agent
|   +-- research_agent.py        # Web research agent (Chrome + Playwright)
|   +-- documentation_agent.py   # Word + PDF report generator
|
+-- core/                        # Shared infrastructure
|   +-- agentic_loop.py          # Multi-turn vision loop (Gemini)
|   +-- agentic_planner.py       # Task router + shape decomposition + workflow generation
|   +-- executor.py              # Abstract Executor base class
|   +-- desktop_executor.py      # xdotool-based desktop executor
|   +-- browser_executor.py      # Playwright-based browser executor
|   +-- screenshot.py            # scrot capture + PIL resize
|   +-- settings.py              # Global config (resolution, models, delays)
|   +-- models.py                # Task, TaskStatus, data models
|   +-- custom_tools.py          # Extra Gemini FunctionDeclarations
|   +-- freecad_functions.py     # Low-level xdotool wrappers (click, scroll)
|   +-- skill_retrieval.py       # Keyword-based demo skill matching
|
+-- pipeline/                    # YouTube -> Skill learning pipeline
|   +-- run_pipeline.py          # Pipeline orchestrator CLI
|   +-- crawl.py                 # yt-dlp video + subtitle download
|   +-- transcribe.py            # VTT subtitle extraction / Whisper ASR
|   +-- extract_keyframes.py     # OpenCV MOG2 keyframe detection
|   +-- label_actions.py         # Gemini Vision action labeling
|   +-- filter_quality.py        # Gemini Vision quality scoring
|   +-- build_skills.py          # YAML skill assembly + index update
|
+-- skills/                      # FreeCAD knowledge base (reference, currently disabled)
|   +-- freecad/
|       +-- *.yaml               # Knowledge + tutorial skill files
|       +-- demos/               # Generated demonstration skills (YAML + PNG)
|
+-- outputs/
    +-- research_results/        # Research JSON + Word + PDF reports
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
| `ACTION_DELAY` | 0.5s | Pause after each executed action |
| `TYPING_DELAY` | 30ms | Delay between keystrokes (xdotool) |
| `CLICK_DELAY` | 0.3s | Pause after mouse clicks |
| `DEFAULT_MODEL` | `gemini-3-flash-preview` | Computer Use model for all agents |
| `PLANNING_MODEL` | `gemini-3.1-pro-preview` | Text-only model for planning and dimension extraction |
| `SCREENSHOT_PATH` | `/tmp/agent_screenshot.png` | Temporary screenshot file path |

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Google Gemini API key |
| `DISPLAY` | Yes (auto) | X11 display (usually `:0`, set automatically) |

---

## Known Limitations

These are limitations discovered through extensive testing with the current best model (`gemini-3-flash-preview`):

### Model Limitations

1. **Polyline / multi-point geometry**: Flash cannot reliably use FreeCAD's polyline tool (click series of points to form a shape). It loses track of which point comes next and misclicks. Workaround: decompose into individual lines or use simpler primitives (rectangle, circle).

2. **Sketch-on-face workflows**: Creating a new sketch on an existing 3D face, then drawing constrained geometry on it, is unreliable. The model struggles with the coordinate precision needed to click exactly on a face. Workaround: use Thickness tool instead of Pocket for hollowing.

3. **Three-level submenu navigation**: XFCE's `Applications -> Category -> App` menu requires hovering to open submenus. The model sometimes clicks too early or on the wrong item. If the app is already in the taskbar, clicking the taskbar entry is more reliable.

4. **Small toolbar icons (~24px)**: Click accuracy drops significantly on small targets. The system instruction mandates using the menu bar (large text targets) instead. This is one of the most impactful design decisions.

5. **Complex multi-step designs (80+ turns)**: Success rate drops for designs requiring many sequential precise operations. Simple shapes (box, cylinder) succeed reliably; complex shapes (L-bracket, detailed assemblies) may need multiple attempts.

6. **Rate limits**: On Gemini's free tier, heavy Computer Use sessions (20-80+ turns of screenshot + vision calls) can exhaust quotas quickly. Rate limits typically reset within 30-60 minutes.

### Architectural Limitations

1. **No undo intelligence**: The agent can press Ctrl+Z but doesn't strategically plan recovery. If it goes down a wrong path for 10+ turns, it may not recover.

2. **No verification**: The agent doesn't compare the final model against the original spec. It relies on the vision model's judgment of "looks done."

3. **Single-monitor only**: The system assumes a single display. Multi-monitor setups would need coordinate mapping changes.

---

## Future Work — Stronger Models

The current system is built on `gemini-3-flash-preview`, which is the best available Computer Use model for desktop applications. However, the architecture is designed to scale with model improvements:

### What a Stronger Model (e.g., Gemini 3.1 Pro with CU) Would Unlock

1. **Complex geometry in one shot**: L-brackets, T-brackets, and multi-feature parts currently require shape decomposition by the Planner. A model with better spatial reasoning could handle polylines, sketch-on-face, and multi-step constraint workflows directly.

2. **Longer reliable sessions**: Currently, accuracy degrades after ~60-80 turns. A stronger model could maintain precision across 150+ turns, enabling full assemblies and multi-part designs.

3. **Sketch-on-face workflows**: The Pocket approach (sketch on existing face, draw offset rectangle, constrain, pocket) would work reliably, eliminating the need for Thickness workarounds.

4. **Reduced Planner complexity**: With a smarter CU model, the Planner could send simpler instructions (just "make a U-channel with 5mm walls") instead of generating step-by-step Thickness workflows. The model itself would know the best approach.

5. **Better error recovery**: A stronger model could recognize when it's going down a wrong path and strategically undo multiple steps, rather than continuing to click on incorrect targets.

### Leveraging the Skill Learning Pipeline

The [Skill Learning Pipeline](#skill-learning-pipeline) is fully built and functional. With a stronger model, the skills it generates could be:
- Injected directly into the CAD agent's prompt as reference knowledge
- Used to auto-generate Planner workflows from tutorial demonstrations
- Used as training data for fine-tuned models specialized in CAD operations

---

## Troubleshooting

### Common Issues

**"ERROR: Set GEMINI_API_KEY first!"**
```bash
export GEMINI_API_KEY="your-key"
```

**"xdotool: command not found"**
```bash
sudo apt install xdotool
```

**"scrot: command not found"**
```bash
sudo apt install scrot
```

**"No protocol specified" / "Cannot open display"**
- Ensure you're running in an X11 session (not SSH without forwarding)
- Check: `echo $DISPLAY` should output `:0` or similar
- If using SSH: `ssh -X user@vm` to enable X11 forwarding

**FreeCAD "Document Recovery" dialog appears every time**
- The agent cleans recovery files automatically, but if it persists:
```bash
rm -rf ~/.local/share/FreeCAD/recovery/*
rm -rf ~/.FreeCAD/recovery/*
```

**Research agent: "Playwright not installed"**
```bash
python -m playwright install chromium
```

**CAD agent hits max_turns without finishing**
- Complex designs may need 150+ turns
- Increase `max_turns` in `agents/cad_agent.py` (default: 120)
- Consider simplifying the design request or providing more specific dimensions

**400 INVALID_ARGUMENT from Gemini API**
- Handled automatically by history reset in the agentic loop
- If persistent, check that no code is fabricating model Content objects

**Rate limit errors (429)**
- Free tier quotas reset within 30-60 minutes
- Reduce `max_turns` for testing
- Consider a paid API tier for heavy usage

---

## Authors

- **Louis** — Core framework, desktop executor, CAD agent, agentic loop, planner
- **Emmanuel** — Research agent, browser executor, documentation agent, parallel research

---

## License

This project is part of an academic submission. See repository for license details.
