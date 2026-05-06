#!/bin/sh
# claude-qte one-shot installer.
#
#   curl -fsSL https://raw.githubusercontent.com/adiletbaimyrza/claude-qte/main/install.sh | sh
#
# Downloads the right macOS binary from the latest GitHub release, then runs
# `claude-qte install` so the actual install logic lives with the binary
# (and stays versioned with it).

set -eu

REPO="${CLAUDE_QTE_REPO:-adiletbaimyrza/claude-qte}"
TMPDIR="$(mktemp -d -t claude-qte-install.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

case "$(uname -s)" in
    Darwin) ;;
    *) echo "claude-qte currently supports macOS only." >&2; exit 1 ;;
esac

case "$(uname -m)" in
    arm64)  ASSET="claude-qte-macos-arm64" ;;
    x86_64) ASSET="claude-qte-macos-x86_64" ;;
    *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

URL="https://github.com/${REPO}/releases/latest/download/${ASSET}"
echo "  Downloading ${ASSET}..."
if ! curl -fsSL "$URL" -o "${TMPDIR}/claude-qte"; then
    echo "  Download failed: ${URL}" >&2
    exit 1
fi

chmod +x "${TMPDIR}/claude-qte"
xattr -d com.apple.quarantine "${TMPDIR}/claude-qte" 2>/dev/null || true

echo "  Running installer..."
"${TMPDIR}/claude-qte" install
