#!/bin/sh
# Install the Elva CLI.
#
#   curl -fsSL https://get.getelva.ai | sh
#   curl -fsSL https://get.getelva.ai | sh -s -- --version v1.0.0
#
# Downloads a standalone binary from the GitHub release, checks it against the
# published SHA256SUMS, and puts it in ~/.local/bin. No Python needed.

set -eu

REPO="Theneo-Inc/theneo-elva-cli"
BIN_NAME="elva"
INSTALL_DIR="${ELVA_INSTALL_DIR:-$HOME/.local/bin}"
VERSION="latest"

die() { echo "elva: $*" >&2; exit 1; }

usage() {
    cat <<'USAGE'
Usage: install.sh [--version VERSION] [--install-dir DIR]

  --version      release tag to install, e.g. v1.0.0 (default: the latest release)
  --install-dir  where to put the binary (default: ~/.local/bin)
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --version) [ $# -ge 2 ] || die "--version needs a value"; VERSION="$2"; shift 2 ;;
        --install-dir) [ $# -ge 2 ] || die "--install-dir needs a value"; INSTALL_DIR="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

command -v curl >/dev/null 2>&1 || die "curl is required"

os="$(uname -s)"
arch="$(uname -m)"
case "$os" in
    Linux)  os_part="linux" ;;
    Darwin) os_part="darwin" ;;
    *) die "no binary for $os. Install with: uv tool install elva-cli" ;;
esac
case "$arch" in
    x86_64|amd64) arch_part="x86_64" ;;
    aarch64|arm64) arch_part="$([ "$os_part" = darwin ] && echo arm64 || echo aarch64)" ;;
    *) die "no binary for $arch. Install with: uv tool install elva-cli" ;;
esac
asset="${BIN_NAME}-${os_part}-${arch_part}"

if [ "$VERSION" = latest ]; then
    base="https://github.com/$REPO/releases/latest/download"
else
    base="https://github.com/$REPO/releases/download/$VERSION"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT INT TERM

echo "Downloading $asset ($VERSION)"
curl -fsSL "$base/$asset" -o "$tmp/$asset" \
    || die "could not download $base/$asset"
curl -fsSL "$base/SHA256SUMS" -o "$tmp/SHA256SUMS" \
    || die "could not download the checksums for $VERSION"

if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "$tmp/$asset" | cut -d' ' -f1)"
elif command -v shasum >/dev/null 2>&1; then
    actual="$(shasum -a 256 "$tmp/$asset" | cut -d' ' -f1)"
else
    die "need sha256sum or shasum to verify the download"
fi
expected="$(grep " \\*\\?$asset\$" "$tmp/SHA256SUMS" | cut -d' ' -f1)"
[ -n "$expected" ] || die "$asset is not listed in SHA256SUMS"
[ "$actual" = "$expected" ] || die "checksum mismatch for $asset (expected $expected, got $actual)"

mkdir -p "$INSTALL_DIR"
chmod +x "$tmp/$asset"

mv -f "$tmp/$asset" "$INSTALL_DIR/$BIN_NAME"

installed="$("$INSTALL_DIR/$BIN_NAME" --version 2>/dev/null || echo unknown)"
echo "Installed $installed to $INSTALL_DIR/$BIN_NAME"

case ":${PATH}:" in
    *":$INSTALL_DIR:"*) ;;
    *)
        echo
        echo "$INSTALL_DIR is not on your PATH. Add it:"
        case "${SHELL##*/}" in
            zsh)  echo "  echo 'export PATH=\"$INSTALL_DIR:\$PATH\"' >> ~/.zshrc && exec zsh" ;;
            fish) echo "  fish_add_path $INSTALL_DIR" ;;
            *)    echo "  echo 'export PATH=\"$INSTALL_DIR:\$PATH\"' >> ~/.bashrc && exec bash" ;;
        esac
        ;;
esac
