#!/usr/bin/env bash
# Build the trybox sandbox image with Apple's container CLI.
set -euo pipefail

CTXT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_REF="${TRYBOX_IMAGE_REF:-local/trybox-sandbox:latest}"

echo "building $IMAGE_REF from $CTXT_DIR"
container build \
  --tag "$IMAGE_REF" \
  --file "$CTXT_DIR/Containerfile" \
  "$CTXT_DIR"

echo "built. container image ls:"
container image ls | grep -i trybox || true
