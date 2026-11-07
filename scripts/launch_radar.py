"""Start the local Streamlit radar as a detached Windows process."""

import http.client
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORT = 8501
HOST = "127.0.0.1"
URL = f"http://localhost:{PORT}"
OUT_LOG = ROOT / "streamlit.out.log"
ERR_LOG = ROOT / "streamlit.err.log"


def is_ready(timeout: float = 2.0) -> bool:
    connection = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        connection.request("GET", "/_stcore/health")
        response = connection.getresponse()
        body = response.read(64)
        return response.status == 200 and body.strip() == b"ok"
    except OSError:
        return False
    finally:
        connection.close()


def start_server() -> subprocess.Popen:
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with OUT_LOG.open("ab") as stdout, ERR_LOG.open("ab") as stderr:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "ui/app.py",
                "--server.port",
                str(PORT),
                "--server.address",
                HOST,
                "--server.headless",
                "true",
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=creation_flags,
            close_fds=True,
        )


def main() -> int:
    process = None
    if not is_ready():
        process = start_server()

    for _ in range(60):
        if is_ready():
            print(f"Tender radar is ready: {URL}")
            webbrowser.open(URL)
            return 0
        if process is not None and process.poll() is not None:
            error_tail = ""
            if ERR_LOG.exists():
                error_tail = ERR_LOG.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"Tender radar exited before becoming ready.\n{error_tail}")
        time.sleep(1)

    raise RuntimeError(f"Tender radar did not respond at {URL} within 60 seconds. Check {ERR_LOG}")


if __name__ == "__main__":
    raise SystemExit(main())
