"""Desktop server bootstrap (no GUI): server starts in a thread and serves."""
import urllib.request

from sprint_pulse import desktop


def test_start_server_serves_health(monkeypatch, tmp_path):
    # Use a temp on-disk DB so the in-thread server and this thread agree.
    monkeypatch.setenv("SPRINT_PULSE_DB", str(tmp_path / "sp.db"))
    port = desktop._free_port()
    server = desktop.start_server(port)
    try:
        assert desktop._wait_health(port, timeout=15)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            assert r.status == 200
    finally:
        server.should_exit = True
