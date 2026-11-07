import parsers.common as common


def test_html_to_text_uses_trafilatura_when_available(monkeypatch):
    class FakeTrafilatura:
        @staticmethod
        def extract(*args, **kwargs):
            return "核心公告正文\n预算金额：120万元"

    monkeypatch.setattr(common, "trafilatura", FakeTrafilatura)

    assert common.html_to_text("<html><body>fallback</body></html>") == "核心公告正文 预算金额：120万元 fallback"


def test_html_to_text_falls_back_to_beautifulsoup(monkeypatch):
    monkeypatch.setattr(common, "trafilatura", None)

    assert common.html_to_text("<html><script>x()</script><body>公告 正文</body></html>") == "公告 正文"
