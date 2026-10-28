#!/usr/bin/env bash
set -euo pipefail
# Usage: build.sh <empty-output-directory> <output-tag>
if [[ $# != 2 ]]; then
  echo 'usage: build.sh OUTPUT_DIRECTORY OUTPUT_IMAGE' >&2
  exit 2
fi
output_dir=$1
image_tag=$2
if [[ -e "$output_dir" ]]; then
  echo 'Output directory must not exist; use a fresh disposable directory.' >&2
  exit 2
fi
mkdir -p -- "$output_dir"
output_dir=$(cd -- "$output_dir" && pwd)
git clone --no-checkout https://github.com/ronigooja/chatgpt-web-voice.git "$output_dir/source"
git -C "$output_dir/source" checkout --detach 6338ac478070aaa34bfe7a3c0469caf9e9174c02
(
  cd "$output_dir/source"
  env -u GOOS -u GOARCH go test ./...
  CGO_ENABLED=0 GOOS=linux go build -trimpath -buildvcs=false -ldflags='-s -w' -o "$output_dir/server" ./cmd/server
)
docker build --tag "$image_tag" "$output_dir/source"
