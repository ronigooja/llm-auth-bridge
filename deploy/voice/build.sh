#!/usr/bin/env bash
set -euo pipefail
# Usage: build.sh <empty-output-directory> <immutable-runtime-image> <output-tag>
if [[ $# != 3 ]]; then
  echo 'usage: build.sh OUTPUT_DIRECTORY VOICE_BASE_IMAGE OUTPUT_IMAGE' >&2
  exit 2
fi
asset_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
output_dir=$1
runtime_image=$2
image_tag=$3
if [[ -e "$output_dir" ]]; then
  echo 'Output directory must not exist; use a fresh disposable directory.' >&2
  exit 2
fi
mkdir -p -- "$output_dir"
output_dir=$(cd -- "$output_dir" && pwd)
(cd "$asset_dir" && sha256sum -c bridge-v1.patch.sha256)
git clone --no-checkout https://github.com/Space3044/chatgpt-web-voice.git "$output_dir/source"
git -C "$output_dir/source" checkout --detach 6338ac478070aaa34bfe7a3c0469caf9e9174c02
git -C "$output_dir/source" apply --check "$asset_dir/bridge-v1.patch"
git -C "$output_dir/source" apply "$asset_dir/bridge-v1.patch"
(
  cd "$output_dir/source"
  go test ./...
  CGO_ENABLED=0 GOOS=linux go build -trimpath -buildvcs=false -ldflags='-s -w' -o "$output_dir/server" ./cmd/server
)
cp -- "$asset_dir/Dockerfile" "$output_dir/Dockerfile"
printf 'source/\n' > "$output_dir/.dockerignore"
patch_hash=$(sha256sum "$asset_dir/bridge-v1.patch")
patch_hash=${patch_hash%% *}
docker build --build-arg "VOICE_BASE_IMAGE=$runtime_image" --build-arg "BRIDGE_PATCH_SHA256=$patch_hash" --tag "$image_tag" "$output_dir"
