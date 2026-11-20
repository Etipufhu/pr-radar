#!/usr/bin/env sh
# Fetch the SemEval-2026 Task 3 (DimABSA) data. The organisers allow research use
# but not redistribution, so the data is downloaded here and never committed.
set -eu
DEST="${1:-data/external/DimABSA2026}"
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" pull --ff-only
else
  git clone --depth 1 https://github.com/DimABSA/DimABSA2026.git "$DEST"
fi
