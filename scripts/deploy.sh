#!/usr/bin/env bash
# =============================================================================
# General Computer Use Agent — Automated Deployment Script
# =============================================================================
# Deploys the agent on an Ubuntu Linux machine with XFCE desktop.
# Can also provision a fresh Google Cloud VM from scratch.
#
# Usage:
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh                          # full local deploy
#   ./scripts/deploy.sh --gcp                    # create GCP VM + deploy
#   ./scripts/deploy.sh --gcp --name my-agent    # custom VM name
#   ./scripts/deploy.sh --gcp --zone us-east1-b  # custom zone
#   ./scripts/deploy.sh --python                 # python deps only
#   ./scripts/deploy.sh --verify                 # verify installation
#   ./scripts/deploy.sh --update                 # git pull + reinstall
#
# Requirements (local deploy):
#   - Ubuntu 22.04+ with XFCE desktop and X11
#   - sudo access
#   - Internet connection
#
# Requirements (GCP deploy):
#   - gcloud CLI installed and authenticated
#   - A GCP project with Compute Engine API enabled
#   - GEMINI_API_KEY environment variable set
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

# GCP defaults
GCP_VM_NAME="engineering-agent-v2"
GCP_ZONE="us-central1-a"
GCP_MACHINE_TYPE="e2-standard-4"
GCP_IMAGE_FAMILY="ubuntu-2204-lts"
GCP_IMAGE_PROJECT="ubuntu-os-cloud"
GCP_DISK_SIZE="50GB"
GCP_REPO_URL="https://github.com/Louisomeg/General_Computer_Use_Agent-.git"
GCP_REPO_BRANCH="design"

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

# ── GCP VM Provisioning ─────────────────────────────────────────────────────

generate_startup_script() {
    # Generates the cloud-init / startup script that runs inside the VM
    # on first boot. Installs everything and leaves the agent ready to run.
    local api_key="${GEMINI_API_KEY:-}"

    cat <<'STARTUP_HEADER'
#!/usr/bin/env bash
# =============================================================================
# GCP VM Startup Script — General Computer Use Agent
# Runs on first boot to set up the complete environment.
# =============================================================================
set -euo pipefail
exec > /var/log/agent-deploy.log 2>&1
echo "=== Agent deployment started at $(date) ==="

AGENT_USER="louismensah227"
AGENT_HOME="/home/$AGENT_USER"
PROJECT_DIR="$AGENT_HOME/General_Computer_Use_Agent-"

# ── Create user if needed ────────────────────────────────────────────────
if ! id "$AGENT_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$AGENT_USER"
    echo "$AGENT_USER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$AGENT_USER
    echo "[+] User $AGENT_USER created"
fi

# ── System packages ──────────────────────────────────────────────────────
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y \
    xfce4 \
    xfce4-goodies \
    xvfb \
    x11vnc \
    xdotool \
    scrot \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    git \
    curl \
    wget \
    dbus-x11 \
    at-spi2-core \
    software-properties-common

echo "[+] Core system packages installed"

# ── Chromium ─────────────────────────────────────────────────────────────
if ! command -v chromium-browser &>/dev/null && ! command -v chromium &>/dev/null; then
    apt-get install -y chromium-browser 2>/dev/null || \
    apt-get install -y chromium 2>/dev/null || \
    snap install chromium 2>/dev/null || \
    echo "[!] Could not install Chromium"
fi
echo "[+] Chromium installed"

# ── FreeCAD ──────────────────────────────────────────────────────────────
if ! command -v freecad &>/dev/null; then
    add-apt-repository -y ppa:freecad-maintainers/freecad-stable 2>/dev/null || true
    apt-get update -qq
    apt-get install -y freecad 2>/dev/null || \
    snap install freecad 2>/dev/null || \
    echo "[!] Could not install FreeCAD"
fi
echo "[+] FreeCAD installed"

STARTUP_HEADER

    # Inject the API key and repo config (these are variable)
    cat <<STARTUP_VARS
# ── Configuration (injected at deploy time) ──────────────────────────────
GEMINI_API_KEY="${api_key}"
REPO_URL="${GCP_REPO_URL}"
REPO_BRANCH="${GCP_REPO_BRANCH}"
STARTUP_VARS

    cat <<'STARTUP_BODY'

# ── Virtual display (Xvfb) ──────────────────────────────────────────────
# Create a persistent virtual X11 display at 1280x800 (agent's expected resolution)
cat > /etc/systemd/system/xvfb.service <<EOF
[Unit]
Description=Virtual X11 Display (Xvfb)
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/Xvfb :99 -screen 0 1280x800x24 -ac +extension GLX +render -noreset
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable xvfb
systemctl start xvfb
echo "[+] Xvfb virtual display started on :99 (1280x800)"

# ── XFCE session on virtual display ─────────────────────────────────────
cat > /etc/systemd/system/xfce-session.service <<EOF
[Unit]
Description=XFCE Desktop Session
After=xvfb.service
Requires=xvfb.service

[Service]
Type=simple
User=$AGENT_USER
Environment=DISPLAY=:99
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u $AGENT_USER)/bus
ExecStartPre=/bin/bash -c 'mkdir -p /run/user/$(id -u $AGENT_USER) && chown $AGENT_USER:$AGENT_USER /run/user/$(id -u $AGENT_USER)'
ExecStart=/usr/bin/xfce4-session
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable xfce-session
systemctl start xfce-session
echo "[+] XFCE session started on :99"

