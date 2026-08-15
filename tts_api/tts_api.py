#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Standalone local Text-to-Speech API using Google Translate's undocumented
jQ1olc web RPC.

Confirmed path from the user's probe:
- POST .../batchexecute?rpcids=jQ1olc
- form field: f.req
- inner payload: [text, lang, None, None, [0]]
- response contains Base64-encoded MP3 audio

This is not an official Google API and may change without notice.
"""

from __future__ import annotations

import argparse
import base64
import json
import threading
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import requests

RPC_ID = "jQ1olc"
UPSTREAM = "https://translate.google.com.vn/_/TranslateWebserverUi/data/batchexecute"

DEFAULT_TIMEOUT = 20.0
DEFAULT_COOLDOWN = 60.0
MAX_TEXT_CHARS = 5000

# Only one voice shape is currently confirmed.
CONFIRMED_VOICES = {
    "default": {
        "id": "default",
        "label": "Google Translate default voice",
        "confirmed": True,
        "rpc_tail": [0],
    }
}

_SESSION = requests.Session()
_SESSION.headers.clear()
_UPSTREAM_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()

_BLOCKED_UNTIL = 0.0
_LAST_BLOCK_REASON: str | None = None


class TtsError(RuntimeError):
    pass


@dataclass
class UpstreamBlockedError(TtsError):
    upstream_status: int
    reason: str
    retry_after_seconds: int | None = None
    location: str | None = None

    def __str__(self):
        return self.reason


def build_f_req(text: str, lang: str, voice: str = "default") -> str:
    if voice not in CONFIRMED_VOICES:
        raise ValueError(
            f"Unsupported voice: {voice}. "
            f"Confirmed voices: {', '.join(CONFIRMED_VOICES)}"
        )

    inner = json.dumps(
        [text, lang, None, None, CONFIRMED_VOICES[voice]["rpc_tail"]],
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return json.dumps(
        [[[RPC_ID, inner, None, "generic"]]],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def parse_jq1olc_base64(raw: str) -> str:
    for line in raw.splitlines():
        s = line.strip()

        if not s or s == ")]}'" or s.isdigit() or not s.startswith("["):
            continue

        try:
            frame = json.loads(s)
        except json.JSONDecodeError:
            continue

        if not isinstance(frame, list):
            continue

        for item in frame:
            if (
                isinstance(item, list)
                and len(item) >= 3
                and item[0] == "wrb.fr"
                and item[1] == RPC_ID
                and isinstance(item[2], str)
            ):
                try:
                    inner = json.loads(item[2])
                except json.JSONDecodeError as exc:
                    raise TtsError(f"Invalid inner jQ1olc JSON: {exc}") from exc

                if isinstance(inner, list) and inner and isinstance(inner[0], str):
                    return inner[0]

    raise TtsError("jQ1olc audio payload not found")


def looks_like_mp3(data: bytes) -> bool:
    if data.startswith(b"ID3"):
        return True
    return len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0


def _parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None

    value = value.strip()

    if value.isdigit():
        return max(0, int(value))

    try:
        dt = parsedate_to_datetime(value)
        return max(0, int(dt.timestamp() - time.time()))
    except Exception:
        return None


def _set_block(seconds: float, reason: str):
    global _BLOCKED_UNTIL, _LAST_BLOCK_REASON

    with _STATE_LOCK:
        _BLOCKED_UNTIL = max(_BLOCKED_UNTIL, time.time() + max(0.0, seconds))
        _LAST_BLOCK_REASON = reason


def breaker_state():
    with _STATE_LOCK:
        remaining = max(0.0, _BLOCKED_UNTIL - time.time())

        return {
            "cooldown_active": remaining > 0,
            "retry_after_seconds": int(remaining + 0.999) if remaining > 0 else 0,
            "last_block_reason": _LAST_BLOCK_REASON,
        }


def _raise_if_cooldown():
    state = breaker_state()

    if state["cooldown_active"]:
        raise UpstreamBlockedError(
            upstream_status=0,
            reason="Local upstream cooldown is active",
            retry_after_seconds=state["retry_after_seconds"],
        )


def synthesize(
    text: str,
    lang: str = "vi",
    voice: str = "default",
    timeout: float = DEFAULT_TIMEOUT,
    cooldown_seconds: float = DEFAULT_COOLDOWN,
):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")

    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"text exceeds {MAX_TEXT_CHARS} characters")

    if not isinstance(lang, str) or not lang.strip():
        raise ValueError("lang must be a language code such as vi, en, ja")

    if voice not in CONFIRMED_VOICES:
        raise ValueError(
            f"voice must be one of: {', '.join(CONFIRMED_VOICES.keys())}"
        )

    _raise_if_cooldown()

    started = time.perf_counter()

    with _UPSTREAM_LOCK:
        _raise_if_cooldown()

        response = _SESSION.post(
            UPSTREAM,
            params={"rpcids": RPC_ID},
            data={"f.req": build_f_req(text, lang, voice)},
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
            },
            timeout=timeout,
            allow_redirects=False,
        )

    upstream_ms = (time.perf_counter() - started) * 1000.0
    retry_after = _parse_retry_after(response.headers.get("Retry-After"))

    if 300 <= response.status_code < 400:
        location = response.headers.get("Location")

        if location and "/sorry" in location:
            seconds = retry_after or int(cooldown_seconds)
            reason = "Google redirected jQ1olc to /sorry"
            _set_block(seconds, reason)

            raise UpstreamBlockedError(
                upstream_status=response.status_code,
                reason=reason,
                retry_after_seconds=seconds,
                location=location,
            )

        raise TtsError(f"Google returned redirect HTTP {response.status_code}")

    if response.status_code in (403, 429):
        seconds = retry_after or int(cooldown_seconds)
        reason = f"Google returned HTTP {response.status_code}"
        _set_block(seconds, reason)

        raise UpstreamBlockedError(
            upstream_status=response.status_code,
            reason=reason,
            retry_after_seconds=seconds,
        )

    if response.status_code != 200:
        raise TtsError(
            f"Google returned HTTP {response.status_code}: "
            f"{response.text[:200]!r}"
        )

    b64 = parse_jq1olc_base64(response.text)

    try:
        audio = base64.b64decode(b64, validate=False)
    except Exception as exc:
        raise TtsError(f"Base64 decode failed: {exc}") from exc

    if not audio:
        raise TtsError("Decoded audio is empty")

    if not looks_like_mp3(audio):
        raise TtsError("Decoded payload does not look like MP3")

    return {
        "audio": audio,
        "lang": lang,
        "voice": voice,
        "upstream_ms": round(upstream_ms, 2),
        "bytes": len(audio),
    }


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "GoogleTranslateTTSLocal/1.0"

    def log_message(self, fmt, *args):
        print(
            f"[{time.strftime('%H:%M:%S')}] "
            f"{self.client_address[0]} - {fmt % args}"
        )

    def send_json(self, status, obj, extra_headers=None):
        data = json.dumps(
            obj,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-API-Key",
        )
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)

        self.end_headers()
        self.wfile.write(data)

    def send_mp3(self, audio: bytes, meta: dict, download=False):
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-TTS-Language", meta["lang"])
        self.send_header("X-TTS-Voice", meta["voice"])
        self.send_header("X-Upstream-Ms", str(meta["upstream_ms"]))
        self.send_header("Access-Control-Allow-Origin", "*")

        if download:
            self.send_header(
                "Content-Disposition",
                'attachment; filename="tts.mp3"',
            )

        self.end_headers()
        self.wfile.write(audio)

    def check_api_key(self):
        api_key = getattr(self.server, "api_key", None)

        if not api_key:
            return True

        if self.headers.get("X-API-Key") == api_key:
            return True

        self.send_json(401, {"ok": False, "error": "invalid_api_key"})
        return False

    def do_OPTIONS(self):
        self.send_json(200, {"ok": True})

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self.send_json(
                200,
                {
                    "ok": True,
                    "service": "google-translate-tts-local-api",
                    "version": "1.0",
                    "rpc": RPC_ID,
                    "upstream_host": "translate.google.com.vn",
                    **breaker_state(),
                },
            )
            return

        if parsed.path == "/voices":
            self.send_json(
                200,
                {
                    "ok": True,
                    "voices": list(CONFIRMED_VOICES.values()),
                    "note": (
                        "Only the default jQ1olc voice is currently confirmed. "
                        "The API is structured to add more voices after capture/A-B verification."
                    ),
                },
            )
            return

        if parsed.path != "/tts":
            self.send_json(
                404,
                {
                    "ok": False,
                    "error": "not_found",
                    "endpoints": [
                        "GET /health",
                        "GET /voices",
                        "GET /tts?text=...&lang=vi",
                        "POST /tts",
                    ],
                },
            )
            return

        if not self.check_api_key():
            return

        q = parse_qs(parsed.query)
        text = q.get("text", [""])[0]
        lang = q.get("lang", ["vi"])[0]
        voice = q.get("voice", ["default"])[0]
        download = q.get("download", ["0"])[0] in ("1", "true", "yes")

        self.handle_tts(text, lang, voice, download)

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path != "/tts":
            self.send_json(404, {"ok": False, "error": "not_found"})
            return

        if not self.check_api_key():
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0

        if length <= 0 or length > 2_000_000:
            self.send_json(400, {"ok": False, "error": "invalid_body"})
            return

        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:
            self.send_json(
                400,
                {
                    "ok": False,
                    "error": "invalid_json",
                    "detail": str(exc),
                },
            )
            return

        if not isinstance(body, dict):
            self.send_json(
                400,
                {
                    "ok": False,
                    "error": "body_must_be_object",
                },
            )
            return

        text = body.get("text", "")
        lang = body.get("lang", "vi")
        voice = body.get("voice", "default")
        download = bool(body.get("download", False))

        self.handle_tts(text, lang, voice, download)

    def handle_tts(self, text, lang, voice, download):
        try:
            result = synthesize(
                text=text,
                lang=lang,
                voice=voice,
                timeout=self.server.upstream_timeout,
                cooldown_seconds=self.server.cooldown_seconds,
            )

            self.send_mp3(result["audio"], result, download=download)

        except ValueError as exc:
            self.send_json(
                400,
                {
                    "ok": False,
                    "error": "bad_request",
                    "detail": str(exc),
                },
            )

        except requests.Timeout:
            self.send_json(
                504,
                {
                    "ok": False,
                    "error": "upstream_timeout",
                },
            )

        except requests.RequestException as exc:
            self.send_json(
                502,
                {
                    "ok": False,
                    "error": "upstream_network_error",
                    "detail": str(exc),
                },
            )

        except UpstreamBlockedError as exc:
            retry_after = exc.retry_after_seconds or 1
            local_status = 429 if exc.upstream_status == 429 else 503

            self.send_json(
                local_status,
                {
                    "ok": False,
                    "error": "upstream_blocked",
                    "detail": exc.reason,
                    "upstream_status": exc.upstream_status,
                    "retry_after_seconds": retry_after,
                },
                extra_headers={"Retry-After": str(retry_after)},
            )

        except TtsError as exc:
            self.send_json(
                502,
                {
                    "ok": False,
                    "error": "tts_upstream_error",
                    "detail": str(exc),
                },
            )


def main():
    ap = argparse.ArgumentParser(
        description="Standalone local TTS API using Google Translate jQ1olc"
    )

    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    ap.add_argument("--cooldown", type=float, default=DEFAULT_COOLDOWN)
    ap.add_argument("--api-key", default=None)

    args = ap.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), ApiHandler)
    server.upstream_timeout = args.timeout
    server.cooldown_seconds = max(0.0, args.cooldown)
    server.api_key = args.api_key

    print("=" * 72)
    print("Google Translate Standalone TTS API V1")
    print(f"Listen : http://{args.host}:{args.port}")
    print(f"Health : http://{args.host}:{args.port}/health")
    print(f"Voices : http://{args.host}:{args.port}/voices")
    print("TTS    : POST /tts")
    print("RPC    : jQ1olc")
    print("Voice  : default (only confirmed voice)")
    print("Upstream concurrency: 1")
    print("Ctrl+C to stop")
    print("=" * 72)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        server.server_close()
        _SESSION.close()


if __name__ == "__main__":
    main()
