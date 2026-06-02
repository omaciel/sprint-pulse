"""Desktop entry point: run the FastAPI app in-process and show it in a native
window via pywebview. Pure Python — no Rust, no Node, no separate process.

The same FastAPI app powers the container; here we just wrap it in an OS webview
(WebKit on macOS, WebKitGTK on Linux).
"""
from __future__ import annotations

import os
import socket
import threading
import time
import urllib.request

import uvicorn

from sprint_pulse.web.app import create_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_health(port: int, timeout: float = 30.0) -> bool:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:  # noqa: S310 (localhost)
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def start_server(port: int) -> uvicorn.Server:
    """Start the app in a daemon thread; return the running Server.

    Separated from ``main`` so it can be tested without opening a window.
    """
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    return server


def main() -> None:
    port = int(os.environ.get("SPRINT_PULSE_PORT") or _free_port())
    server = start_server(port)

    # Smoke mode: verify the (possibly frozen) bundle serves AND renders a
    # bundled template, then exit. No GUI. Used to validate the frozen app.
    if os.environ.get("SPRINT_PULSE_SMOKE") == "1":
        ok = _wait_health(port)
        if ok:
            try:
                with urllib.request.urlopen(  # noqa: S310 (localhost)
                    f"http://127.0.0.1:{port}/setup", timeout=3
                ) as r:
                    ok = r.status == 200 and b"Sprint Pulse" in r.read()
            except Exception:
                ok = False
        server.should_exit = True
        print("SMOKE_OK" if ok else "SMOKE_FAIL")
        raise SystemExit(0 if ok else 1)

    import webview  # imported lazily so headless tests don't require a display

    if not _wait_health(port):
        webview.create_window(
            "Sprint Pulse — error",
            html="<h1>Server failed to start</h1><p>Check the logs.</p>",
        )
        webview.start()
        return

    webview.create_window(
        "Sprint Pulse", f"http://127.0.0.1:{port}/", width=1280, height=860
    )
    webview.start()  # blocks until the window closes
    server.should_exit = True


if __name__ == "__main__":
    main()
