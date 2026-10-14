"""Launch the app: builds the UI if needed, then serves API + UI on http://127.0.0.1:8000

    python start.py            # build frontend if dist/ missing, then serve
    python start.py --rebuild  # force a frontend rebuild
    python start.py --port 9000
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(ROOT, "frontend")


def build_frontend(force: bool) -> None:
    if os.path.isdir(os.path.join(FRONTEND, "dist")) and not force:
        return
    npm = shutil.which("npm")
    if npm is None:
        print("npm not found: the API will run, but the UI needs `cd frontend && npm install && npm run build`.")
        return
    if not os.path.isdir(os.path.join(FRONTEND, "node_modules")):
        subprocess.run([npm, "install"], cwd=FRONTEND, check=True)
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    build_frontend(args.rebuild)
    sys.path.insert(0, ROOT)
    import uvicorn
    print(f"Open http://{args.host}:{args.port}")
    uvicorn.run("backend.api:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
