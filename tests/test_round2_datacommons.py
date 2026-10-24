"""Round 2: fetch_datacommons keeps DATACOMMONS_API_KEY in the X-API-Key header only. It never
appears in the URL, the request body, other headers, output files, stdout, or stderr, including
on every error path and across batches. No real network calls: a fake opener is injected."""

import io
import json
import socket
import urllib.error

import pytest

from scripts import fetch_datacommons as fdc

KEY = "round2-fake-key-XYZ-0001"


class Opener:
    """Records every request. `fail_on` = (request index, exception) raises on that call."""

    def __init__(self, fail_on=None, body=None):
        self.requests = []
        self.fail_on = fail_on
        self.body = body

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if self.fail_on and len(self.requests) - 1 == self.fail_on[0]:
            raise self.fail_on[1]
        if self.body is not None:
            return io.BytesIO(self.body)
        return io.BytesIO(json.dumps({"byVariable": {}, "facets": {}}).encode())


@pytest.fixture
def env(monkeypatch, tmp_path):
    # Padded on purpose: main() strips it, and the padded form must not leak either.
    monkeypatch.setenv("DATACOMMONS_API_KEY", f"  {KEY}\n")
    monkeypatch.setattr(fdc, "BATCH", 2)  # 4 Amherst ZIPs -> 2 requests
    monkeypatch.setattr(fdc.urllib.request, "urlopen", _no_network)
    raw = tmp_path / "raw"
    return raw, tmp_path / "missing.sqlite"


def _no_network(*a, **k):
    raise AssertionError("real network call")


def _assert_key_only_in_header(req):
    assert KEY not in req.full_url and req.full_url == fdc.API_URL
    assert req.get_method() == "POST"
    assert KEY not in (req.data or b"").decode()
    headers = dict(req.header_items())
    assert headers.get("X-api-key") == KEY
    others = {k: v for k, v in headers.items() if k != "X-api-key"}
    assert KEY not in json.dumps(others)


def _assert_no_leak(capsys, raw):
    out = capsys.readouterr()
    assert KEY not in out.out and KEY not in out.err
    if raw.exists():
        for f in raw.iterdir():
            assert KEY not in f.read_text(), f
    return out


def test_success_every_batch_keeps_key_in_header(env, capsys):
    raw, db = env
    opener = Opener()
    assert fdc.main(opener=opener, raw_dir=raw, db_path=db) == 0
    assert len(opener.requests) == 2
    for req in opener.requests:
        _assert_key_only_in_header(req)
    zips = [d for r in opener.requests for d in json.loads(r.data)["entity"]["dcids"]]
    assert zips == [f"zip/{z}" for z in fdc.AMHERST_ZIPS]
    out = _assert_no_leak(capsys, raw)
    assert "Wrote data/raw/datacommons.json" in out.out
    assert (raw / "datacommons.json").exists() and not (raw / "datacommons.json.part").exists()


@pytest.mark.parametrize("code", [400, 401, 403, 429, 500])
@pytest.mark.parametrize("batch", [0, 1])
def test_http_errors_never_print_key(env, capsys, code, batch):
    raw, db = env
    # The error's URL, message, and headers all carry the key, as a hostile server might echo it.
    err = urllib.error.HTTPError(
        f"{fdc.API_URL}?key={KEY}", code, f"bad key {KEY}", {"X-API-Key": KEY}, io.BytesIO(KEY.encode())
    )
    opener = Opener(fail_on=(batch, err))
    assert fdc.main(opener=opener, raw_dir=raw, db_path=db) == 1
    for req in opener.requests:
        _assert_key_only_in_header(req)
    out = _assert_no_leak(capsys, raw)
    assert f"HTTP {code}" in out.err
    assert not (raw / "datacommons.json").exists()


@pytest.mark.parametrize(
    "exc, name",
    [
        (urllib.error.URLError(f"connection refused for {KEY}"), "URLError"),
        (TimeoutError(f"timed out {KEY}"), "TimeoutError"),
        (socket.timeout(f"timed out {KEY}"), "TimeoutError"),
    ],
)
def test_network_errors_never_print_key(env, capsys, exc, name):
    raw, db = env
    assert fdc.main(opener=Opener(fail_on=(0, exc)), raw_dir=raw, db_path=db) == 1
    out = _assert_no_leak(capsys, raw)
    assert name in out.err


def test_bad_json_never_prints_key(env, capsys):
    raw, db = env
    opener = Opener(body=f"not json {KEY}".encode())
    assert fdc.main(opener=opener, raw_dir=raw, db_path=db) == 1
    out = _assert_no_leak(capsys, raw)
    assert "JSONDecodeError" in out.err
    assert not (raw / "datacommons.json").exists()


def test_blank_key_makes_no_request(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DATACOMMONS_API_KEY", "   ")
    opener = Opener()
    assert fdc.main(opener=opener, raw_dir=tmp_path, db_path=tmp_path / "x.sqlite") == 0
    assert opener.requests == []
    assert "DATACOMMONS_API_KEY is not set" in capsys.readouterr().out