# ── VNC server (for remote viewing) ─────────────────────────────────────
cat > /etc/systemd/system/x11vnc.service <<EOF
[Unit]
Description=x11vnc VNC Server
After=xvfb.service xfce-session.service
Requires=xvfb.service

[Service]
Type=simple
ExecStart=/usr/bin/x11vnc -display :99 -forever -shared -rfbport 5900 -nopw -xkb
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable x11vnc
systemctl start x11vnc
echo "[+] VNC server started on port 5900"

# ── Clone project ────────────────────────────────────────────────────────
su - $AGENT_USER -c "
    if [ ! -d '$PROJECT_DIR' ]; then
        git clone '$REPO_URL' '$PROJECT_DIR'
        cd '$PROJECT_DIR'
        git checkout '$REPO_BRANCH'
    else
        cd '$PROJECT_DIR'
        git pull origin '$REPO_BRANCH'
    fi
    echo '[+] Repository cloned/updated'
"

# ── Python environment ───────────────────────────────────────────────────
su - $AGENT_USER -c "
    cd '$PROJECT_DIR'
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    python -m playwright install chromium 2>/dev/null || echo '[!] Playwright install failed'
    echo '[+] Python environment ready'
"

# ── Environment variables ────────────────────────────────────────────────
cat >> $AGENT_HOME/.bashrc <<EOF

# === General Computer Use Agent ===
export DISPLAY=:99
export GEMINI_API_KEY="$GEMINI_API_KEY"
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
alias agent='cd $PROJECT_DIR && source venv/bin/activate'
EOF

chown $AGENT_USER:$AGENT_USER $AGENT_HOME/.bashrc

# ── .env file ────────────────────────────────────────────────────────────
cat > $PROJECT_DIR/.env <<EOF
GEMINI_API_KEY=$GEMINI_API_KEY
SCREEN_WIDTH=1280
SCREEN_HEIGHT=800
MODEL_SCREEN_WIDTH=1440
MODEL_SCREEN_HEIGHT=900
EOF

chown $AGENT_USER:$AGENT_USER $PROJECT_DIR/.env

# ── Output directories ──────────────────────────────────────────────────
su - $AGENT_USER -c "
    mkdir -p '$PROJECT_DIR/outputs/research_results'
    mkdir -p '$PROJECT_DIR/outputs/cad_exports'
    mkdir -p '$PROJECT_DIR/outputs/screenshots'
    mkdir -p '$PROJECT_DIR/outputs/recordings'
"

# ── Done ─────────────────────────────────────────────────────────────────
echo ""
echo "=== Agent deployment completed at $(date) ==="
echo ""
echo "To use:"
echo "  1. SSH in:  gcloud compute ssh $AGENT_USER@$(hostname)"
echo "  2. Run:     agent"
echo "  3. Test:    python main.py 'Create a 30mm cube'"
echo "  4. VNC:     connect to <external-ip>:5900"
echo ""
STARTUP_BODY
}

