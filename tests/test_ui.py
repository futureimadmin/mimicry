import io, json, threading, urllib.request, urllib.error
import numpy as np
import pytest

sf = pytest.importorskip("soundfile")
pytest.importorskip("pedalboard")

from http.server import ThreadingHTTPServer
from mimicry.config import Config
from mimicry.ui.server import App, make_handler


def voice(f, secs, sr=48000):
    t = np.arange(int(secs * sr)) / sr
    x = sum(0.3 / k * np.sin(2 * np.pi * f * k * t) for k in range(1, 6)) * (0.6 + 0.4 * np.sin(2 * np.pi * 2 * t))
    return (x + 0.003 * np.random.randn(len(t))).astype("float32")


def wav(x, sr=48000):
    b = io.BytesIO(); sf.write(b, x, sr, format="WAV", subtype="FLOAT"); return b.getvalue()


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = App(Config())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = make_handler(app, port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield app, f"http://127.0.0.1:{port}"
    httpd.shutdown()


def call(base, app, path, data=None, token=True, method=None):
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"))
    if token:
        req.add_header("X-Mimicry-Token", app.token)
    try:
        r = urllib.request.urlopen(req)
        return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_security(server):
    app, base = server
    assert call(base, app, "/api/state", token=False)[0] == 403
    code, body, _ = call(base, app, "/")
    assert code == 200 and app.token.encode() in body
    # wrong Host header (DNS-rebinding style) is refused even with a valid token
    req = urllib.request.Request(base + "/api/state", headers={"X-Mimicry-Token": app.token, "Host": "evil.com"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403


def test_state(server):
    app, base = server
    code, body, _ = call(base, app, "/api/state")
    s = json.loads(body)
    assert code == 200 and s["status"] == "idle" and "consent_text" in s


def test_full_flow_enroll_and_try(server):
    app, base = server
    c, b, _ = call(base, app, "/api/upload?kind=target", wav(voice(220, 12)))
    tgt = json.loads(b)
    assert c == 200 and tgt["metrics"]["duration_s"] >= 11
    src = json.loads(call(base, app, "/api/upload?kind=source", wav(voice(120, 6)))[1])
    # consent is mandatory
    c, b, _ = call(base, app, "/api/enroll", json.dumps({"target": tgt["id"], "source": src["id"], "name": "t1"}).encode())
    assert c == 400 and "consent" in json.loads(b)["error"]
    # path traversal / bad ids rejected
    c, _, _ = call(base, app, "/api/enroll", json.dumps({"target": "../../etc/passwd", "consent": True}).encode())
    assert c == 400
    c, b, _ = call(base, app, "/api/enroll", json.dumps({"target": tgt["id"], "source": src["id"], "name": "t1", "consent": True}).encode())
    assert c == 200, b
    assert json.loads(call(base, app, "/api/state")[1])["profiles"][0]["name"] == "t1"
    # try-it conversion uses the pitch fallback here (no torch in test env)
    c, out, h = call(base, app, "/api/convert?profile=t1", wav(voice(120, 3)))
    assert c == 200
    y, sr = sf.read(io.BytesIO(out))
    from mimicry.dsp import estimate_f0
    f0 = estimate_f0(y[sr:].astype("float32"), sr)
    assert f0 and abs(f0 - 220) / 220 < 0.1
    assert json.loads(h["X-Mimicry-Info"])["backend"] in ("pitch",)
