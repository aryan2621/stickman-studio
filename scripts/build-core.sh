#!/usr/bin/env bash
# Builds the Python core into one self-contained executable (PyInstaller: Python, Kokoro's ONNX
# runtime, Pillow and a static ffmpeg) and puts it where Tauri expects the sidecar:
#   src-tauri/binaries/stickman-core-<target-triple>
# Users don't need Python installed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/core"

TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
OUT="$ROOT/src-tauri/binaries/stickman-core-$TRIPLE"

# Nothing to do when the binary is newer than every core source file.
if [[ -f "$OUT" && -z "$(find stickman_core core_entry.py pyproject.toml -newer "$OUT" 2>/dev/null)" ]]; then
  echo "stickman-core is up to date"
  exit 0
fi

uv sync --quiet
uv run python -m PyInstaller --onefile --clean --noconfirm --log-level WARN \
  --name stickman-core --distpath build/dist --workpath build/work --specpath build \
  --collect-all kokoro_onnx --collect-all espeakng_loader --collect-all language_tags \
  --collect-binaries imageio_ffmpeg --collect-binaries onnxruntime \
  --collect-submodules keyring --copy-metadata keyring --collect-submodules truststore \
  core_entry.py

mkdir -p "$(dirname "$OUT")"
cp build/dist/stickman-core "$OUT"
echo "built $OUT"
