from pathlib import Path

from scripts.launch_radar import is_ready


LAUNCHER = Path("scripts/launch_radar.py")
CMD = Path("scripts/start_exhibition_tender_radar.cmd")


def test_launcher_uses_detached_process_and_loopback_health_check():
    text = LAUNCHER.read_text(encoding="utf-8")

    assert 'HOST = "127.0.0.1"' in text
    assert "subprocess.DETACHED_PROCESS" in text
    assert "subprocess.CREATE_NEW_PROCESS_GROUP" in text
    assert "for _ in range(60)" in text


def test_double_click_command_uses_relative_python_launcher():
    text = CMD.read_text(encoding="utf-8")

    assert 'python "%~dp0launch_radar.py"' in text
    assert "start_exhibition_tender_radar.ps1" not in text


def test_launcher_does_not_accept_unrelated_http_200_service(monkeypatch):
    class Connection:
        def __init__(self, *args, **kwargs):
            self.status = 200

        def request(self, method, path):
            assert path == "/_stcore/health"

        def getresponse(self):
            return self

        def read(self, size):
            return b"<html>Another service</html>"

        def close(self):
            pass

    monkeypatch.setattr("scripts.launch_radar.http.client.HTTPConnection", Connection)
    assert not is_ready()
