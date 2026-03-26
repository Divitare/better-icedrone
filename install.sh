#!/usr/bin/env bash
# ============================================================================
# UWB Web — Installer & Updater for Raspberry Pi
# ============================================================================
# Usage:
#   curl -sSL https://raw.githubusercontent.com/Divitare/better-icedrone/main/install.sh | sudo bash
#   — or —
#   sudo bash install.sh
#
# Handles:
#   - Fresh installation from GitHub
#   - Update of an existing installation
#   - System dependency management
#   - Python virtual-environment setup
#   - systemd service configuration
#   - Permissions and serial-port access
# ============================================================================

set -euo pipefail

# --- Configuration ---
REPO_URL="https://github.com/Divitare/better-icedrone.git"
INSTALL_DIR="/opt/uwb-web"
VENV_DIR="${INSTALL_DIR}/venv"
DATA_DIR="${INSTALL_DIR}/data"
SERVICE_USER="uwb"
SERVICE_FILE="/etc/systemd/system/uwb-web.service"
BRANCH="main"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }

# --- Pre-checks ---

if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (sudo)."
    exit 1
fi

# Detect Raspberry Pi (informational only — works on any Debian/Ubuntu)
if grep -qi 'raspberry\|raspbian' /etc/os-release 2>/dev/null; then
    info "Detected Raspberry Pi OS."
elif grep -qi 'ubuntu\|debian' /etc/os-release 2>/dev/null; then
    info "Detected Debian/Ubuntu."
else
    warn "This installer is designed for Debian-based systems. Proceeding anyway."
fi

# --- Functions ---

install_system_deps() {
    info "Installing system dependencies..."
    apt-get update -qq
    apt-get install -y -qq \
        python3 \
        python3-venv \
        python3-pip \
        python3-dev \
        git \
        build-essential \
        libffi-dev \
        > /dev/null 2>&1
    success "System dependencies installed."
}

create_service_user() {
    if id "${SERVICE_USER}" &>/dev/null; then
        info "Service user '${SERVICE_USER}' already exists."
    else
        info "Creating service user '${SERVICE_USER}'..."
        useradd --system --shell /usr/sbin/nologin --home-dir "${INSTALL_DIR}" "${SERVICE_USER}"
        success "User '${SERVICE_USER}' created."
    fi
    # Ensure the user is in the dialout group for serial access
    usermod -aG dialout "${SERVICE_USER}" 2>/dev/null || true
}

clone_repo() {
    info "Cloning repository from ${REPO_URL}..."
    git clone --branch "${BRANCH}" --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
    success "Repository cloned to ${INSTALL_DIR}."
}

pull_updates() {
    info "Pulling latest changes..."
    cd "${INSTALL_DIR}"
    # Stash any local changes to config
    git stash --include-untracked 2>/dev/null || true
    git fetch origin "${BRANCH}"
    git reset --hard "origin/${BRANCH}"
    # Restore stashed config if any
    git stash pop 2>/dev/null || true
    success "Repository updated."
}

setup_venv() {
    if [[ -d "${VENV_DIR}" ]]; then
        info "Virtual environment exists — upgrading pip..."
        "${VENV_DIR}/bin/pip" install --upgrade pip -q
    else
        info "Creating Python virtual environment..."
        python3 -m venv "${VENV_DIR}"
        "${VENV_DIR}/bin/pip" install --upgrade pip -q
    fi
    info "Installing Python dependencies..."
    "${VENV_DIR}/bin/pip" install -r "${INSTALL_DIR}/requirements.txt" -q
    success "Python environment ready."
}

setup_data_dir() {
    mkdir -p "${DATA_DIR}"
    # Copy default config if not present
    if [[ ! -f "${INSTALL_DIR}/config.yaml" ]]; then
        if [[ -f "${INSTALL_DIR}/config.yaml" ]]; then
            info "Config file already exists."
        else
            warn "No config.yaml found — creating default."
            cat > "${INSTALL_DIR}/config.yaml" <<'YAML'
serial:
  port: auto
  baud: 115200
  timeout: 1.0
  reconnect_delay: 3.0

database:
  path: data/uwb_data.db

logging:
  level: INFO
  file: data/uwb_web.log

web:
  host: 0.0.0.0
  port: 5000
  debug: false

retention:
  raw_lines_days: 30
  measurements_days: 365
  store_raw_lines: true

demo:
  enabled: false
  replay_file: tests/sample_serial_output.txt
  replay_speed: 1.0
YAML
        fi
    fi
    success "Data directory ready."
}

