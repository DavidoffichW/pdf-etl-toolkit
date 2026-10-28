from __future__ import annotations

import subprocess
import socket
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_probe:
    port_probe.bind(("127.0.0.1", 0))
    PORT = int(port_probe.getsockname()[1])
creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
process = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app.py",
        "--server.headless=true",
        f"--server.port={PORT}",
        "--server.address=127.0.0.1",
    ],
    cwd=ROOT,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    creationflags=creationflags,
)

try:
    response = None
    for _ in range(60):
        if process.poll() is not None:
            break
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/_stcore/health", timeout=1
            ) as health:
                response = (health.status, health.read().decode("utf-8"))
            if response == (200, "ok"):
                break
        except Exception:
            time.sleep(0.25)
    if response != (200, "ok"):
        raise RuntimeError(f"Streamlit health check failed: {response!r}")
finally:
    process.terminate()
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=10)
    if process.returncode not in {0, -15, 1}:
        print(stdout)
        print(stderr, file=sys.stderr)
