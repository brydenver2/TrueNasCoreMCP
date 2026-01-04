#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REGISTRY_HOST="registry.local.wallacearizona.us"
IMAGE_NAME="truenas-mcp-server"

usage() {
  cat <<'USAGE'
Usage: scripts/build-and-push.sh [version]

Builds the Docker image for TrueNAS MCP Server and pushes it to registry.local.wallacearizona.us.
If no version is provided, the script reads the version from pyproject.toml.
USAGE
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker CLI not found in PATH" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "[ERROR] docker daemon is unreachable" >&2
  exit 1
fi

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 is required to read pyproject.toml" >&2
    exit 1
  fi
    VERSION="$(python3 <<'PY'
import pathlib

pyproject = pathlib.Path('pyproject.toml')
if not pyproject.exists():
    raise SystemExit('pyproject.toml not found; please supply the version explicitly')

section = None
version = None
for raw_line in pyproject.read_text().splitlines():
    line = raw_line.strip()
    if not line or line.startswith('#'):
        continue
    if line.startswith('[') and line.endswith(']'):
        section = line.strip('[]').strip()
        continue
    if section == 'project' and line.startswith('version'):
        _, value = line.split('=', 1)
        version = value.strip().strip('"').strip("'")
        break

if not version:
    raise SystemExit('version missing from [project] section; please supply manually')

print(version)
PY
  )"
fi

IMAGE_TAG_VERSION="${REGISTRY_HOST}/${IMAGE_NAME}:${VERSION}"
IMAGE_TAG_LATEST="${REGISTRY_HOST}/${IMAGE_NAME}:latest"

echo "[INFO] Building image ${IMAGE_TAG_VERSION}"
docker build --pull --tag "$IMAGE_TAG_VERSION" --tag "$IMAGE_TAG_LATEST" .

echo "[INFO] Pushing ${IMAGE_TAG_VERSION}"
docker push "$IMAGE_TAG_VERSION"

echo "[INFO] Pushing ${IMAGE_TAG_LATEST}"
docker push "$IMAGE_TAG_LATEST"

echo "[INFO] Done."
