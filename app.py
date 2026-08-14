#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
WEB_FILE = BASE_DIR / "web" / "index.html"
SETTINGS_FILE = BASE_DIR / "settings.json"

HOST = os.getenv("LOA_API_HOST", "0.0.0.0")
PORT = int(os.getenv("LOA_API_PORT", "9000"))
EVENT_PATH = os.getenv("LOA_API_EVENT_PATH", "/tiktok-event").strip() or "/tiktok-event"

TTS_API_URL = os.getenv("LOA_TTS_API_URL", "http://127.0.0.1:8090/tts").strip()
TTS_HEALTH_URL = os.getenv("LOA_TTS_HEALTH_URL", "http://127.0.0.1:8090/health").strip()
TTS_TIMEOUT = max(5.0, float(os.getenv("LOA_TTS_TIMEOUT", "30")))

QUEUE_MAX = max(1, int(os.getenv("LOA_TTS_QUEUE_MAX", "30")))
COMMENT_MAX_AGE = max(0.0, float(os.getenv("LOA_TTS_COMMENT_MAX_AGE", "20")))
EVENT_ID_CACHE = max(100, int(os.getenv("LOA_TTS_EVENT_ID_CACHE", "10000")))

SERVER_VERSION = "3.0"
SERVER_INSTANCE_ID = uuid.uuid4().hex[:12]
SERVER_SESSION_TOKEN = os.getenv("GAME_EVENT_INSTANCE_TOKEN", "").strip()
SERVER_PID = os.getpid()


DEFAULT_ABBREVIATIONS = {
    "ko": "không",
    "k0": "không",
    "kh": "không",
    "hk": "không",
    "hok": "không",
    "hong": "không",
    "khum": "không",
    "dc": "được",
    "đc": "được",
    "mn": "mọi người",
    "mng": "mọi người",
    "mk": "mình",
    "mik": "mình",
    "cx": "cũng",
    "vs": "với",
    "j": "gì",
    "z": "vậy",
    "ib": "nhắn tin",
    "rep": "trả lời",
    "trl": "trả lời",
    "cmt": "bình luận",
    "acc": "tài khoản",
    "ae": "anh em",
    "fl": "theo dõi",
    "follow": "theo dõi",
    "tym": "thả tim",
    "thx": "cảm ơn",
    "tks": "cảm ơn",
    "thanks": "cảm ơn",
    "pls": "làm ơn",
    "yt": "YouTube",
    "ttok": "TikTok",
    "oki": "ô kê",
    "okie": "ô kê",
    "oke": "ô kê",
}

SYSTEM_COMMENT_PATTERNS = (
    re.compile(r"\bđã\s+chia\s+sẻ\s+(?:phiên\s+)?live\b", re.I),
    re.compile(r"\bđã\s+chia\s+se\s+(?:phiên\s+)?live\b", re.I),
    re.compile(r"\bshared\s+(?:the\s+)?live\b", re.I),
    re.compile(r"\bshared\s+(?:this\s+)?live\b", re.I),
)

LEADING_UI_NUMBER_RE = re.compile(r"^\s*(\d{1,3})\s+(?=\D)")


class SpeakerSettings(BaseModel):
    lang: str = "vi"
    voice: str = "default"
    read_username: bool = False
    chunk_chars: int = Field(default=80, ge=30, le=150)
    normalize_abbreviations: bool = True
    custom_replacements: dict[str, str] = Field(default_factory=dict)
    blocked_phrases: list[str] = Field(default_factory=list)


class CommentJob(BaseModel):
    id: str
    event_id: str
    created_at: float
    display_name: str
    unique_id: Optional[str] = None
    text: str
    speech_text: str
    segments: list[str]


settings_lock = threading.Lock()
settings = SpeakerSettings()

comment_queue: asyncio.Queue[CommentJob] = asyncio.Queue(maxsize=QUEUE_MAX)

speakers: dict[str, dict[str, Any]] = {}
active_speaker_id: Optional[str] = None
active_speaker_event = asyncio.Event()
state_lock = asyncio.Lock()

