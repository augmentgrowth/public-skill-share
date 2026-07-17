#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: render_google_docx.sh INPUT.md OUTPUT.docx [ROUNDTRIP.md]" >&2
}

if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage
  exit 2
fi

INPUT=$1
OUTPUT=$2
ROUNDTRIP=${3:-"${OUTPUT%.docx}.roundtrip.md"}

if [[ ! -f "$INPUT" ]]; then
  echo "ERROR: Markdown input not found: $INPUT" >&2
  exit 1
fi
if ! command -v pandoc >/dev/null 2>&1; then
  echo "ERROR: pandoc is required for the conservative Google-compatible DOCX profile" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")" "$(dirname "$ROUNDTRIP")"
PANDOC_ARGS=("$INPUT" --from=gfm --to=docx --standalone --output="$OUTPUT")
if [[ -n "${REFERENCE_DOCX:-}" ]]; then
  if [[ ! -f "$REFERENCE_DOCX" ]]; then
    echo "ERROR: REFERENCE_DOCX not found: $REFERENCE_DOCX" >&2
    exit 1
  fi
  PANDOC_ARGS+=(--reference-doc="$REFERENCE_DOCX")
fi
pandoc "${PANDOC_ARGS[@]}"
pandoc "$OUTPUT" --from=docx --to=gfm --wrap=none --output="$ROUNDTRIP"

for heading in \
  "## Current-state workflow outline" \
  "## Verification questions for the client" \
  "## Detailed extraction and source evidence"; do
  if ! grep -Fq "$heading" "$ROUNDTRIP"; then
    echo "ERROR: DOCX round-trip lost required heading: $heading" >&2
    exit 1
  fi
done

RECEIPT="${OUTPUT}.validation.json"
python3 - "$INPUT" "$OUTPUT" "$ROUNDTRIP" "$RECEIPT" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

input_path, output_path, roundtrip_path, receipt_path = map(Path, sys.argv[1:])
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

required_headings = [
    "## Current-state workflow outline",
    "## Verification questions for the client",
    "## Detailed extraction and source evidence",
]

def section_bodies(text):
    bodies = {}
    for heading in required_headings:
        start = text.index(heading) + len(heading)
        next_heading = re.search(r"(?m)^## ", text[start:])
        end = start + next_heading.start() if next_heading else len(text)
        bodies[heading] = " ".join(text[start:end].split())
    return bodies

canonical_bodies = section_bodies(input_path.read_text(encoding="utf-8"))
roundtrip_bodies = section_bodies(roundtrip_path.read_text(encoding="utf-8"))
for heading in required_headings:
    canonical_length = len(canonical_bodies[heading])
    roundtrip_length = len(roundtrip_bodies[heading])
    if canonical_length == 0 or roundtrip_length < canonical_length * 0.8:
        raise SystemExit(
            f"ERROR: DOCX round-trip lost substantial content under {heading}: "
            f"canonical={canonical_length}, roundtrip={roundtrip_length}"
        )

receipt_path.write_text(json.dumps({
    "status": "validated-local-roundtrip",
    "canonical_markdown": str(input_path.resolve()),
    "docx": str(output_path.resolve()),
    "roundtrip_markdown": str(roundtrip_path.resolve()),
    "sha256": {
        "canonical_markdown": digest(input_path),
        "docx": digest(output_path),
        "roundtrip_markdown": digest(roundtrip_path),
    },
    "section_character_counts": {
        heading: {
            "canonical": len(canonical_bodies[heading]),
            "roundtrip": len(roundtrip_bodies[heading]),
        }
        for heading in required_headings
    },
}, indent=2) + "\n", encoding="utf-8")
PY

echo "Validated local Markdown → DOCX → Markdown round-trip: $OUTPUT"
