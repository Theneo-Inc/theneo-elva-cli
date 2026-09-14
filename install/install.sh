#!/bin/sh
# Install the Elva CLI on macOS or Linux.
#
#   curl -fsSL https://get.getelva.ai | sh
#   curl -fsSL https://get.getelva.ai | sh -s -- --version v1.0.0
#
# Downloads a standalone binary from the GitHub release, checks it against the
# published SHA256SUMS, and puts it in ~/.local/bin. No Python needed.

set -eu

REPO="Theneo-Inc/theneo-elva-cli"
BIN_NAME="elva"

die() { echo "elva: $*" >&2; exit 1; }

usage() {
cat <<'USAGE'
Usage: install.sh [--version VERSION] [--install-dir DIR]

  --version      release tag to install, e.g. v1.0.0 (default: the latest release)
  --install-dir  where to put the binary (default: ~/.local/bin)
USAGE
}

target() {
    os="$(uname -s)"
    arch="$(uname -m)"
    case "$os" in
        Linux)  os_part="linux" ;;
        Darwin) os_part="darwin" ;;
        *) die "no binary for $os. Install with: uv tool install elva-cli" ;;
    esac
    case "$arch" in
        x86_64|amd64)  arch_part="x86_64" ;;
        aarch64|arm64) if [ "$os_part" = darwin ]; then arch_part="arm64"; else arch_part="aarch64"; fi ;;
        *) die "no binary for $arch. Install with: uv tool install elva-cli" ;;
    esac
    echo "${BIN_NAME}-${os_part}-${arch_part}"
}

checksum() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | cut -d' ' -f1
    else
        die "need sha256sum or shasum to verify the download"
    fi
}

path_hint() {
    echo
    echo "$1 is not on your PATH. Add it:"
    case "${SHELL##*/}" in
        zsh)  echo "  echo 'export PATH=\"$1:\$PATH\"' >> ~/.zshrc && exec zsh" ;;
        fish) echo "  fish_add_path $1" ;;
        *)    echo "  echo 'export PATH=\"$1:\$PATH\"' >> ~/.bashrc && exec bash" ;;
    esac
}

main() {
    install_dir="${ELVA_INSTALL_DIR:-$HOME/.local/bin}"
    version="latest"

    while [ $# -gt 0 ]; do
        case "$1" in
            --version) [ $# -ge 2 ] || die "--version needs a value"; version="$2"; shift 2 ;;
            --install-dir) [ $# -ge 2 ] || die "--install-dir needs a value"; install_dir="$2"; shift 2 ;;
            -h|--help) usage; exit 0 ;;
            *) die "unknown option: $1" ;;
        esac
    done

    command -v curl >/dev/null 2>&1 || die "curl is required"
    asset="$(target)"

    if [ "$version" = latest ]; then
        base="https://github.com/$REPO/releases/latest/download"
    else
        base="https://github.com/$REPO/releases/download/$version"
    fi

    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT INT TERM

    echo "Downloading $asset ($version)"
    curl -fsSL "$base/$asset" -o "$tmp/$asset" || die "could not download $base/$asset"
    curl -fsSL "$base/SHA256SUMS" -o "$tmp/SHA256SUMS" || die "could not download the checksums for $version"

    expected="$(grep " \**$asset\$" "$tmp/SHA256SUMS" | cut -d' ' -f1)"
    [ -n "$expected" ] || die "$asset is not listed in SHA256SUMS"
    actual="$(checksum "$tmp/$asset")"
    [ "$actual" = "$expected" ] || die "checksum mismatch for $asset (expected $expected, got $actual)"

    mkdir -p "$install_dir"
    chmod +x "$tmp/$asset"

    mv -f "$tmp/$asset" "$install_dir/$BIN_NAME"

    echo "Installed $("$install_dir/$BIN_NAME" --version 2>/dev/null || echo unknown) to $install_dir/$BIN_NAME"
    case ":${PATH}:" in
        *":$install_dir:"*) ;;
        *) path_hint "$install_dir" ;;
    esac
}

main "$@"
