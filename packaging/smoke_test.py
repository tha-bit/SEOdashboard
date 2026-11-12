from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def get(url: str, timeout: float = 2) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"Unexpected HTTP status {response.status} for {url}")
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="seo-dashboard-smoke-") as temporary:
        data_dir = Path(temporary)
        environment = {**os.environ, "SEO_DATA_DIR": str(data_dir)}
        process = subprocess.Popen([str(args.executable), "--no-browser"], env=environment)
        try:
            runtime_file = data_dir / "runtime.json"
            for _ in range(180):
                if runtime_file.exists():
                    runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
                    base = f"http://127.0.0.1:{runtime['port']}"
                    try:
                        health = json.loads(get(f"{base}/api/health"))
                        index = get(base).decode("utf-8")
                        if health.get("status") == "ok" and '<div id="root"></div>' in index:
                            break
                    except OSError:
                        pass
                if process.poll() is not None:
                    raise RuntimeError(f"Packaged application exited with {process.returncode}")
                time.sleep(0.25)
            else:
                raise RuntimeError("Packaged application did not become ready")
            stopped = subprocess.run([str(args.executable), "--stop"], env=environment, timeout=15)
            if stopped.returncode != 0:
                raise RuntimeError("Packaged stop command failed")
            process.wait(timeout=15)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
