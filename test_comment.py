#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import urllib.request
import uuid

event = {
    "eventId": "test-" + uuid.uuid4().hex[:10],
    "eventType": "comment",
    "user": {
        "id": "test_user",
        "uniqueId": "test_user",
        "displayName": "Người thử",
    },
    "payload": {
        "text": "Xin chào, đây là comment TikTok thử nghiệm bằng Google TTS API.",
        "normalizedText": "XIN CHÀO",
    },
}

req = urllib.request.Request(
    "http://127.0.0.1:9000/tiktok-event",
    data=json.dumps(event, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(req, timeout=10) as r:
    print(r.read().decode("utf-8"))
