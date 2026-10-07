#!/usr/bin/env bash
# Builds stable-diffusion.cpp's server as one self-contained binary (static, Metal shaders
# embedded): src-tauri/binaries/sd-server-<target-triple>. The core runs it to draw the shots
# with Z-Image, keeping the model loaded across a whole video.
set -euo pipefail

VERSION="master-929-3f8527a"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
OUT="$ROOT/src-tauri/binaries/sd-server-$TRIPLE"
CACHE="$ROOT/src-tauri/target/stable-diffusion.cpp-$VERSION"

if [[ -x "$OUT" && "$(cat "$OUT.version" 2>/dev/null)" == "$VERSION" ]]; then
  echo "sd-server $VERSION already built"
  exit 0
fi

# ggml is a git submodule, so a release tarball isn't enough.
if [[ ! -f "$CACHE/ggml/CMakeLists.txt" ]]; then
  rm -rf "$CACHE"
  git clone --quiet --depth 1 --branch "$VERSION" --recurse-submodules --shallow-submodules \
    https://github.com/leejet/stable-diffusion.cpp "$CACHE"
fi

cmake -S "$CACHE" -B "$CACHE/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=14.0 \
  -DBUILD_SHARED_LIBS=OFF \
  -DSD_BUILD_SHARED_LIBS=OFF \
  -DSD_METAL=ON \
  -DGGML_METAL_EMBED_LIBRARY=ON \
  -DGGML_NATIVE=OFF \
  -DGGML_BLAS=OFF > /dev/null
cmake --build "$CACHE/build" --config Release --target sd-server -j "$(sysctl -n hw.ncpu)" > /dev/null

mkdir -p "$(dirname "$OUT")"
cp "$(find "$CACHE/build" -name sd-server -type f -perm +111 | head -1)" "$OUT"
echo "$VERSION" > "$OUT.version"
echo "built $OUT"
