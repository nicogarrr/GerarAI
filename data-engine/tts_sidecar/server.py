"""Sidecar TTS (Piper, voz local es_ES). Una sintesis a la vez, cache en /w/cache."""
import json
import os
import queue
import re
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import lameenc
from piper import PiperVoice

CACHE = "/w/cache"
os.makedirs(CACHE, exist_ok=True)
VOICE = PiperVoice.load("/w/es_ES-davefx-medium.onnx")
RATE = VOICE.config.sample_rate
JOBS: "queue.Queue[tuple[str, str]]" = queue.Queue()
STATE: dict[str, str] = {}
KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
MAX_CHARS = 60000
TTL_SECONDS = 24 * 3600  # un mp3 con mas de 24 h se descarta y se regenera


def _path(key: str) -> str:
    return os.path.join(CACHE, key + ".mp3")


def _fresh(key: str) -> bool:
    """True si hay mp3 en cache y no ha caducado (TTL); si caduco, lo borra."""
    path = _path(key)
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return False
    if age > TTL_SECONDS:
        try:
            os.remove(path)
        except OSError:
            pass
        STATE.pop(key, None)
        return False
    return True


def _generated_at(key: str) -> str:
    return datetime.fromtimestamp(os.path.getmtime(_path(key)), UTC).isoformat()


def _synth(key: str, text: str) -> None:
    enc = lameenc.Encoder()
    enc.set_bit_rate(48)
    enc.set_in_sample_rate(RATE)
    enc.set_channels(1)
    enc.set_quality(5)
    out = bytearray()
    for paragraph in [p.strip() for p in text.split("\n") if p.strip()]:
        for chunk in VOICE.synthesize(paragraph):
            out += enc.encode(chunk.audio_int16_bytes)
    out += enc.flush()
    tmp = _path(key) + ".part"
    with open(tmp, "wb") as fh:
        fh.write(bytes(out))
    os.replace(tmp, _path(key))


def _worker() -> None:
    while True:
        key, text = JOBS.get()
        try:
            os.nice(10) if hasattr(os, "nice") else None
        except OSError:
            pass
        try:
            STATE[key] = "pending"
            _synth(key, text)
            STATE[key] = "ready"
        except Exception as exc:  # noqa: BLE001
            STATE[key] = "error:" + type(exc).__name__


threading.Thread(target=_worker, daemon=True).start()


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parts = self.path.strip("/").split("/")
        if parts[0] == "health":
            return self._send(200, b'{"ok":true}')
        if len(parts) == 2 and parts[0] == "status" and KEY_RE.match(parts[1]):
            key = parts[1]
            if _fresh(key):
                body = {"state": "ready", "generated_at": _generated_at(key)}
            else:
                body = {"state": STATE.get(key, "missing")}
            return self._send(200, json.dumps(body).encode())
        if len(parts) == 2 and parts[0] == "audio" and KEY_RE.match(parts[1]) and _fresh(parts[1]):
            with open(_path(parts[1]), "rb") as fh:
                return self._send(200, fh.read(), "audio/mpeg")
        self._send(404, b'{"error":"not found"}')

    def do_POST(self) -> None:  # noqa: N802
        parts = self.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "tts" and KEY_RE.match(parts[1]):
            key = parts[1]
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_CHARS * 4:
                return self._send(400, b'{"error":"bad length"}')
            text = json.loads(self.rfile.read(length)).get("text", "")[:MAX_CHARS]
            if _fresh(key):
                return self._send(200, b'{"state":"ready"}')
            if STATE.get(key) != "pending":
                STATE[key] = "pending"
                JOBS.put((key, text))
            return self._send(202, b'{"state":"pending"}')
        self._send(404, b'{"error":"not found"}')

    def log_message(self, *args) -> None:  # noqa: D401
        return


ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
