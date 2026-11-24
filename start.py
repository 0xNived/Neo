"""Start Neo's local development dashboard (API + background worker)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    dashboard = shutil.which("mprocs")
    if not dashboard:
        print("Neo's local dashboard needs mprocs. Install it once with:")
        print("  npm install --global mprocs")
        return 1
    return subprocess.run(
        [dashboard, "--config", str(ROOT / "mprocs.yaml")],
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
