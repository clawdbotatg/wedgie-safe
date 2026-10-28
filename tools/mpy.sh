#!/bin/sh
# Build the .mpy files wedgie.json ships (the wedgie runs these; the .py next to each is the source).
# Compiling a big .py on the wedgie needs one free block it often doesn't have (MemoryError mid-swap, 10-27).
# Run after editing any of these, and commit both.
cd "$(dirname "$0")/.." || exit 1
for m in safe_7730 safe_read safe_wire safe_8362 safe_book safe_sim safe_msg; do
  uv run -q --with mpy-cross==1.29.0.post2 python3 -c "import mpy_cross,subprocess,sys;subprocess.run([mpy_cross.mpy_cross,'-s',sys.argv[1]+'.py','-o',sys.argv[1]+'.mpy',sys.argv[1]+'.py'],check=True)" "$m" || exit 1
done
