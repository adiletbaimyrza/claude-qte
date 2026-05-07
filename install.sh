#!/bin/sh
# claude-qte one-shot installer.
#
#   curl -fsSL https://raw.githubusercontent.com/adiletbaimyrza/claude-qte/main/install.sh | sh
#
# Downloads the right binary for your platform from the latest GitHub release,
# then runs `claude-qte install` so the actual install logic lives with the
# binary (and stays versioned with it).

set -eu

REPO="${CLAUDE_QTE_REPO:-adiletbaimyrza/claude-qte}"
TMPDIR="$(mktemp -d -t claude-qte-install.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin)
        case "$ARCH" in
            arm64)  ASSET="claude-qte-macos-arm64" ;;
            x86_64) ASSET="claude-qte-macos-arm64" ;;
            *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
        esac
        ;;
    Linux)
        case "$ARCH" in
            x86_64) ASSET="claude-qte-linux-x86_64" ;;
            *) echo "Unsupported architecture: $ARCH (only x86_64 is supported on Linux)" >&2; exit 1 ;;
        esac
        ;;
    *)
        echo "Unsupported OS: $OS (supported: macOS, Linux)" >&2
        exit 1
        ;;
esac

URL="https://github.com/${REPO}/releases/latest/download/${ASSET}"
echo "  Downloading ${ASSET}..."
if ! curl -fsSL "$URL" -o "${TMPDIR}/claude-qte"; then
    echo "  Download failed: ${URL}" >&2
    exit 1
fi

chmod +x "${TMPDIR}/claude-qte"
# Strip Gatekeeper quarantine on macOS (no-op on Linux).
xattr -d com.apple.quarantine "${TMPDIR}/claude-qte" 2>/dev/null || true

echo "  Running installer..."
"${TMPDIR}/claude-qte" install