pending_completion: dict[str, asyncio.Future] = {}
worker_task: Optional[asyncio.Task] = None

current_job: Optional[CommentJob] = None
current_started_at: Optional[float] = None

seen_event_ids: set[str] = set()
seen_event_order: deque[str] = deque()
seen_event_lock = threading.Lock()

tts_session = requests.Session()

stats = {
    "webhook_requests": 0,
    "comments_received": 0,
    "comments_queued": 0,
    "comments_played": 0,
    "comments_failed": 0,
    "comments_dropped": 0,
    "comments_expired": 0,
    "comments_filtered_system": 0,
    "comments_filtered_custom": 0,
    "comments_abbreviation_normalized": 0,
    "comments_cleaned_ui_prefix": 0,
    "ignored_non_comment": 0,
    "duplicate_events": 0,
    "tts_requests": 0,
    "tts_success": 0,
    "tts_failed": 0,
    "last_tts_status": None,
    "last_tts_ms": None,
    "last_webhook_at": None,
    "last_comment_at": None,
    "last_client_ip": None,
    "last_event_type": None,
    "last_health_handshake_at": None,
}

tts_health_cache = {
    "ok": False,
    "checked_at": None,
    "detail": "chưa kiểm tra",
}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def sanitize_settings(value: SpeakerSettings) -> SpeakerSettings:
    lang = re.sub(r"[^A-Za-z0-9_-]", "", value.lang.strip())[:20] or "vi"
    voice = re.sub(r"[^A-Za-z0-9_.-]", "", value.voice.strip())[:50] or "default"

    replacements = {}
    for raw_key, raw_value in value.custom_replacements.items():
        key = re.sub(r"\s+", " ", str(raw_key or "")).strip()
        val = re.sub(r"\s+", " ", str(raw_value or "")).strip()
        if not key or not val:
            continue
        if len(key) > 60 or len(val) > 120:
            continue
        replacements[key] = val
        if len(replacements) >= 200:
            break

    blocked = []
    seen = set()
    for raw in value.blocked_phrases:
        phrase = re.sub(r"\s+", " ", str(raw or "")).strip()
        marker = phrase.casefold()
        if not phrase or marker in seen or len(phrase) > 160:
            continue
        seen.add(marker)
        blocked.append(phrase)
        if len(blocked) >= 200:
            break

    return value.model_copy(update={
        "lang": lang,
        "voice": voice,
        "custom_replacements": replacements,
        "blocked_phrases": blocked,
    })


