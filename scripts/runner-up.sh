#!/usr/bin/env bash
# Portable GitHub Actions self-hosted runner bootstrap.
#
# Same script works on WSL2-Ubuntu and the homelab Ubuntu host (both Linux).
# Idempotent: downloads the runner once, configures once per machine, then just
# runs. Re-running after the first time simply starts the runner again.
#
# Usage:
#   REPO=owner/name ./scripts/runner-up.sh
#       -> mints a registration token automatically if `gh` is installed+auth'd
#   REPO=owner/name RUNNER_TOKEN=ABC123 ./scripts/runner-up.sh
#       -> use a token you copied from
#          https://github.com/<owner>/<name>/settings/actions/runners/new
#
# Optional env:
#   RUNNER_DIR   install location           (default: $HOME/actions-runner)
#   LABELS       runner labels              (default: self-hosted)
#                e.g. LABELS=self-hosted,homelab to target the deploy job here
#   RUNNER_NAME  runner name in GitHub UI   (default: <hostname>-<user>)
#   AS_SERVICE=1 install as a systemd service instead of foreground
#                (homelab: survives reboots; needs systemd — see notes below)
set -euo pipefail

REPO="${REPO:?Set REPO=owner/name (the GitHub repo the runner attaches to)}"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"
LABELS="${LABELS:-self-hosted}"
RUNNER_NAME="${RUNNER_NAME:-$(hostname)-$(whoami)}"

# --- resolve latest runner version (fallback pinned) ------------------------
if [ -z "${RUNNER_VERSION:-}" ]; then
  RUNNER_VERSION="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \
    | grep -oP '"tag_name":\s*"v\K[^"]+' || true)"
  RUNNER_VERSION="${RUNNER_VERSION:-2.321.0}"
fi

case "$(uname -m)" in
  x86_64)  ARCH=x64 ;;
  aarch64) ARCH=arm64 ;;
  *) echo "Unsupported arch: $(uname -m)"; exit 1 ;;
esac

mkdir -p "$RUNNER_DIR"; cd "$RUNNER_DIR"

# --- 1. download the runner once --------------------------------------------
if [ ! -x ./run.sh ]; then
  TARBALL="actions-runner-linux-${ARCH}-${RUNNER_VERSION}.tar.gz"
  echo ">> downloading runner v${RUNNER_VERSION} (${ARCH})"
  curl -fsSL -o "$TARBALL" \
    "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${TARBALL}"
  tar xzf "$TARBALL" && rm -f "$TARBALL"
fi

# --- 2. configure once (idempotent: .runner exists once registered) ---------
if [ ! -f .runner ]; then
  TOKEN="${RUNNER_TOKEN:-}"
  if [ -z "$TOKEN" ]; then
    if command -v gh >/dev/null 2>&1; then
      echo ">> minting a registration token via gh"
      TOKEN="$(gh api -X POST "repos/${REPO}/actions/runners/registration-token" --jq .token)"
    else
      echo "No RUNNER_TOKEN set and gh not installed."
      echo "Grab a one-hour token here, then re-run with RUNNER_TOKEN=...:"
      echo "  https://github.com/${REPO}/settings/actions/runners/new"
      exit 1
    fi
  fi
  echo ">> configuring runner '${RUNNER_NAME}' (labels: ${LABELS})"
  ./config.sh --url "https://github.com/${REPO}" --token "$TOKEN" \
    --name "$RUNNER_NAME" --labels "$LABELS" --unattended --replace
fi

# --- 3. run -----------------------------------------------------------------
if [ "${AS_SERVICE:-0}" = "1" ]; then
  echo ">> installing + starting systemd service"
  sudo ./svc.sh install "$(whoami)"
  sudo ./svc.sh start
  sudo ./svc.sh status
else
  echo ">> starting runner in the foreground (Ctrl-C to stop)"
  ./run.sh
fi
