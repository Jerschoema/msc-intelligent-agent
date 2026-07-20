import io
import urllib.error

import src.tools.web_fetch as web_fetch_mod
from src.tools.web_fetch import fetch_html, html_to_text


class _FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode()

    def read(self):
        return self._body

    @property
    def headers(self):
        class _H:
            @staticmethod
            def get_content_charset():
                return "utf-8"
        return _H()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(monkeypatch, body: str):
    monkeypatch.setattr(web_fetch_mod.urllib.request, "urlopen", lambda *a, **kw: _FakeResponse(body))


def test_html_to_text_strips_script_and_style():
    html = "<html><head><style>p{color:red}</style><script>var x=1;</script></head><body><p>Real  text</p></body></html>"
    assert html_to_text(html) == "Real text"


def test_ok_page_returns_extracted_text(monkeypatch):
    _serve(monkeypatch, "<html><body><article>" + "Study finding sentence. " * 30 + "</article></body></html>")
    status, text = fetch_html("http://open.example/a")
    assert status == "ok"
    assert "Study finding sentence." in text


def test_cloudflare_interstitial_is_captcha(monkeypatch):
    _serve(monkeypatch, "<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>")
    status, text = fetch_html("http://guarded.example/a")
    assert status == "captcha" and text == ""


def test_http_403_is_captcha(monkeypatch):
    def blocked(*a, **kw):
        raise urllib.error.HTTPError("url", 403, "Forbidden", None, io.BytesIO(b""))

    monkeypatch.setattr(web_fetch_mod.urllib.request, "urlopen", blocked)
    assert fetch_html("http://publisher.example/a") == ("captcha", "")


def test_network_failure_is_error(monkeypatch):
    def boom(*a, **kw):
        raise OSError("no route")

    monkeypatch.setattr(web_fetch_mod.urllib.request, "urlopen", boom)
    assert fetch_html("http://gone.example/a") == ("error", "")


def test_empty_js_shell_is_error(monkeypatch):
    _serve(monkeypatch, "<html><body><div id='app'></div></body></html>")
    status, _ = fetch_html("http://spa.example/a")
    assert status == "error"
