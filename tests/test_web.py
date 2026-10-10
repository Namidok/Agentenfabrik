import socket

import httpx
import pytest

from factory.web import WebError, fetch_page, normalize_domain

HTML = """<html><head><title>Jobs</title><style>p{}</style><script>alert(1)</script></head>
<body><h1>Internships</h1><p>Backend intern</p><a href="/job/1">Apply here</a></body></html>"""


def public(host):
    return ["93.184.216.34"]


def page(request):
    return httpx.Response(200, text=HTML, headers={"content-type": "text/html; charset=utf-8"})


def fetch(handler, url="https://jobs.example.com/list", allowed=("example.com",),
          resolver=public, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return fetch_page(url, list(allowed), client=client, resolver=resolver, **kw)


def test_html_becomes_text_with_links():
    out = fetch(page)
    assert "Backend intern" in out
    assert "Apply here [https://jobs.example.com/job/1]" in out
    assert "Title: Jobs" in out
    assert "alert(1)" not in out
    assert "untrusted" in out


def test_domain_not_allowed():
    calls = []

    def handler(request):
        calls.append(request)
        return page(request)

    with pytest.raises(WebError, match="not an allowed website"):
        fetch(handler, url="https://evil.com/x")
    assert calls == []


def test_lookalike_domain_is_blocked():
    with pytest.raises(WebError, match="not an allowed website"):
        fetch(page, url="https://notexample.com/x")


def test_non_http_scheme_is_blocked():
    with pytest.raises(WebError, match="Only http and https"):
        fetch(page, url="file:///etc/passwd")


def test_private_address_is_blocked():
    with pytest.raises(WebError, match="private"):
        fetch(page, resolver=lambda host: ["127.0.0.1"])


def test_unknown_host():
    def boom(host):
        raise socket.gaierror("no such host")

    with pytest.raises(WebError, match="Could not find"):
        fetch(page, resolver=boom)


def test_redirect_to_disallowed_site_is_blocked():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://evil.com/"})

    with pytest.raises(WebError, match="not an allowed website"):
        fetch(handler)


def test_redirect_is_followed_when_allowed():
    def handler(request):
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})
        return httpx.Response(200, text="arrived")

    assert "arrived" in fetch(handler, url="https://example.com/a")


def test_too_many_redirects():
    def handler(request):
        return httpx.Response(302, headers={"location": "/loop"})

    with pytest.raises(WebError, match="Too many redirects"):
        fetch(handler)


def test_http_error_status():
    with pytest.raises(WebError, match="HTTP 404"):
        fetch(lambda request: httpx.Response(404, text="nope"))


def test_unsupported_content_type():
    def handler(request):
        return httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})

    with pytest.raises(WebError, match="Unsupported content type"):
        fetch(handler)


def test_json_passes_through():
    out = fetch(lambda request: httpx.Response(200, json={"jobs": [{"title": "Intern"}]}))
    assert "jobs" in out and "Intern" in out


def test_paging_with_offset():
    handler = lambda request: httpx.Response(200, text="x" * 20000)
    assert "offset=8000" in fetch(handler)
    last = fetch(handler, offset=16000)
    assert "more content" not in last


def test_offset_past_end():
    with pytest.raises(WebError, match="past the end"):
        fetch(lambda request: httpx.Response(200, text="short"), offset=100)


def test_huge_page_is_capped():
    out = fetch(lambda request: httpx.Response(200, text="x" * 2_000_000))
    assert "1000000 characters in total" in out


def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(WebError, match="timed out"):
        fetch(handler)


def test_normalize_domain():
    assert normalize_domain("https://Example.com/path") == "example.com"
    assert normalize_domain("  Example.COM ") == "example.com"