init_database() {
    info "Initializing database..."
    cd "${INSTALL_DIR}"
    "${VENV_DIR}/bin/python" scripts/init_db.py
    success "Database initialized."
}

install_systemd_service() {
    info "Installing systemd service..."
    cp "${INSTALL_DIR}/systemd/uwb-web.service" "${SERVICE_FILE}"
    systemctl daemon-reload
    systemctl enable uwb-web.service
    success "systemd service installed and enabled."
}

set_permissions() {
    info "Setting file permissions..."
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
    chmod -R 755 "${INSTALL_DIR}"
    chmod -R 770 "${DATA_DIR}"
    success "Permissions set."
}

start_service() {
    info "Starting uwb-web service..."
    systemctl restart uwb-web.service
    sleep 2
    if systemctl is-active --quiet uwb-web.service; then
        success "Service is running."
    else
        error "Service failed to start. Check: journalctl -u uwb-web.service"
        return 1
    fi
}

show_status() {
    echo ""
    echo -e "${BOLD}============================================${NC}"
    echo -e "${GREEN} UWB Web — Installation Complete${NC}"
    echo -e "${BOLD}============================================${NC}"
    echo ""
    echo -e "  Install dir:  ${INSTALL_DIR}"
    echo -e "  Data dir:     ${DATA_DIR}"
    echo -e "  Config:       ${INSTALL_DIR}/config.yaml"
    echo -e "  Service:      uwb-web.service"
    echo ""
    # Detect IP
    local ip
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    if [[ -n "$ip" ]]; then
        echo -e "  ${BOLD}Web UI:  http://${ip}:5000${NC}"
    else
        echo -e "  ${BOLD}Web UI:  http://localhost:5000${NC}"
    fi
    echo ""
    echo "  Useful commands:"
    echo "    sudo systemctl status uwb-web"
    echo "    sudo systemctl restart uwb-web"
    echo "    sudo journalctl -u uwb-web -f"
    echo ""
}

# --- Update flow ---

do_update() {
    echo ""
    echo -e "${BOLD}=== UWB Web Update ===${NC}"
    echo ""
    echo "  Existing installation found at ${INSTALL_DIR}"
    echo ""
    echo "  Options:"
    echo "    1) Update code + dependencies (keeps data & config)"
    echo "    2) Full reinstall (DELETES data — fresh start)"
    echo "    3) Cancel"
    echo ""
    read -rp "  Choose [1/2/3]: " choice

    case "$choice" in
        1)
            info "Performing update..."
            systemctl stop uwb-web.service 2>/dev/null || true
            install_system_deps
            pull_updates
            setup_venv
            setup_data_dir
            init_database
            install_systemd_service
            set_permissions
            start_service
            show_status
            ;;
        2)
            warn "This will DELETE all existing data and config!"
            read -rp "  Type 'YES' to confirm: " confirm
            if [[ "$confirm" != "YES" ]]; then
                info "Cancelled."
                exit 0
            fi
            systemctl stop uwb-web.service 2>/dev/null || true
            systemctl disable uwb-web.service 2>/dev/null || true
            rm -f "${SERVICE_FILE}"
            rm -rf "${INSTALL_DIR}"
            do_fresh_install
            ;;
        3)
            info "Cancelled."
            exit 0
            ;;
        *)
            error "Invalid choice."
            exit 1
            ;;
    esac
}

# --- Fresh install flow ---

do_fresh_install() {
    echo ""
    echo -e "${BOLD}=== UWB Web Fresh Install ===${NC}"
    echo ""
    install_system_deps
    create_service_user
    clone_repo
    setup_venv
    setup_data_dir
    init_database
    install_systemd_service
    set_permissions
    start_service
    show_status
}

# --- Main ---

echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   UWB Web Installer — Raspberry Pi   ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""

if [[ -d "${INSTALL_DIR}/.git" ]]; then
    do_update
else
    do_fresh_install
fi
