# General Computer Use Agent

A multi-agent system that autonomously operates an Ubuntu Linux desktop to perform engineering design tasks. The system uses **Google Gemini's Computer Use API** (vision model) to see the screen, reason about what to do, and control the mouse/keyboard to drive applications like **FreeCAD** and **Google Chrome** — all without any application-specific APIs or scripting.

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
- [VM Environment Setup](#vm-environment-setup)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Agents](#agents)
  - [CAD Agent](#cad-agent)
  - [Research Agent](#research-agent)
  - [Documentation Agent](#documentation-agent)
- [Multi-Agent Workflow](#multi-agent-workflow)
- [The Agentic Loop](#the-agentic-loop)
- [Skill Learning Pipeline](#skill-learning-pipeline)
- [Skill System](#skill-system)
- [Coordinate System & Executors](#coordinate-system--executors)
- [Project Structure](#project-structure)
- [Configuration Reference](#configuration-reference)
- [API & Tool Reference](#api--tool-reference)
- [Error Handling & Recovery](#error-handling--recovery)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

---

## Overview

This project demonstrates a **general-purpose computer use agent** that can:

1. **Design 3D parts in FreeCAD** — The CAD agent sees the FreeCAD GUI through screenshots, clicks menus, draws sketches, applies constraints, and performs Part Design operations (Pad, Pocket, Fillet, etc.) just like a human would.

2. **Research information online** — The Research agent opens Google Chrome via Playwright, searches the web, reads pages, and extracts structured data with confidence scores and source URLs.

3. **Generate professional reports** — The Documentation agent converts raw research data into formatted Word (.docx) and PDF documents with tables, sections, and citations.

4. **Chain agents together** — The Planner can route a request like *"Make a phone holder for a bicycle"* through Research (find handlebar/phone dimensions) → Documentation (save report) → CAD (build the 3D model with real dimensions).

5. **Learn from YouTube tutorials** — The Skill Learning Pipeline processes FreeCAD tutorial videos into structured YAML skill files that teach the agent new CAD techniques.

### Key Technologies

| Component | Technology |
|-----------|-----------|
| Vision Model | Google Gemini 3 Flash Preview (`gemini-3-flash-preview`) |
| Desktop Control | xdotool (X11 input automation) |
| Screenshots | scrot + PIL (resize to 1440x900) |
| Browser Control | Playwright (Chromium) |
| CAD Application | FreeCAD 1.0 |
| Video Processing | OpenCV, yt-dlp, Whisper ASR |
| Document Generation | fpdf2 (PDF), python-docx (Word) |
| VM Environment | Ubuntu Linux, XFCE desktop, X11 display server |

---

## System Architecture

```
                          ┌──────────────┐
                          │   main.py    │
                          │  (CLI/REPL)  │
                          └──────┬───────┘
                                 │ user request
                                 ▼
                          ┌──────────────┐
                          │   Planner    │  ← Uses Gemini to classify task
                          │  (Router)    │    and extract parameters
                          └──────┬───────┘
                     ┌───────────┼───────────┐
                     ▼           ▼           ▼
              ┌────────┐  ┌──────────┐  ┌────────────────┐
              │  CAD   │  │ Research │  │ Research → CAD  │
              │ Agent  │  │  Agent   │  │   (chained)    │
              └───┬────┘  └────┬─────┘  └────────────────┘
                  │            │
                  ▼            ▼
           ┌───────────┐ ┌────────────┐
           │  Desktop   │ │  Browser   │
           │ Executor   │ │ Executor   │
           │ (xdotool)  │ │(Playwright)│
           └───────────┘ └────────────┘
                  │            │
                  ▼            ▼
           ┌───────────┐ ┌────────────┐
           │  FreeCAD   │ │   Chrome   │
           │   (GUI)    │ │ (headless) │
           └───────────┘ └────────────┘

    ┌─────────────────────────────────────────┐
    │           Shared Agentic Loop           │
    │  screenshot → Gemini → function calls   │
    │  → executor → screenshot → repeat...    │
    └─────────────────────────────────────────┘
```

### Data Flow: Research → CAD Pipeline

```
User: "Make a phone holder for a bicycle"
  │
  ├─ Planner._plan() → Gemini classifies as "research+cad"
  │
  ├─ Phase 1: ResearchAgent
  │   ├─ Opens Chrome → Googles "bicycle handlebar dimensions"
  │   ├─ Reads multiple websites, extracts data points
  │   ├─ Returns: {data_points: [{fact: "handlebar diameter", value: "25.4", unit: "mm"}, ...]}
  │   └─ DocumentationAgent auto-generates Word + PDF report
  │
  ├─ Phase 2: Planner._extract_dimensions()
  │   └─ Gemini extracts CAD-relevant params: {handlebar_diameter: "25.4mm", phone_width: "73mm"}
  │
  └─ Phase 3: CADAgent
      ├─ Gets enriched description + real dimensions
      ├─ Opens FreeCAD, creates sketches, applies constraints
      └─ Builds 3D model using researched specifications
```

---

## VM Environment Setup

The agent runs on an **Ubuntu Linux virtual machine** with specific display requirements for the Gemini Computer Use model. This section covers everything you need to set up the VM from scratch.

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
# Or install from PPA for latest version:
# sudo add-apt-repository ppa:freecad-maintainers/freecad-stable
# sudo apt update && sudo apt install freecad

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
SCREEN_WIDTH = 1280    # ← Change to match your VM
SCREEN_HEIGHT = 800    # ← Change to match your VM

# Model screenshot dimensions (keep at 1440x900 for best results)
MODEL_SCREEN_WIDTH = 1440
MODEL_SCREEN_HEIGHT = 900
```

The system automatically resizes screenshots from VM resolution to model resolution using PIL. Both 1280x800 and 1440x900 are 16:10 aspect ratio, so no distortion occurs.

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

**Dependencies:**

| Package | Purpose |
|---------|---------|
| `google-genai` | Google Gemini API client (Computer Use, vision, text generation) |
| `termcolor` | Colored terminal output for agent logs |
| `pyyaml` | YAML skill file parsing |
| `playwright` | Browser automation for Research agent |
| `fpdf2` | PDF report generation |
| `python-docx` | Word document generation |
| `Pillow` | Screenshot resizing (1280x800 → 1440x900) |
| `youtube-transcript-api` | YouTube subtitle extraction |
| `yt-dlp` | YouTube video downloading |
| `opencv-python` | Keyframe extraction (MOG2 background subtraction) |
| `openai-whisper` | Speech-to-text fallback for videos without subtitles |

### 4. Install Playwright Browsers

```bash
python -m playwright install chromium
```

### 5. Set Up Gemini API Key

```bash
export GEMINI_API_KEY="your-google-gemini-api-key"

# Add to ~/.bashrc for persistence:
echo 'export GEMINI_API_KEY="your-key"' >> ~/.bashrc
```

Get your API key from [Google AI Studio](https://aistudio.google.com/apikey).

### 6. Verify Installation

```bash
# Test executor (works on any OS — no xdotool needed)
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
Agentic Planner — type a request or 'quit' to exit

>>> Create a 50mm tall cylinder with radius 15mm
>>> Research M6 bolt dimensions
>>> Design a phone holder for a bicycle handlebar
>>> Open FreeCAD and create a new Part Design body
>>> quit
```

### Direct CLI Mode

```bash
# CAD task (dimensions provided → CAD agent directly)
python main.py "Create a 30mm cube in FreeCAD"

# Research task (information lookup → Research agent)
python main.py "What are the standard dimensions of an M8 hex bolt?"

# Design task without dimensions (→ Research + CAD pipeline)
python main.py "Make a phone holder for a bicycle"
```

### Run Individual Agents

```bash
# Research agent with custom query
python test_research.py --query "M10 bolt head diameter and thread pitch"

# Research agent with more turns
python test_research.py --query "bicycle handlebar standards" --max-turns 30

# Parallel research (multiple browsers)
python test_research.py --parallel
```

---

## Agents

### CAD Agent

**File:** `agents/cad_agent.py`

The CAD agent drives FreeCAD through the desktop GUI using vision-based interaction. It sees the FreeCAD window through screenshots, reasons about what to do next, and clicks menus, draws geometry, and applies operations.

**Capabilities:**
- Create 3D parts from descriptions and dimensions
- Draw 2D sketches with geometry and constraints
- Apply Part Design operations (Pad, Pocket, Fillet, Chamfer, etc.)
- Navigate FreeCAD menus and dialogs
- Handle error recovery (undo mistakes, close unexpected dialogs)

**Key Design Decisions:**
- **Menu-driven interaction**: The agent is instructed to ALWAYS use FreeCAD's menu bar (large text targets) instead of tiny toolbar icons (~24px). This dramatically improves click accuracy.
- **Two-click workflows**: Detailed instructions for FreeCAD's sketch tools (Rectangle: click corner 1 → click corner 2; Circle: click center → click radius point).
- **Constraint workflow**: After drawing geometry, immediately constrain dimensions via Sketch → Sketcher constraints → type value with "mm" units.
- **Error recovery**: Ctrl+Z for undo, Escape to cancel tools, Sketch → Close sketch to exit sketcher. Never use the Delete key.

**Configuration:**
- `max_turns`: 120 (maximum screenshot-action cycles before stopping)
- System instruction: Base desktop instruction + CAD-specific addendum (167 lines of FreeCAD guidance)

**How It Works:**

```
1. Planner creates a Task with description + dimensions
2. CAD agent cleans FreeCAD recovery files (prevents recovery dialog)
3. Builds prompt: task description + dimensions + tutorial tips + demo images
4. Runs agentic loop: screenshot → Gemini → function calls → execute → repeat
5. Agent calls task_complete() when done, or hits max_turns
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

**Modes:**

| Mode | Description |
|------|-------------|
| Single | One browser, sequential page visits (default) |
| Parallel | Multiple browsers, each researching a sub-question concurrently |

**How It Works:**

```
1. Uses Gemini to generate a research plan (sub-questions to investigate)
2. Opens Chrome via Playwright to Google.com
3. Agentic loop: screenshot → Gemini → browser actions (click, type, scroll)
4. Model calls report_findings() when it has enough data
5. Results saved as JSON to outputs/research_results/
6. DocumentationAgent automatically generates Word + PDF report
```

### Documentation Agent

**File:** `agents/documentation_agent.py`

Converts raw research JSON into professionally formatted documents. Automatically called by the Research agent after data collection.

**Output Formats:**
- **Word Document (.docx)**: Full report with headers, tables, styled text, citations
- **PDF Document (.pdf)**: Matching PDF with tables and formatted sections

**Features:**
- Executive summary generated by Gemini from raw data points
- Data tables with fact/value/unit/source columns
- Source list with clickable URLs
- Confidence assessment section
- Knowledge gaps section
- Auto-installs fpdf2 and python-docx if missing

**Output Location:** `outputs/research_results/`

---

## Multi-Agent Workflow

The Planner (`core/agentic_planner.py`) orchestrates multi-agent workflows. It uses Gemini to classify incoming requests and route them to the appropriate agent(s).

### Routing Logic

| Request Type | Route | Example |
|-------------|-------|---------|
| Exact dimensions provided | `cad` only | "Create a 50mm cylinder with 15mm radius" |
| Information lookup | `research` only | "What are M8 bolt specifications?" |
| Design without dimensions | `research+cad` | "Make a phone holder for a bicycle" |
| Desktop operation | `cad` only | "Open FreeCAD and create a new body" |

### Research → CAD Pipeline

When the Planner detects a design task without specific dimensions:

1. **Classify**: Gemini reads the request and returns `AGENT: research+cad`
2. **Research Phase**: ResearchAgent browses the web, collects data points
3. **Quality Gate**: Planner checks if research produced useful data (data_points exist, confidence not "low")
4. **Dimension Extraction**: Gemini reads research data and extracts CAD-relevant dimensions as `key=value` pairs
5. **CAD Phase**: CADAgent receives enriched description + extracted dimensions
6. **Report**: Results saved to `outputs/research_results/`

### Fallback Routing

If the Gemini API is unavailable for planning, a keyword-based fallback activates:
- "research", "look up", "what is", "specifications" → `research`
- "design", "make", "build", "create" (without mm/numbers) → `research+cad`
- Everything else → `cad` (default to desktop interaction)

---

## The Agentic Loop

**File:** `core/agentic_loop.py`

The agentic loop is the core engine shared by all agents. It implements a multi-turn cycle:

```
┌──────────────────────────────────────────────┐
│              Agentic Loop Cycle               │
│                                               │
│  1. Capture screenshot (scrot → PNG bytes)    │
│  2. Send to Gemini (screenshot + history)     │
│  3. Gemini returns function calls             │
│  4. Execute function calls via Executor       │
│  5. Append results to conversation history    │
│  6. Repeat until task_complete or max_turns   │
└──────────────────────────────────────────────┘
```

### Gemini Computer Use Integration

The loop uses Gemini's **Computer Use** tool, which allows the model to:
- See desktop screenshots as images
- Output function calls like `click_at(x=450, y=300)`, `type_text_at(x=200, y=150, text="30 mm")`
- Use a normalized 0-1000 coordinate grid for all mouse actions
- Reason visually about UI state and plan next actions

### Conversation History Management

The loop maintains a strict `user → model → user → model` alternation in the conversation history. This is critical because:

- **Gemini 3 requires strict role alternation** — consecutive messages from the same role cause 400 INVALID_ARGUMENT errors
- **Every function call needs a matching response** — orphaned function calls in history break the API
- **Thought signatures** — Gemini 3 model Content includes internal thought signatures that cannot be fabricated

### Error Recovery Mechanisms

| Scenario | Recovery |
|----------|----------|
| 400 INVALID_ARGUMENT | Reset history to initial prompt + fresh screenshot (one attempt) |
| Empty model response | Update screenshot in last user Content in-place, retry |
| `candidate.content` is None | Treat as empty response, update screenshot, retry |
| Malformed function calls | Pop orphaned model content, update screenshot |
| Stuck (same screenshot repeated) | Inject warning message into existing user Content |
| Max empty retries (3) | Return "empty_responses" status |
| Max consecutive errors (5) | Return "api_error" status |
| Max turns reached | Return "max_turns" status |

### Key Implementation Details

- **Screenshot function**: Pluggable — `capture_desktop_screenshot()` for CAD, browser screenshot for Research
- **Custom declarations**: Additional `FunctionDeclaration` objects beyond Computer Use (e.g., `right_click_at`, `task_complete`, `report_findings`)
- **History reset**: On 400 errors, history is completely reset to `[initial_prompt + fresh_screenshot]` rather than trimmed (trimming breaks function call/response pairing)
- **In-place updates**: When retrying after empty responses, the screenshot in the last user message is replaced rather than creating new history entries (prevents role alternation violations)

---

## Skill Learning Pipeline

**Directory:** `pipeline/`

The Skill Learning Pipeline converts YouTube FreeCAD tutorial videos into structured YAML skill files that the agent can use as reference during CAD tasks.

### Pipeline Stages

```
YouTube URL
    │
    ▼
┌─────────────────────────────────────────────┐
│ Stage 1: CRAWL                              │
│ Download video + subtitles via yt-dlp       │
│ Format: h264 ≤720p (AV1 not supported)      │
│ Output: pipeline/downloads/<video_id>/      │
└───────────────────┬─────────────────────────┘
                    ▼
┌─────────────────────────────────────────────┐
│ Stage 2: TRANSCRIBE                         │
│ Extract subtitles from VTT files            │
│ Fallback: Whisper ASR (speech-to-text)      │
│ Output: segments with timestamps            │
└───────────────────┬─────────────────────────┘
                    ▼
┌─────────────────────────────────────────────┐
│ Stage 3: KEYFRAMES                          │
│ OpenCV MOG2 background subtraction          │
│ Detect GUI state changes (menus, dialogs)   │
│ Mask FreeCAD 3D viewport (ignore rotation)  │
│ Output: numbered PNG keyframes              │
│ Max duration: 1200s (20 minutes)            │
└───────────────────┬─────────────────────────┘
                    ▼
┌─────────────────────────────────────────────┐
│ Stage 4: LABEL                              │
│ Send consecutive keyframe pairs to Gemini   │
│ + transcript context for that time range    │
│ Ask: "What action happened between frames?" │
│ Output: labeled action descriptions         │
└───────────────────┬─────────────────────────┘
                    ▼
┌─────────────────────────────────────────────┐
│ Stage 5: FILTER                             │
│ Gemini Vision scores each action 0-5        │
│ Filter out low-quality actions (< 3)        │
│ Output: filtered action list                │
└───────────────────┬─────────────────────────┘
                    ▼
┌─────────────────────────────────────────────┐
│ Stage 6: BUILD                              │
│ Assemble into YAML skill file + PNG dir     │
│ Update skills/freecad/demos/index.yaml      │
│ Output: skills/freecad/demos/<name>/        │
│         ├── skill.yaml                      │
│         └── *.png (keyframe screenshots)    │
└─────────────────────────────────────────────┘
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
| Video format | h264, ≤720p | AV1 codec not supported on most VMs |

### Important Notes

- **Video codec**: The pipeline forces h264 encoding (`vcodec^=avc1`) because most VMs lack AV1 hardware decoding
- **API costs**: The labeling and filtering stages make many Gemini Vision API calls (one per keyframe pair). Budget accordingly.
- **Whisper fallback**: If the video has no subtitles, Whisper ASR runs locally. This requires ~1GB of model download on first use.
- **Delete old downloads**: If a video was previously downloaded with wrong settings, delete the folder: `rm -rf pipeline/downloads/<video_id>/`

---

## Skill System

**Directory:** `skills/freecad/`

Skills are YAML files that provide the CAD agent with FreeCAD knowledge and demonstrations. They are loaded at task start and injected into the agent's prompt.

### Skill Types

| Type | Purpose | Loaded When |
|------|---------|-------------|
| `tutorial` | General FreeCAD workflows with tips and troubleshooting | Always (injected as tips reference) |
| `knowledge` | Specific operation details (Pad, Sketch, constraints) | At agent startup |
| `demonstration` | Visual examples from processed tutorials (YAML + PNGs) | Matched to task via keyword retrieval |
| `enrichments` | Additional tips/troubleshooting from tutorials | Merged with tutorial tips |

### Available Skills

| Skill File | Description |
|------------|-------------|
| `basic_operations.yaml` | Pad, Chamfer, Fillet, Revolution, Pocket, Mirror, Pattern |
| `sketcher_tools.yaml` | Sketch geometry (Rectangle, Circle, Line) and constraints |
| `sketcher_advanced.yaml` | Polylines, arcs, tangency, construction geometry |
| `part_design_ops.yaml` | Body/Sketch management, Pad, Pocket, dress-up features |
| `part_design_parametric.yaml` | VarSet parametric variables, hole wizard |
| `setup.yaml` | FreeCAD launch, workbench selection, document creation |
| `setup_extended.yaml` | Add-on manager, community workbenches |
| `assembly_basics.yaml` | Assembly operations for multi-part designs |
| `bicycle_stem.yaml` | Complete parametric bicycle stem tutorial |
| `enrichments_from_tutorial.yaml` | Extra tips from tutorial processing |

### Skill Retrieval

When the CAD agent receives a task, it searches for relevant demonstration skills using keyword matching:

1. Task description is tokenized and stopwords removed
2. Each demo skill's tags + description are compared
3. Best match is loaded with up to 3 screenshot images
4. Screenshots are sent to Gemini as visual reference

```python
# Example: Task "Create a cylinder" matches demo with tags ["cylinder", "pad", "sketch"]
from core.skill_retrieval import find_relevant_demo, get_demo_screenshots
demo = find_relevant_demo("Create a cylinder with 10mm radius")
images = get_demo_screenshots(demo, max_screenshots=3)
```

### Creating Custom Skills

Create a YAML file in `skills/freecad/`:

```yaml
name: my_custom_skill
type: knowledge
description: How to create a specific part
operations:
  - name: create_feature
    steps:
      - "Step 1: Do this"
      - "Step 2: Do that"
tips:
  - "Useful tip about this operation"
troubleshooting:
  - problem: "Common issue"
    solution: "How to fix it"
```

---

## Coordinate System & Executors

### Coordinate System

The Gemini Computer Use model uses a **normalized 0-1000 grid** for all coordinates:

```
(0, 0) ──────────────────── (999, 0)
  │                              │
  │     Normalized 1000x1000     │
  │          Grid                │
  │                              │
  │        (500, 500)            │
  │         = center             │
  │                              │
(0, 999) ────────────────── (999, 999)
```

These are converted to actual screen pixels by the executor:

```
screen_x = int(normalized_x / 1000 * SCREEN_WIDTH)   # e.g., 500/1000 * 1280 = 640
screen_y = int(normalized_y / 1000 * SCREEN_HEIGHT)   # e.g., 500/1000 * 800  = 400
```

### Desktop Executor

**File:** `core/desktop_executor.py`

Controls the Ubuntu desktop via `xdotool` subprocess calls. Handles coordinate denormalization and all mouse/keyboard operations.

**Supported Functions:**

| Function | Description |
|----------|-------------|
| `click_at(x, y)` | Left-click at normalized coordinates |
| `hover_at(x, y)` | Move mouse to coordinates |
| `type_text_at(x, y, text)` | Click field, optionally clear, type text |
| `key_combination(keys)` | Press key combo (e.g., "ctrl+z", "escape") |
| `scroll_at(x, y, direction, magnitude)` | Scroll at position |
| `scroll_document(direction)` | Scroll at screen center |
| `drag_and_drop(x, y, dest_x, dest_y)` | Drag from one point to another |
| `right_click_at(x, y)` | Right-click (custom function) |
| `double_click_at(x, y)` | Double-click (custom function) |
| `wait_5_seconds()` | Wait for UI to settle |
| `task_complete(summary)` | Signal task completion |

**Key normalization**: The executor also normalizes X11 key names (e.g., `delete` → `Delete`, `escape` → `Escape`) because xdotool silently ignores lowercase key names.

### Browser Executor

**File:** `core/browser_executor.py`

Controls a Playwright Chromium browser for the Research agent. Same Executor interface but translates function calls to browser actions (click, type, navigate, screenshot).

**Browser viewport**: 1440x900 (matches Gemini's recommended resolution directly).

---

## Project Structure

```
General_Computer_Use_Agent-/
│
├── main.py                      # Entry point (CLI + interactive REPL)
├── requirements.txt             # Python dependencies
├── config.py                    # (Reserved for future configuration)
├── test_executor.py             # Desktop executor unit tests
├── test_research.py             # Research agent integration test CLI
│
├── agents/                      # Agent implementations
│   ├── __init__.py
│   ├── registry.py              # @register decorator + get_agent() factory
│   ├── cad_agent.py             # FreeCAD CAD design agent
│   ├── research_agent.py        # Web research agent (Chrome + Playwright)
│   ├── documentation_agent.py   # Word + PDF report generator
│   ├── skill_translator.py      # YouTube transcript → YAML skill converter
│   ├── testing_agent.py         # (Reserved for testing agent)
│   └── cards/
│       └── cad_agent.yaml       # Agent card (A2A-style metadata)
│
├── core/                        # Shared infrastructure
│   ├── agentic_loop.py          # Multi-turn vision loop (the engine)
│   ├── agentic_planner.py       # Task router + multi-agent orchestration
│   ├── executor.py              # Abstract Executor base class
│   ├── desktop_executor.py      # xdotool-based desktop executor
│   ├── browser_executor.py      # Playwright-based browser executor
│   ├── screenshot.py            # scrot capture + PIL resize
│   ├── settings.py              # Global config (resolution, model, delays)
│   ├── models.py                # Task, TaskStatus, skill loaders
│   ├── custom_tools.py          # Extra Gemini FunctionDeclarations
│   ├── freecad_functions.py     # Low-level xdotool wrappers (click, scroll)
│   └── skill_retrieval.py       # Keyword-based demo skill matching
│
├── pipeline/                    # YouTube → Skill learning pipeline
│   ├── __init__.py
│   ├── run_pipeline.py          # Pipeline orchestrator CLI
│   ├── crawl.py                 # yt-dlp video + subtitle download
│   ├── transcribe.py            # VTT subtitle extraction / Whisper ASR
│   ├── extract_keyframes.py     # OpenCV MOG2 keyframe detection
│   ├── label_actions.py         # Gemini Vision action labeling
│   ├── filter_quality.py        # Gemini Vision quality scoring
│   └── build_skills.py          # YAML skill assembly + index update
│
├── skills/                      # FreeCAD knowledge base
│   └── freecad/
│       ├── *.yaml               # Knowledge + tutorial skill files
│       ├── seed_tasks.txt       # Seed task descriptions for training
│       └── demos/               # Generated demonstration skills (YAML + PNG)
│
├── scripts/
│   ├── deploy.sh                # VM deployment script
│   └── run_agent.py             # (Reserved)
│
├── server/                      # (Reserved for web interface)
│   ├── app.py
│   └── templates/
│       └── index.html
│
└── outputs/
    └── research_results/        # Research JSON + Word + PDF reports
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
| `APP_LAUNCH_DELAY` | 3.0s | Pause after launching applications |
| `SEARCH_TYPE_DELAY` | 1.0s | Pause after typing in launcher |
| `DEFAULT_MODEL` | `gemini-3-flash-preview` | Gemini model for all agents |
| `SCREENSHOT_PATH` | `/tmp/agent_screenshot.png` | Temporary screenshot file path |

### Agent-Specific Settings

| Agent | Setting | Value |
|-------|---------|-------|
| CAD Agent | `max_turns` | 120 |
| Research Agent | `max_turns` | Configurable via params (default 20) |
| Browser Executor | Viewport | 1440x900 |

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Google Gemini API key |
| `DISPLAY` | Yes (auto) | X11 display (usually `:0`, set automatically) |

---

## API & Tool Reference

### Gemini Computer Use Model

The system uses `gemini-3-flash-preview` with the Computer Use tool enabled. The model:

- Receives screenshots as inline PNG images in user messages
- Returns function calls (click, type, scroll, etc.) with normalized coordinates
- Maintains conversation history for multi-turn reasoning
- Includes internal thought signatures in model messages (cannot be fabricated)

### Custom Function Declarations

Beyond the built-in Computer Use functions, the system registers:

| Function | Defined In | Used By |
|----------|-----------|---------|
| `right_click_at(x, y)` | `core/custom_tools.py` | CAD Agent |
| `double_click_at(x, y)` | `core/custom_tools.py` | CAD Agent |
| `task_complete(summary)` | `agents/cad_agent.py` | CAD Agent |
| `report_findings(data)` | `core/agentic_loop.py` | Research Agent |

### Agent Registry

```python
from agents.registry import register, get_agent, list_agents

# Register (decorator in agent files)
@register("cad")
class CADAgent: ...

# Discover
agents = list_agents()  # ["cad", "research"]

# Instantiate
agent = get_agent("cad", client=client, executor=executor)
result = agent.execute(task)
```

---

## Error Handling & Recovery

### Gemini API Errors

| Error | Cause | Recovery |
|-------|-------|----------|
| 400 INVALID_ARGUMENT | Broken role alternation, orphaned function calls, or fabricated model content | History reset to initial prompt + fresh screenshot (single attempt) |
| 429 RESOURCE_EXHAUSTED | API quota exceeded | Caught in loop, logged, retried |
| 500 Server Error | Gemini backend issue | Retry with backoff |

### FreeCAD Errors

| Situation | Recovery |
|-----------|----------|
| Wrong tool activated | Press Escape, then Ctrl+Z multiple times |
| Sketch not closing | Use Sketch → Close sketch (menu), not Escape |
| Recovery dialog on startup | Agent cleans `~/.local/share/FreeCAD/recovery` before each task |
| Misclicked toolbar icon | Agent instructed to always use menu bar (larger targets) |
| Stuck in a loop | Stuck detection injects warning after 3 identical screenshots |

### PDF Generation Errors

| Error | Cause | Fix |
|-------|-------|-----|
| "Not enough horizontal space" | C0/C1 control characters (0x00-0x1f, 0x7f-0x9f) with no glyphs | `safe()` function strips control characters via regex |
| Encoding errors | Non-latin-1 characters | `safe()` encodes to latin-1 with replacement |
| X-position drift | Floating point accumulation in multi_cell | `pdf.set_x(pdf.l_margin)` before every multi_cell() call |

---

## Testing

### Unit Tests

```bash
# Test DesktopExecutor (no xdotool needed — validates logic only)
python test_executor.py
```

This validates:
- Coordinate denormalization (0-1000 → screen pixels)
- Function handler lookup
- Key name normalization (lowercase → X11 keysym)

### Integration Tests

```bash
# Quick research test (5 turns)
python test_research.py --quick

# Engineering-focused test
python test_research.py --engineering

# Custom query with turn limit
python test_research.py --query "titanium alloy properties" --max-turns 15

# Parallel research mode
python test_research.py --parallel
```

### End-to-End Testing

Run on the VM with FreeCAD installed:

```bash
# Simple CAD task
python main.py "Create a 30mm cube in FreeCAD"

# Research + CAD pipeline
python main.py "Design a bracket for an M6 bolt"
```

Monitor output for:
- `[Planner]` — routing decisions
- `[Research Agent]` — data point collection
- `[CAD Agent]` — FreeCAD interaction
- `[Agentic Loop]` — turn counts, error recovery

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

**Pipeline: "Video too long"**
- Maximum video duration is 20 minutes (1200 seconds)
- For longer videos, split them or increase `max_duration_s` in `pipeline/extract_keyframes.py`

**Pipeline: "AV1 codec not supported"**
- The pipeline forces h264 encoding. If you have an old AV1 download:
```bash
rm -rf pipeline/downloads/<video_id>/*.mp4
# Re-run the pipeline
```

**PDF: "Not enough horizontal space to render a single character"**
- This is fixed in the current version. The `safe()` function strips control characters.
- If it recurs, check for non-latin-1 text in research results.

**CAD agent hits max_turns without finishing**
- Increase `max_turns` in `agents/cad_agent.py` (default: 120)
- Complex designs may need 150+ turns
- Check logs for stuck detection warnings

**400 INVALID_ARGUMENT from Gemini API**
- This is handled automatically by history reset
- If persistent, check that no code is fabricating model Content objects
- The agentic loop includes one-shot recovery: reset history and retry

---

## Authors

- **Louis** — Core framework, desktop executor, CAD agent, agentic loop, skill system
- **Emmanuel** — Research agent, browser executor, documentation agent, parallel research

---

## License

This project is part of an academic submission. See repository for license details.
