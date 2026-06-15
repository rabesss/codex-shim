#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
PREFIX="${CODEX_SHIM_INSTALL_PREFIX:-$DATA_HOME/codex-shim}"
BIN_DIR="${CODEX_SHIM_BIN_DIR:-$HOME/.local/bin}"
SETTINGS="${CODEX_SHIM_SETTINGS:-$HOME/.codex-shim/models.json}"
INSTALL_SERVICE=1
WRITE_MODELS=1

usage() {
    cat <<'EOF'
Usage: scripts/install-user.sh [options]

Install codex-shim into an isolated user venv and optionally install its
credential-neutral systemd user service.

Options:
  --prefix PATH      Installation root (default: ~/.local/share/codex-shim)
  --bin-dir PATH     Launcher directory (default: ~/.local/bin)
  --settings PATH    Model settings path (default: ~/.codex-shim/models.json)
  --no-service       Install the CLI without creating or starting a user service
  --no-models        Keep an existing settings file and skip model discovery
  -h, --help         Show this help
EOF
}

while (($#)); do
    case "$1" in
        --prefix)
            PREFIX="${2:?--prefix requires a path}"
            shift 2
            ;;
        --bin-dir)
            BIN_DIR="${2:?--bin-dir requires a path}"
            shift 2
            ;;
        --settings)
            SETTINGS="${2:?--settings requires a path}"
            shift 2
            ;;
        --no-service)
            INSTALL_SERVICE=0
            shift
            ;;
        --no-models)
            WRITE_MODELS=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

PREFIX="$(realpath -m "$PREFIX")"
BIN_DIR="$(realpath -m "$BIN_DIR")"
SETTINGS="$(realpath -m "$SETTINGS")"
VENV="$PREFIX/venv"
RUNTIME_DIR="$STATE_HOME/codex-shim"

mkdir -p "$PREFIX" "$BIN_DIR" "$(dirname "$SETTINGS")" "$RUNTIME_DIR"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install "$ROOT_DIR"

cat >"$BIN_DIR/codex-shim" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "$VENV/bin/codex-shim" "\$@"
EOF
chmod 0755 "$BIN_DIR/codex-shim"

if ((WRITE_MODELS)); then
    "$VENV/bin/codex-shim" --settings "$SETTINGS" desktop write-models --output "$SETTINGS"
elif [[ ! -f "$SETTINGS" ]]; then
    echo "Settings file does not exist: $SETTINGS" >&2
    exit 1
fi

if ((INSTALL_SERVICE)); then
    if ! command -v systemctl >/dev/null 2>&1; then
        echo "systemctl is unavailable; rerun with --no-service or install the service manually." >&2
        exit 1
    fi
    UNIT_DIR="$CONFIG_HOME/systemd/user"
    UNIT_PATH="$UNIT_DIR/codex-shim.service"
    mkdir -p "$UNIT_DIR"
    cat >"$UNIT_PATH" <<EOF
[Unit]
Description=Codex custom-model compatibility shim
After=network.target

[Service]
Type=simple
Environment=PYTHONUNBUFFERED=1
Environment=NO_PROXY=127.0.0.1,localhost,::1
Environment=no_proxy=127.0.0.1,localhost,::1
Environment="CODEX_SHIM_RUNTIME_DIR=$RUNTIME_DIR"
ExecStart="$VENV/bin/python" -m codex_shim.server --settings "$SETTINGS" --host 127.0.0.1 --port 8765
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now codex-shim.service
fi

echo "Installed codex-shim under $PREFIX"
echo "CLI launcher: $BIN_DIR/codex-shim"
echo "Model settings: $SETTINGS"
if ((INSTALL_SERVICE)); then
    echo "User service: codex-shim.service"
fi
echo "No provider credentials were written by this installer."
"$VENV/bin/codex-shim" --settings "$SETTINGS" doctor || true