deploy_gcp() {
    header "Deploying to Google Cloud VM"

    # Check prerequisites
    if ! command -v gcloud &>/dev/null; then
        err "gcloud CLI not found. Install it from: https://cloud.google.com/sdk/docs/install"
        exit 1
    fi

    # Check gcloud auth
    if ! gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>/dev/null | head -1 | grep -q "@"; then
        err "Not authenticated with gcloud. Run: gcloud auth login"
        exit 1
    fi

    # Check project
    local project
    project=$(gcloud config get-value project 2>/dev/null || echo "")
    if [ -z "$project" ]; then
        err "No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID"
        exit 1
    fi
    log "GCP project: $project"

    # Check API key
    if [ -z "${GEMINI_API_KEY:-}" ]; then
        err "GEMINI_API_KEY not set. The VM needs it."
        echo "  Run: export GEMINI_API_KEY='your-key'"
        exit 1
    fi
    log "GEMINI_API_KEY is set (will be injected into VM)"

    # Check if VM already exists
    if gcloud compute instances describe "$GCP_VM_NAME" --zone="$GCP_ZONE" &>/dev/null; then
        warn "VM '$GCP_VM_NAME' already exists in zone '$GCP_ZONE'"
        echo ""
        echo "  Options:"
        echo "    1. SSH in:     gcloud compute ssh $GCP_VM_NAME --zone=$GCP_ZONE"
        echo "    2. Delete it:  gcloud compute instances delete $GCP_VM_NAME --zone=$GCP_ZONE"
        echo "    3. Use --name: ./scripts/deploy.sh --gcp --name my-other-agent"
        echo ""
        exit 1
    fi

    # Generate startup script
    info "Generating startup script..."
    local startup_script
    startup_script=$(generate_startup_script)

    # Create the VM
    info "Creating GCP VM: $GCP_VM_NAME ($GCP_MACHINE_TYPE) in $GCP_ZONE..."
    gcloud compute instances create "$GCP_VM_NAME" \
        --zone="$GCP_ZONE" \
        --machine-type="$GCP_MACHINE_TYPE" \
        --image-family="$GCP_IMAGE_FAMILY" \
        --image-project="$GCP_IMAGE_PROJECT" \
        --boot-disk-size="$GCP_DISK_SIZE" \
        --boot-disk-type="pd-ssd" \
        --tags="agent-vnc" \
        --metadata=startup-script="$startup_script" \
        --scopes="https://www.googleapis.com/auth/cloud-platform"

    log "VM created: $GCP_VM_NAME"

    # Create firewall rule for VNC (port 5900) if it doesn't exist
    if ! gcloud compute firewall-rules describe allow-vnc-agent &>/dev/null 2>&1; then
        info "Creating firewall rule for VNC (port 5900)..."
        gcloud compute firewall-rules create allow-vnc-agent \
            --allow=tcp:5900 \
            --target-tags=agent-vnc \
            --description="Allow VNC access to agent VMs" \
            --source-ranges="0.0.0.0/0" 2>/dev/null || \
        warn "Could not create firewall rule. Create manually or use SSH tunnel."
    fi

    # Get external IP
    local external_ip
    external_ip=$(gcloud compute instances describe "$GCP_VM_NAME" \
        --zone="$GCP_ZONE" \
        --format="get(networkInterfaces[0].accessConfigs[0].natIP)" 2>/dev/null || echo "pending")

    echo ""
    header "GCP VM Deployment Complete"
    echo ""
    echo "  VM Name:     $GCP_VM_NAME"
    echo "  Zone:        $GCP_ZONE"
    echo "  Machine:     $GCP_MACHINE_TYPE"
    echo "  External IP: $external_ip"
    echo ""
    echo "  The startup script is installing dependencies now."
    echo "  This takes ~5-10 minutes. Check progress with:"
    echo ""
    echo "    gcloud compute ssh $GCP_VM_NAME --zone=$GCP_ZONE -- tail -f /var/log/agent-deploy.log"
    echo ""
    echo "  Once ready:"
    echo "    1. SSH:  gcloud compute ssh $GCP_VM_NAME --zone=$GCP_ZONE"
    echo "    2. Run:  agent && python main.py 'Create a 30mm cube'"
    echo "    3. VNC:  connect to $external_ip:5900 (or use SSH tunnel)"
    echo ""
    echo "  SSH tunnel for VNC (more secure):"
    echo "    gcloud compute ssh $GCP_VM_NAME --zone=$GCP_ZONE -- -L 5900:localhost:5900"
    echo "    Then connect VNC to localhost:5900"
    echo ""
    echo "  View deployment log:"
    echo "    gcloud compute ssh $GCP_VM_NAME --zone=$GCP_ZONE -- cat /var/log/agent-deploy.log"
    echo ""
    echo "  Delete VM when done:"
    echo "    gcloud compute instances delete $GCP_VM_NAME --zone=$GCP_ZONE"
    echo ""
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

    # Parse arguments
    local mode="full"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --gcp|-g)
                mode="gcp"
                shift
                ;;
            --name)
                GCP_VM_NAME="$2"
                shift 2
                ;;
            --zone)
                GCP_ZONE="$2"
                shift 2
                ;;
            --machine-type)
                GCP_MACHINE_TYPE="$2"
                shift 2
                ;;
            --verify|-v)
                mode="verify"
                shift
                ;;
            --python|-p)
                mode="python"
                shift
                ;;
            --update|-u)
                mode="update"
                shift
                ;;
            --system|-s)
                mode="system"
                shift
                ;;
            --help|-h)
                mode="help"
                shift
                ;;
            *)
                shift
                ;;
        esac
    done

    case "$mode" in
        gcp)
            deploy_gcp
            ;;
        verify)
            verify_all
            ;;
        python)
            setup_python
            setup_env
            setup_outputs
            verify_all
            ;;
        update)
            update_project
            verify_all
            ;;
        system)
            install_system_deps
            ;;
        help)
            echo ""
            echo "Usage: ./scripts/deploy.sh [option]"
            echo ""
            echo "Local deployment:"
            echo "  (none)       Full deployment (system + python + verify)"
            echo "  --python     Python deps only (skip system packages)"
            echo "  --system     System deps only (apt packages)"
            echo "  --update     Git pull + reinstall python deps"
            echo "  --verify     Verify existing installation"
            echo ""
            echo "GCP deployment:"
            echo "  --gcp                    Create a GCP VM and deploy everything"
            echo "  --gcp --name NAME        Custom VM name (default: engineering-agent-v2)"
            echo "  --gcp --zone ZONE        Custom zone (default: us-central1-a)"
            echo "  --gcp --machine-type MT  Custom machine (default: e2-standard-4)"
            echo ""
            echo "  Requires: gcloud CLI, authenticated, GEMINI_API_KEY set"
            echo "  Creates: Ubuntu 22.04 VM with XFCE + Xvfb + VNC + FreeCAD + agent"
            echo ""
            ;;
        *)
            # Full local deployment
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
