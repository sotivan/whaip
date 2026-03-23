#!/usr/bin/env bash
# WHAIP installer
# Usage: curl -fsSL https://raw.githubusercontent.com/[usuario]/whaip/main/scripts/install.sh | bash

set -euo pipefail

REPO="https://github.com/sotivan/whaip"
REPO_RAW="https://raw.githubusercontent.com/sotivan/whaip/main"
INSTALL_DIR="$HOME/.whaip"
BIN_DIR="/usr/local/bin"
CONFIG_DIR="$HOME/.whaip"
PYTHON_MIN="3.10"

# ── Colours ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[whaip]${NC} $*"; }
warn()  { echo -e "${YELLOW}[whaip]${NC} $*"; }
error() { echo -e "${RED}[whaip]${NC} $*"; exit 1; }

# ── Dependency checks ──────────────────────────────────────────────────────

check_dependencies() {
  info "Checking dependencies…"
  command -v git    >/dev/null 2>&1 || error "git is required. Install it first."
  command -v node   >/dev/null 2>&1 || error "Node.js is required (v18+). See https://nodejs.org"
  command -v npm    >/dev/null 2>&1 || error "npm is required."
  command -v python3 >/dev/null 2>&1 || error "Python 3 is required (>= $PYTHON_MIN)."

  # Python version check
  PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
  python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" \
    || error "Python $PYTHON_MIN+ required, found $PY_VER"

  info "All dependencies satisfied."
}

# ── Clone / update ─────────────────────────────────────────────────────────

clone_or_update() {
  if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation at $INSTALL_DIR…"
    git -C "$INSTALL_DIR" pull --ff-only
  else
    info "Cloning WHAIP into $INSTALL_DIR…"
    git clone "$REPO" "$INSTALL_DIR"
  fi
}

# ── Node dependencies ──────────────────────────────────────────────────────

install_node_deps() {
  info "Installing Node dependencies…"
  npm --prefix "$INSTALL_DIR" install
}

# ── Python virtualenv + dependencies ──────────────────────────────────────

install_python_deps() {
  info "Creating Python virtual environment…"
  python3 -m venv "$INSTALL_DIR/.venv"
  # shellcheck disable=SC1091
  source "$INSTALL_DIR/.venv/bin/activate"
  pip install --upgrade pip -q
  info "Installing Python dependencies (this may take a few minutes — Whisper is ~150MB)…"
  pip install -r "$INSTALL_DIR/requirements.txt" -q
  deactivate
}

# ── Config ─────────────────────────────────────────────────────────────────

setup_config() {
  if [ ! -f "$INSTALL_DIR/whaip.config.yaml" ]; then
    warn "Config file not found – creating default at $INSTALL_DIR/whaip.config.yaml"
    cp "$INSTALL_DIR/whaip.config.yaml.example" "$INSTALL_DIR/whaip.config.yaml" 2>/dev/null \
      || warn "No example config found; run 'whaip config' after install."
  else
    info "Config already exists at $INSTALL_DIR/whaip.config.yaml"
  fi
}

# ── CLI shim ───────────────────────────────────────────────────────────────

install_cli_shim() {
  info "Installing 'whaip' CLI shim to $BIN_DIR…"
  sudo tee "$BIN_DIR/whaip" > /dev/null <<EOF
#!/usr/bin/env bash
cd "$INSTALL_DIR"
source .venv/bin/activate
case "\$1" in
  start) npm start ;;
  agent) python3 agent/main.py ;;
  config) \${EDITOR:-nano} whaip.config.yaml ;;
  update) git pull --ff-only && npm install && pip install -r requirements.txt -q ;;
  *) echo "Usage: whaip [start|agent|config|update]" ;;
esac
EOF
  sudo chmod +x "$BIN_DIR/whaip"
}

# ── Main ───────────────────────────────────────────────────────────────────

main() {
  echo ""
  echo "  ██╗    ██╗██╗  ██╗ █████╗ ██╗██████╗ "
  echo "  ██║    ██║██║  ██║██╔══██╗██║██╔══██╗"
  echo "  ██║ █╗ ██║███████║███████║██║██████╔╝"
  echo "  ██║███╗██║██╔══██║██╔══██║██║██╔═══╝ "
  echo "  ╚███╔███╔╝██║  ██║██║  ██║██║██║     "
  echo "   ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝     "
  echo ""
  info "Installing WHAIP – AI-powered browser agent"
  echo ""

  check_dependencies
  clone_or_update
  install_node_deps
  install_python_deps
  setup_config
  install_cli_shim

  echo ""
  info "Installation complete!"
  echo ""
  echo "  Next steps:"
  echo "  1. Edit your config:  whaip config"
  echo "  2. Add your API keys to whaip.config.yaml"
  echo "  3. Launch WHAIP:       whaip start"
  echo ""
}

main "$@"
