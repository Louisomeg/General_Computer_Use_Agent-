#!/usr/bin/env bash
# =============================================================================
# General Computer Use Agent — Automated Deployment Script
# =============================================================================
# Deploys the agent on an Ubuntu Linux machine with XFCE desktop.
#
# Usage:
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh              # full deploy (system deps + python + app)
#   ./scripts/deploy.sh --python     # python deps only (skip system packages)
#   ./scripts/deploy.sh --verify     # verify existing installation
#   ./scripts/deploy.sh --update     # git pull + reinstall python deps
#
# Requirements:
#   - Ubuntu 22.04+ with XFCE desktop and X11
#   - sudo access (for system package installation)
#   - Display resolution set to 1280x800
#   - Internet connection
# =============================================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Project root (relative to this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_ROOT/venv"

# ── Helpers ──────────────────────────────────────────────────────────────────

log()   { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
err()   { echo -e "${RED}[x]${NC} $1"; }
info()  { echo -e "${CYAN}[>]${NC} $1"; }
header() {
    echo ""
    echo -e "${CYAN}============================================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}============================================================${NC}"
}

check_cmd() {
    if command -v "$1" &>/dev/null; then
        log "$1 found: $(command -v "$1")"
        return 0
    else
        err "$1 not found"
        return 1
    fi
}

# ── System Dependencies ─────────────────────────────────────────────────────

install_system_deps() {
    header "Installing System Dependencies"

    if ! command -v apt &>/dev/null; then
        err "apt package manager not found. This script requires Ubuntu/Debian."
        exit 1
    fi

    info "Updating package lists..."
    sudo apt update -qq

    info "Installing core packages..."
    sudo apt install -y \
        python3 \
        python3-pip \
        python3-venv \
        scrot \
        xdotool \
        ffmpeg \
        git \
        curl \
        wget

    # Chromium for research agent
    info "Installing Chromium browser..."
    if command -v chromium-browser &>/dev/null || command -v chromium &>/dev/null; then
        log "Chromium already installed"
    else
        sudo apt install -y chromium-browser 2>/dev/null || \
        sudo apt install -y chromium 2>/dev/null || \
        sudo snap install chromium 2>/dev/null || \
        warn "Could not install Chromium. Research agent may not work."
    fi

    # FreeCAD for CAD agent
    info "Installing FreeCAD..."
    if command -v freecad &>/dev/null || command -v FreeCAD &>/dev/null; then
        log "FreeCAD already installed"
    else
        # Try the PPA for latest version first, fall back to apt
        sudo add-apt-repository -y ppa:freecad-maintainers/freecad-stable 2>/dev/null || true
        sudo apt update -qq
        sudo apt install -y freecad 2>/dev/null || \
        sudo snap install freecad 2>/dev/null || \
        warn "Could not install FreeCAD. CAD agent will not work."
    fi

    log "System dependencies installed"
}

# ── Python Environment ───────────────────────────────────────────────────────

setup_python() {
    header "Setting Up Python Environment"

    cd "$PROJECT_ROOT"

    # Create virtual environment if it doesn't exist
    if [ ! -d "$VENV_DIR" ]; then
        info "Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
        log "Virtual environment created at $VENV_DIR"
    else
        log "Virtual environment already exists"
    fi

    # Activate
    source "$VENV_DIR/bin/activate"

    # Upgrade pip
    info "Upgrading pip..."
    pip install --upgrade pip -q

    # Install requirements
    info "Installing Python dependencies..."
    pip install -r requirements.txt -q
    log "Python dependencies installed"

    # Install Playwright browsers
    info "Installing Playwright Chromium browser..."
    python -m playwright install chromium 2>/dev/null || \
        warn "Playwright browser install failed. Research agent may not work."
    log "Playwright browsers installed"
}

# ── Environment Configuration ────────────────────────────────────────────────

setup_env() {
    header "Configuring Environment"

    cd "$PROJECT_ROOT"

    # Check for .env file
    if [ -f ".env" ]; then
        log ".env file exists"
        # Source it to check for GEMINI_API_KEY
        set +u
        source .env 2>/dev/null || true
        set -u
    fi

    # Check GEMINI_API_KEY
    if [ -z "${GEMINI_API_KEY:-}" ]; then
        warn "GEMINI_API_KEY is not set!"
        echo ""
        echo "  Set it now:"
        echo "    export GEMINI_API_KEY=\"your-key\""
        echo ""
        echo "  Or create a .env file:"
        echo "    cp .env.example .env"
        echo "    # Edit .env and add your key"
        echo ""
        echo "  Get a key at: https://aistudio.google.com/apikey"
        echo ""
    else
        log "GEMINI_API_KEY is set"
    fi

    # Check display
    if [ -n "${DISPLAY:-}" ]; then
        log "DISPLAY is set: $DISPLAY"
    else
        warn "DISPLAY is not set. Agent requires X11 display."
        echo "  Set it with: export DISPLAY=:0"
    fi
}

# ── Display Verification ────────────────────────────────────────────────────

verify_display() {
    header "Verifying Display Setup"

    # Check X11
    if [ -z "${DISPLAY:-}" ]; then
        err "No DISPLAY set. Cannot verify display."
        return 1
    fi

    # Check resolution
    if command -v xdotool &>/dev/null; then
        local geometry
        geometry=$(xdotool getdisplaygeometry 2>/dev/null || echo "unknown")
        if [ "$geometry" = "1280 800" ]; then
            log "Display resolution: 1280x800 (correct)"
        else
            warn "Display resolution: $geometry (expected: 1280 800)"
            echo "  Fix with: xrandr --output \$(xrandr | grep ' connected' | cut -d' ' -f1) --mode 1280x800"
            echo "  Or update SCREEN_WIDTH/SCREEN_HEIGHT in core/settings.py"
        fi
    fi

    # Test screenshot
    if command -v scrot &>/dev/null; then
        if scrot /tmp/deploy_test_screenshot.png -o 2>/dev/null; then
            log "Screenshot capture works"
            rm -f /tmp/deploy_test_screenshot.png
        else
            err "Screenshot capture failed (scrot)"
        fi
    fi

    # Test xdotool
    if command -v xdotool &>/dev/null; then
        if xdotool getactivewindow &>/dev/null; then
            log "xdotool works"
        else
            warn "xdotool cannot get active window (may work when desktop is active)"
        fi
    fi
}

# ── Full Verification ────────────────────────────────────────────────────────

verify_all() {
    header "Verifying Installation"
    local errors=0

    echo ""
    info "Checking system commands..."
    check_cmd python3    || ((errors++))
    check_cmd scrot      || ((errors++))
    check_cmd xdotool    || ((errors++))
    check_cmd ffmpeg     || ((errors++))
    check_cmd git        || ((errors++))

    echo ""
    info "Checking applications..."
    (check_cmd freecad || check_cmd FreeCAD) || ((errors++))
    (check_cmd chromium-browser || check_cmd chromium) || ((errors++))

    echo ""
    info "Checking Python environment..."
    if [ -d "$VENV_DIR" ]; then
        log "Virtual environment exists"
        source "$VENV_DIR/bin/activate" 2>/dev/null
        if python -c "import google.genai" 2>/dev/null; then
            log "google-genai package installed"
        else
            err "google-genai package not found"
            ((errors++))
        fi
        if python -c "import playwright" 2>/dev/null; then
            log "playwright package installed"
        else
            err "playwright package not found"
            ((errors++))
        fi
        if python -c "from PIL import Image" 2>/dev/null; then
            log "Pillow package installed"
        else
            err "Pillow package not found"
            ((errors++))
        fi
    else
        err "Virtual environment not found at $VENV_DIR"
        ((errors++))
    fi

    echo ""
    info "Checking environment variables..."
    if [ -n "${GEMINI_API_KEY:-}" ]; then
        log "GEMINI_API_KEY is set"
    else
        err "GEMINI_API_KEY is not set"
        ((errors++))
    fi
    if [ -n "${DISPLAY:-}" ]; then
        log "DISPLAY is set: $DISPLAY"
    else
        err "DISPLAY is not set"
        ((errors++))
    fi

    echo ""
    info "Checking project structure..."
    cd "$PROJECT_ROOT"
    for f in main.py requirements.txt core/settings.py core/agentic_loop.py \
             core/agentic_planner.py core/desktop_executor.py core/freecad_functions.py \
             core/custom_tools.py agents/cad_agent.py agents/research_agent.py; do
        if [ -f "$f" ]; then
            log "$f exists"
        else
            err "$f missing"
            ((errors++))
        fi
    done

    echo ""
    if [ "$errors" -eq 0 ]; then
        log "All checks passed! Ready to run."
        echo ""
        echo "  Start the agent:"
        echo "    source venv/bin/activate"
        echo "    python main.py \"Create a 30mm cube\""
        echo ""
    else
        err "$errors check(s) failed. Fix the issues above and re-run:"
        echo "    ./scripts/deploy.sh --verify"
    fi

    return "$errors"
}

# ── Git Update ───────────────────────────────────────────────────────────────

update_project() {
    header "Updating Project"

    cd "$PROJECT_ROOT"

    info "Pulling latest changes..."
    git pull origin design

    info "Reinstalling Python dependencies..."
    source "$VENV_DIR/bin/activate"
    pip install -r requirements.txt -q

    log "Update complete"
}

# ── Output Directory Setup ───────────────────────────────────────────────────

setup_outputs() {
    header "Setting Up Output Directories"

    cd "$PROJECT_ROOT"

    mkdir -p outputs/research_results
    mkdir -p outputs/cad_exports
    mkdir -p outputs/screenshots
    mkdir -p outputs/recordings

    log "Output directories created"
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo ""
    echo -e "${CYAN}============================================================${NC}"
    echo -e "${CYAN}  General Computer Use Agent - Deployment Script${NC}"
    echo -e "${CYAN}============================================================${NC}"

    local mode="${1:-full}"

    case "$mode" in
        --verify|-v)
            verify_all
            ;;
        --python|-p)
            setup_python
            setup_env
            setup_outputs
            verify_all
            ;;
        --update|-u)
            update_project
            verify_all
            ;;
        --system|-s)
            install_system_deps
            ;;
        --help|-h)
            echo ""
            echo "Usage: ./scripts/deploy.sh [option]"
            echo ""
            echo "Options:"
            echo "  (none)       Full deployment (system + python + verify)"
            echo "  --python     Python deps only (skip system packages)"
            echo "  --system     System deps only (apt packages)"
            echo "  --update     Git pull + reinstall python deps"
            echo "  --verify     Verify existing installation"
            echo "  --help       Show this help"
            echo ""
            ;;
        *)
            # Full deployment
            install_system_deps
            setup_python
            setup_env
            setup_outputs
            verify_display
            verify_all
            ;;
    esac
}

main "$@"