def save_settings() -> None:
    SETTINGS_FILE.write_text(
        json.dumps(settings.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_settings() -> None:
    global settings

    if not SETTINGS_FILE.exists():
        save_settings()
        return

    try:
        obj = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        settings = sanitize_settings(SpeakerSettings.model_validate(obj))
    except Exception as exc:
        print(f"[SETTINGS] Lỗi settings.json, dùng mặc định: {exc}")
        settings = SpeakerSettings()


def register_event_id(event_id: str) -> bool:
    if not event_id:
        return True

    with seen_event_lock:
        if event_id in seen_event_ids:
            return False

        seen_event_ids.add(event_id)
        seen_event_order.append(event_id)

        while len(seen_event_order) > EVENT_ID_CACHE:
            seen_event_ids.discard(seen_event_order.popleft())

    return True


def normalize_comment_text(value: Any) -> tuple[str, bool]:
    text = str(value or "").replace("\u200b", " ").replace("\ufeff", " ")
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return "", False

    cleaned = LEADING_UI_NUMBER_RE.sub("", text, count=1).strip()
    return cleaned, cleaned != text


def is_system_comment(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return bool(value) and any(p.search(value) for p in SYSTEM_COMMENT_PATTERNS)


def custom_block_match(text: str, cfg: SpeakerSettings) -> Optional[str]:
    folded = text.casefold()
    for phrase in cfg.blocked_phrases:
        if phrase.casefold() in folded:
            return phrase
    return None


def replace_phrase(text: str, source: str, target: str) -> tuple[str, int]:
    pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.I)
    return pattern.subn(lambda _: target, text)


def normalize_abbreviations(text: str, cfg: SpeakerSettings) -> tuple[str, int]:
    if not cfg.normalize_abbreviations:
        return text, 0

    rules = dict(DEFAULT_ABBREVIATIONS)
    rules.update(cfg.custom_replacements)

    output = text
    total = 0

    for source in sorted(rules, key=len, reverse=True):
        output, count = replace_phrase(output, source, rules[source])
        total += count

    return re.sub(r"\s+", " ", output).strip(), total


def find_cut(text: str, limit: int) -> int:
    if len(text) <= limit:
        return len(text)

    window = text[:limit]
    min_good = max(10, int(limit * 0.45))

    for chars in (".!?…", ",;:", " "):
        positions = [i + 1 for i, ch in enumerate(window) if ch in chars]
        good = [p for p in positions if p >= min_good]
        if good:
            return good[-1]

    return limit


def split_text(text: str, max_chars: int) -> list[str]:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []

    out = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            out.append(remaining)
            break

        cut = find_cut(remaining, max_chars)
        left = remaining[:cut].strip()
        remaining = remaining[cut:].strip()

        if not left:
            left = remaining[:max_chars]
            remaining = remaining[max_chars:].strip()

        out.append(left)

    return [x for x in out if x]


def make_speech_text(display_name: str, text: str, cfg: SpeakerSettings) -> str:
    if cfg.read_username and display_name:
        return f"{display_name} bình luận: {text}"
    return text


def check_tts_health_sync() -> dict:
    started = time.perf_counter()
    try:
        r = tts_session.get(TTS_HEALTH_URL, timeout=min(5.0, TTS_TIMEOUT))
        elapsed = (time.perf_counter() - started) * 1000
        if 200 <= r.status_code < 300:
            try:
                body = r.json()
            except Exception:
                body = {}
            return {
                "ok": bool(body.get("ok", True)),
                "status": r.status_code,
                "ms": round(elapsed, 2),
                "detail": body,
            }
        return {
            "ok": False,
            "status": r.status_code,
            "ms": round(elapsed, 2),
            "detail": r.text[:300],
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "ms": None,
            "detail": str(exc),
        }


async def refresh_tts_health() -> dict:
    result = await asyncio.to_thread(check_tts_health_sync)
    tts_health_cache.update({
        "ok": bool(result.get("ok")),
        "checked_at": now_iso(),
        "detail": result,
    })
    return result


def fetch_tts_audio_sync(text: str, lang: str, voice: str) -> tuple[bytes, int, float]:
    started = time.perf_counter()

    r = tts_session.post(
        TTS_API_URL,
        json={
            "text": text,
            "lang": lang,
            "voice": voice,
        },
        headers={"Accept": "audio/mpeg"},
        timeout=TTS_TIMEOUT,
        allow_redirects=False,
    )

    elapsed = (time.perf_counter() - started) * 1000

    if r.status_code != 200:
        detail = r.text[:1000]
        raise RuntimeError(f"TTS API HTTP {r.status_code}: {detail}")

    ctype = (r.headers.get("Content-Type") or "").lower()
    if "audio/" not in ctype:
        raise RuntimeError(
            f"TTS API trả Content-Type={ctype!r}, không phải audio. "
            f"Body={r.text[:500]!r}"
        )

    if not r.content:
        raise RuntimeError("TTS API trả audio rỗng")

    return r.content, r.status_code, elapsed


async def fetch_tts_audio(text: str, lang: str, voice: str) -> bytes:
    stats["tts_requests"] += 1
    try:
        audio, status, elapsed = await asyncio.to_thread(
            fetch_tts_audio_sync, text, lang, voice
        )
        stats["tts_success"] += 1
        stats["last_tts_status"] = status
        stats["last_tts_ms"] = round(elapsed, 2)
        tts_health_cache["ok"] = True
        tts_health_cache["checked_at"] = now_iso()
        return audio

    except Exception as exc:
        stats["tts_failed"] += 1
        stats["last_tts_status"] = "error"
        stats["last_tts_ms"] = None
        tts_health_cache["ok"] = False
        tts_health_cache["checked_at"] = now_iso()
        tts_health_cache["detail"] = str(exc)
        raise


async def set_active_speaker(device_id: Optional[str]) -> None:
    global active_speaker_id

    async with state_lock:
        old_id = active_speaker_id
        active_speaker_id = device_id if device_id in speakers else None

        if active_speaker_id:
            active_speaker_event.set()
        else:
            active_speaker_event.clear()

        if old_id and old_id != active_speaker_id and old_id in speakers:
            try:
                await speakers[old_id]["ws"].send_json({
                    "type": "stop",
                    "reason": "speaker_taken_over",
                })
            except Exception:
                pass

        if current_job and old_id and old_id != active_speaker_id:
            future = pending_completion.get(current_job.id)
            if future and not future.done():
                future.set_result(("retry", "active speaker changed"))


async def wait_for_active_speaker() -> tuple[str, WebSocket]:
    while True:
        await active_speaker_event.wait()

        async with state_lock:
            if active_speaker_id and active_speaker_id in speakers:
                return active_speaker_id, speakers[active_speaker_id]["ws"]

            active_speaker_event.clear()


async def queue_comment(job: CommentJob) -> None:
    if comment_queue.full():
        try:
            dropped = comment_queue.get_nowait()
            comment_queue.task_done()
            stats["comments_dropped"] += 1
            print(
                f"[QUEUE] Bỏ comment cũ vì queue đầy: "
                f"{dropped.display_name}: {dropped.text[:80]}"
            )
        except asyncio.QueueEmpty:
            pass

    await comment_queue.put(job)
    stats["comments_queued"] += 1


async def speaker_worker() -> None:
    global current_job, current_started_at

    while True:
        await active_speaker_event.wait()
        job = await comment_queue.get()

        try:
            age = time.time() - job.created_at

            if COMMENT_MAX_AGE > 0 and age > COMMENT_MAX_AGE:
                stats["comments_expired"] += 1
                print(f"[QUEUE] Bỏ comment quá cũ ({age:.1f}s): {job.text[:80]}")
                continue

            while True:
                device_id, ws = await wait_for_active_speaker()
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                pending_completion[job.id] = future

                current_job = job
                current_started_at = time.time()

                try:
                    await ws.send_json({
                        "type": "comment",
                        "job": {
                            "id": job.id,
                            "event_id": job.event_id,
                            "display_name": job.display_name,
                            "unique_id": job.unique_id,
                            "text": job.text,
                            "segment_count": len(job.segments),
                        },
                    })
                except Exception as exc:
                    pending_completion.pop(job.id, None)
                    current_job = None
                    current_started_at = None
                    await set_active_speaker(None)
                    print(f"[LOA] Không gửi được job tới {device_id}: {exc}")
                    continue

                try:
                    result, detail = await asyncio.wait_for(
                        future,
                        timeout=max(45.0, min(180.0, len(job.speech_text) * 2.0)),
                    )
                except asyncio.TimeoutError:
                    result, detail = "failed", "speaker timeout"
                finally:
                    pending_completion.pop(job.id, None)

                if result == "retry":
                    current_job = None
                    current_started_at = None
                    print(f"[LOA] Retry job {job.id}: {detail}")
                    continue

                if result == "completed":
                    stats["comments_played"] += 1
                    print(f"[LOA] Đọc xong: {job.display_name}: {job.text[:100]}")
                else:
                    stats["comments_failed"] += 1
                    print(f"[LOA] Đọc lỗi: {job.display_name}: {detail}")

                current_job = None
                current_started_at = None
                break

        finally:
            comment_queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker_task

    load_settings()

    print("=" * 72)
    print("GOOGLE TTS API -> TIKTOK SPEAKER")
    print(f"Web/health : http://127.0.0.1:{PORT}")
    print(f"Webhook    : http://127.0.0.1:{PORT}{EVENT_PATH}")
    print(f"TTS API    : {TTS_API_URL}")
    print(f"Instance   : {SERVER_INSTANCE_ID}")
    print(f"PID        : {SERVER_PID}")
    print("=" * 72)

    health = await refresh_tts_health()
    if health.get("ok"):
        print(f"[TTS API] KẾT NỐI OK ({health.get('ms')} ms)")
    else:
        print(f"[TTS API] CHƯA KẾT NỐI: {health.get('detail')}")
        print("[TTS API] Hãy chạy START_TTS_API.cmd của google_translate_tts_api_v1.")

    worker_task = asyncio.create_task(speaker_worker())

    try:
        yield
    finally:
        if worker_task:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

        tts_session.close()


app = FastAPI(
    title="Google TTS TikTok Comment Speaker",
    version=SERVER_VERSION,
    lifespan=lifespan,
)


@app.get("/", response_class=HTMLResponse)
def index():
    if not WEB_FILE.exists():
        raise HTTPException(status_code=500, detail="Thiếu web/index.html")

    return HTMLResponse(
        WEB_FILE.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health")
async def health(request: Request):
    is_handshake = request.headers.get("X-TikTok-Middleware-Handshake") == "1"
    client_ip = request.client.host if request.client else "unknown"

    if is_handshake:
        stats["last_health_handshake_at"] = now_iso()
        stats["last_client_ip"] = client_ip
        print(f"[HANDSHAKE] TikTok middleware -> speaker OK từ {client_ip}")

    return {
        "ok": True,
        "service": "game-event-server",
        "version": SERVER_VERSION,
        "instanceId": SERVER_INSTANCE_ID,
        "instanceToken": SERVER_SESSION_TOKEN,
        "pid": SERVER_PID,
        "eventPath": EVENT_PATH,
        "mode": "google-api-comment-tts-only",
        "ttsApiUrl": TTS_API_URL,
        "ttsApiOk": bool(tts_health_cache.get("ok")),
        "queueSize": comment_queue.qsize(),
        "queueCapacity": QUEUE_MAX,
        "activeSpeakerId": active_speaker_id,
    }


@app.get("/status")
async def status():
    active = speakers.get(active_speaker_id) if active_speaker_id else None

    return {
        "ok": True,
        "mode": "google-api-comment-tts-only",
        "tts_api_url": TTS_API_URL,
        "tts_api": tts_health_cache,
        "queue_size": comment_queue.qsize(),
        "queue_capacity": QUEUE_MAX,
        "comment_max_age_seconds": COMMENT_MAX_AGE,
        "connected_speakers": len(speakers),
        "active_speaker_id": active_speaker_id,
        "active_speaker_name": active.get("name") if active else None,
        "current_comment": (
            {
                "display_name": current_job.display_name,
                "text": current_job.text,
                "segments": len(current_job.segments),
                "started_at": current_started_at,
            }
            if current_job
            else None
        ),
        "stats": stats,
    }


@app.get("/api/voices")
async def voices():
    return [
        {
            "id": "default",
            "label": "Google Translate mặc định",
            "confirmed": True,
        }
    ]


@app.get("/api/settings")
async def get_settings():
    with settings_lock:
        payload = settings.model_dump()

    payload["default_abbreviations"] = DEFAULT_ABBREVIATIONS
    return payload


@app.post("/api/settings")
async def update_settings(req: SpeakerSettings):
    global settings

    req = sanitize_settings(req)

    with settings_lock:
        settings = req
        save_settings()
        return {
            "ok": True,
            "settings": settings.model_dump(),
        }


@app.post("/api/check-tts")
async def check_tts_api():
    result = await refresh_tts_health()
    return {
        "ok": bool(result.get("ok")),
        "result": result,
    }


@app.post(EVENT_PATH)
async def tiktok_event(request: Request):
    stats["webhook_requests"] += 1
    stats["last_webhook_at"] = now_iso()
    stats["last_client_ip"] = request.client.host if request.client else "unknown"

    try:
        event = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"JSON không hợp lệ: {exc}") from exc

    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Event phải là JSON object")

    event_type = str(event.get("eventType") or "").strip().lower()
    event_id = str(event.get("eventId") or "").strip()

    stats["last_event_type"] = event_type or None

    if event_id and not register_event_id(event_id):
        stats["duplicate_events"] += 1
        return {
            "ok": True,
            "duplicate": True,
            "eventId": event_id,
        }

    if event_type != "comment":
        stats["ignored_non_comment"] += 1
        return {
            "ok": True,
            "ignored": True,
            "reason": "comment_only",
            "eventType": event_type or None,
        }

    user = event.get("user") or {}
    payload = event.get("payload") or {}

    text, removed_ui_number = normalize_comment_text(payload.get("text"))

    if not text:
        return {
            "ok": True,
            "ignored": True,
            "reason": "empty_comment",
        }

    if is_system_comment(text):
        stats["comments_filtered_system"] += 1
        print(f"[FILTER] Bỏ dòng hệ thống: {text}")
        return {
            "ok": True,
            "ignored": True,
            "reason": "system_share_message",
            "eventId": event_id or None,
        }

    with settings_lock:
        cfg = settings.model_copy(deep=True)

    blocked_by = custom_block_match(text, cfg)

    if blocked_by:
        stats["comments_filtered_custom"] += 1
        print(f"[FILTER] Bỏ comment vì cụm '{blocked_by}': {text}")
        return {
            "ok": True,
            "ignored": True,
            "reason": "custom_blocked_phrase",
            "matched": blocked_by,
            "eventId": event_id or None,
        }

    normalized_text, replacement_count = normalize_abbreviations(text, cfg)

    if replacement_count:
        stats["comments_abbreviation_normalized"] += 1
        print(
            f"[TEXT] Chuẩn hóa {replacement_count} viết tắt: "
            f"{text} -> {normalized_text}"
        )

    text = normalized_text

    if removed_ui_number:
        stats["comments_cleaned_ui_prefix"] += 1

    display_name = str(
        user.get("displayName")
        or user.get("uniqueId")
        or user.get("id")
        or "Viewer"
    ).strip()

    unique_raw = user.get("uniqueId")

    speech_text = make_speech_text(display_name, text, cfg)
    segments = split_text(speech_text, cfg.chunk_chars)

    if not segments:
        return {
            "ok": True,
            "ignored": True,
            "reason": "empty_after_normalize",
        }

    job = CommentJob(
        id=uuid.uuid4().hex[:12],
        event_id=event_id,
        created_at=time.time(),
        display_name=display_name,
        unique_id=str(unique_raw).strip() if unique_raw else None,
        text=text,
        speech_text=speech_text,
        segments=segments,
    )

    stats["comments_received"] += 1
    stats["last_comment_at"] = now_iso()

    await queue_comment(job)

    print(
        f"[COMMENT] {display_name}: {text} "
        f"| segments={len(segments)}"
    )

    return {
        "ok": True,
        "accepted": True,
        "commentOnly": True,
        "eventId": event_id or None,
        "jobId": job.id,
        "queueSize": comment_queue.qsize(),
        "segmentCount": len(segments),
        "instanceId": SERVER_INSTANCE_ID,
        "pid": SERVER_PID,
    }


@app.get("/audio/{job_id}/{segment_index}")
async def audio_segment(job_id: str, segment_index: int, device_id: str):
    if not current_job or current_job.id != job_id:
        raise HTTPException(status_code=404, detail="Job không còn là comment hiện tại")

    if not active_speaker_id or device_id != active_speaker_id:
        raise HTTPException(status_code=403, detail="Thiết bị này không phải loa chính")

    if segment_index < 0 or segment_index >= len(current_job.segments):
        raise HTTPException(status_code=404, detail="Segment không tồn tại")

    with settings_lock:
        cfg = settings.model_copy(deep=True)

    segment_text = current_job.segments[segment_index]

    try:
        audio = await fetch_tts_audio(segment_text, cfg.lang, cfg.voice)
    except Exception as exc:
        print(
            f"[TTS API] Lỗi job={job_id} segment={segment_index}: {exc}"
        )

        text = str(exc)
        if "HTTP 504" in text:
            raise HTTPException(status_code=504, detail=text) from exc
        if "HTTP 429" in text:
            raise HTTPException(status_code=429, detail=text) from exc
        if "HTTP 503" in text:
            raise HTTPException(status_code=503, detail=text) from exc
        raise HTTPException(status_code=502, detail=text) from exc

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store",
            "X-TTS-Segment": str(segment_index),
            "X-TTS-Segments": str(len(current_job.segments)),
            "X-TTS-Language": cfg.lang,
            "X-TTS-Voice": cfg.voice,
        },
    )


