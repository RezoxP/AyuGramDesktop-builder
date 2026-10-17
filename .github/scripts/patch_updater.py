#!/usr/bin/env python3
"""
Wrapper for backward compatibility. Delegates to apply_patches.py.
"""
import sys
import subprocess
from pathlib import Path

scripts_dir = Path(__file__).resolve().parent
apply_script = scripts_dir / "apply_patches.py"

if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, str(apply_script)] + sys.argv[1:]))
