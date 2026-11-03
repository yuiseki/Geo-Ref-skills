"""Run every test with the command on its first line, from the directory that holds its scripts/.

    python3 run_tests.py [filter]

Each test file starts with the uvx command that brings what it imports. Prints one line per file and exits 1
if any fails. Network tests stay skipped unless GEOREF_NETWORK=1 is set.
"""

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    pat = sys.argv[1] if len(sys.argv) > 1 else ""
    files = sorted(ROOT.glob(".agents/skills/*/scripts/test_*.py")) + sorted(ROOT.glob("evals/scripts/test_*.py"))
    failed = []
    env = {**os.environ, "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", "2")}
    for f in files:
        if pat not in str(f):
            continue
        first = f.read_text(encoding="utf-8").splitlines()[0]
        if not first.startswith("# uvx "):
            failed.append(f)
            print(f"NO COMMAND  {f.relative_to(ROOT)}")
            continue
        cmd = shlex.split(first[2:]) + ["-q", "-p", "no:cacheprovider"]
        t0 = time.time()
        r = subprocess.run(cmd, cwd=f.parent.parent, capture_output=True, text=True, env=env)
        last = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
        status = "ok  " if r.returncode == 0 else "FAIL"
        print(f"{status} {time.time() - t0:5.0f}s {f.relative_to(ROOT)}  {last}", flush=True)
        if r.returncode != 0:
            failed.append(f)
    print(f"{len(failed)} failed" if failed else "all passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