@app.post("/clear")
async def clear_queue():
    cleared = 0

    while True:
        try:
            comment_queue.get_nowait()
            comment_queue.task_done()
            cleared += 1
        except asyncio.QueueEmpty:
            break

    return {
        "ok": True,
        "cleared": cleared,
    }


@app.post("/stop")
async def stop_current():
    if not current_job:
        return {
            "ok": True,
            "stopped": False,
        }

    if active_speaker_id and active_speaker_id in speakers:
        try:
            await speakers[active_speaker_id]["ws"].send_json({
                "type": "stop",
                "reason": "user_stop",
            })
        except Exception:
            pass

    future = pending_completion.get(current_job.id)

    if future and not future.done():
        future.set_result(("failed", "stopped by user"))

    return {
        "ok": True,
        "stopped": True,
        "job_id": current_job.id,
    }


@app.websocket("/ws/speaker")
async def speaker_socket(websocket: WebSocket):
    device_id = (
        websocket.query_params.get("device_id")
        or uuid.uuid4().hex[:10]
    ).strip()[:64]

    name = (
        websocket.query_params.get("name")
        or "Loa TikTok"
    ).strip()[:80]

    await websocket.accept()

    async with state_lock:
        speakers[device_id] = {
            "ws": websocket,
            "name": name,
            "connected_at": time.time(),
        }

    await websocket.send_json({
        "type": "hello",
        "device_id": device_id,
        "active": active_speaker_id == device_id,
        "message": "Đã kết nối. Bấm BẬT LOA TIKTOK để nhận comment.",
    })

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = str(message.get("type") or "")

            if msg_type == "claim":
                await set_active_speaker(device_id)
                await websocket.send_json({
                    "type": "claimed",
                    "device_id": device_id,
                })
                print(f"[LOA] Loa chính: {name} ({device_id})")

            elif msg_type == "release":
                if active_speaker_id == device_id:
                    await set_active_speaker(None)

                await websocket.send_json({
                    "type": "released",
                    "device_id": device_id,
                })

            elif msg_type == "started":
                print(
                    f"[LOA] Bắt đầu đọc "
                    f"{str(message.get('job_id') or '')} trên {name}"
                )

            elif msg_type in {"completed", "failed"}:
                job_id = str(message.get("job_id") or "")
                future = pending_completion.get(job_id)

                if future and not future.done():
                    if msg_type == "completed":
                        future.set_result(("completed", None))
                    else:
                        future.set_result((
                            "failed",
                            str(message.get("error") or "speaker failed"),
                        ))

            elif msg_type == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "time": time.time(),
                })

    except WebSocketDisconnect:
        pass

    except Exception as exc:
        print(f"[LOA] WebSocket {device_id} error: {exc}")

    finally:
        was_active = active_speaker_id == device_id

        async with state_lock:
            speakers.pop(device_id, None)

        if was_active:
            await set_active_speaker(None)

            if current_job:
                future = pending_completion.get(current_job.id)
                if future and not future.done():
                    future.set_result(("retry", "speaker disconnected"))

        print(f"[LOA] Mất kết nối: {name} ({device_id})")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
    )
