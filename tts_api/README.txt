GOOGLE TRANSLATE STANDALONE TTS API V1
=======================================

MUC TIEU
--------
API rieng chi lam mot viec:

  TEXT -> MP3

Khong kem phan dich.

RPC:
  jQ1olc

Upstream:
  https://translate.google.com.vn/_/TranslateWebserverUi/data/batchexecute?rpcids=jQ1olc


CAI DAT
-------
Windows CMD:

  py -m pip install -r requirements.txt


CHAY
----
  START_TTS_API.cmd

Mac dinh:
  http://127.0.0.1:8090


POST /tts
---------
Request:

  POST http://127.0.0.1:8090/tts
  Content-Type: application/json

Body:

  {
    "text": "Xin chào thế giới",
    "lang": "vi"
  }

Response thanh cong:
  Content-Type: audio/mpeg

Body:
  MP3 bytes truc tiep.


CURL
----
Windows CMD:

  curl -X POST "http://127.0.0.1:8090/tts" ^
    -H "Content-Type: application/json" ^
    -d "{\"text\":\"Xin chào thế giới\",\"lang\":\"vi\"}" ^
    --output voice.mp3


GET TEST NHANH
--------------
Mo tren browser:

  http://127.0.0.1:8090/tts?text=Xin%20chao&lang=vi&download=1


HEALTH
------
  http://127.0.0.1:8090/health


VOICES
------
  http://127.0.0.1:8090/voices

Hien tai chi co:
  default

Day la giong duy nhat da duoc xac nhan bang capture + probe.

Code da chuan bi truoc cau truc "voice" de sau nay them:
  voice-2
  male
  female
  ...

NHUNG khong gia lap cac voice chua duoc xac nhan.


PYTHON CLIENT
-------------
  py example_client.py

Se tao:
  example_voice.mp3


LAN
---
Chay:

  py tts_api.py --host 0.0.0.0 --port 8090 --api-key "YOUR_SECRET"

Client them header:

  X-API-Key: YOUR_SECRET


ANTI-ABUSE
----------
Khong retry lien tuc.
Khong doi IP/host.
302 /sorry, 403, 429 -> cooldown local.


LUU Y
-----
jQ1olc la web RPC khong chinh thuc cua Google Translate.
No co the thay doi ma khong thong bao.
