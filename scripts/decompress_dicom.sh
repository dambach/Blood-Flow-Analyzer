#!/usr/bin/env bash
# Decompress DICOM files in a directory using dcmdjpeg (dcmtk)
# Usage: ./scripts/decompress_dicom.sh <input_dir> <output_dir>

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <input_dir> <output_dir>"
  exit 2
fi

INPUT_DIR="$1"
OUTPUT_DIR="$2"

if ! command -v dcmdjpeg >/dev/null 2>&1; then
  echo "dcmdjpeg not found. Install dcmtk (Homebrew: brew install dcmtk) or ensure dcmdjpeg in PATH." >&2
  exit 3
fi

mkdir -p "$OUTPUT_DIR"

for f in "$INPUT_DIR"/*; do
  [ -e "$f" ] || continue
  base=$(basename "$f")
  out="$OUTPUT_DIR/$base"
  echo "Processing: $f -> $out"
  if dcmdjpeg -O "$out" "$f"; then
    echo "Decompressed -> $out"
  else
    echo "dcmdjpeg failed for $f, copying original" >&2
    cp "$f" "$out"
  fi
done

echo "Done. Decompressed files in $OUTPUT_DIR"