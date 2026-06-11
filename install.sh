#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  cat >&2 <<'EOF'
uv is required before installing bester-ytm.

Install uv first:
  macOS:          brew install uv
  Arch Linux:    sudo pacman -S --needed uv
  Ubuntu/Debian: curl -LsSf https://astral.sh/uv/install.sh | sh
EOF
  exit 1
fi

echo "Installing bester-ytm from ${repo_dir}"
uv tool install --force --reinstall "${repo_dir}"

tool_bin="$(cd "$(uv tool dir --bin)" && pwd)"
path_was_ready=0
case ":${PATH}:" in
  *":${tool_bin}:"*) path_was_ready=1 ;;
esac

echo "Ensuring uv's tool directory is on PATH"
uv tool update-shell

export PATH="${tool_bin}:${PATH}"

if ! command -v bester-ytm >/dev/null 2>&1; then
  cat >&2 <<EOF
bester-ytm was installed, but this shell still cannot find it.

Run this once in the current shell:
  export PATH="${tool_bin}:\$PATH"

Then retry:
  bester-ytm --help
EOF
  exit 1
fi

bester-ytm --help >/dev/null

cat <<EOF
bester-ytm installed successfully.

Start it from any directory with:
  bester-ytm

EOF

if [[ "${path_was_ready}" -eq 0 ]]; then
  cat <<EOF
This installer updated your shell startup files. For this already-open terminal,
run this once before starting bester-ytm:
  export PATH="${tool_bin}:\$PATH"

EOF
fi

cat <<EOF
If another terminal cannot find it, open a new terminal or run:
  export PATH="${tool_bin}:\$PATH"
EOF
