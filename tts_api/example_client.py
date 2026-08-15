#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import urllib.request

URL = "http://127.0.0.1:8090/tts"

payload = {
    "text": "Xin chào thế giới",
    "lang": "vi",
    "voice": "default",
}

req = urllib.request.Request(
    URL,
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(req, timeout=30) as r:
    audio = r.read()

with open("example_voice.mp3", "wb") as f:
    f.write(audio)

print("Created example_voice.mp3:", len(audio), "bytes")
