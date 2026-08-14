GOOGLE TTS API -> TIKTOK SPEAKER V1
====================================

MUC TIEU
--------
Bien API TTS local jQ1olc thanh "loa TikTok" tuong tu loaTTS-:

TikTok LIVE
   |
tiktok_live_cmd_active_viewers_v9
   |
POST /tiktok-event
   |
Google API TikTok Speaker :9000
   |
queue comment FIFO
   |
local TTS API :8090
   |
MP3
   |
browser tren dien thoai/laptop
   |
loa / tai nghe / Bluetooth


CAC REPO THAM CHIEU
-------------------
TikTok middleware:
  https://github.com/banupham/tiktok_live_cmd_active_viewers_v9

LoaTTS tham chieu:
  https://github.com/banupham/loaTTS-


CAN CO TTS API TRUOC
--------------------
Dung goi:
  google_translate_tts_api_v1.zip

Chay:
  START_TTS_API.cmd

Kiem tra:
  http://127.0.0.1:8090/health


CAI SPEAKER
-----------
  INSTALL.cmd

Hoac START_SPEAKER.cmd se tu cai dependency neu thieu.


CHAY
----
Thu tu:

CMD 1:
  START_TTS_API.cmd

CMD 2:
  START_SPEAKER.cmd

Sau do browser PC:
  http://127.0.0.1:9000

Dien thoai cung Wi-Fi:
  http://IP_MAY_TINH:9000

Vi du:
  http://192.168.1.20:9000

Tren web:
  bam BẬT LOA TIKTOK


NOI VOI MIDDLEWARE
------------------
Tai repo:
  tiktok_live_cmd_active_viewers_v9

Chay:
  start_middleware_to_game.bat ten_tiktok

Vi du:
  start_middleware_to_game.bat ngocky.ne

Middleware mac dinh gui:
  http://127.0.0.1:9000/tiktok-event

Speaker /health tra contract:
  ok=true
  service=game-event-server
  instanceId
  instanceToken
  pid
  eventPath=/tiktok-event

Nen handshake cua middleware co the ket noi truc tiep.


EVENT DUOC DOC
--------------
Chi:
  eventType=comment

Text:
  payload.text

join/follow/like/gift:
  tra HTTP 2xx
  ignored=true

Middleware khong retry cac event nay.


CHIA TEXT
---------
API jQ1olc co the loi neu text dai.

Speaker mac dinh tach:
  80 ky tu / segment

Moi segment:
  POST http://127.0.0.1:8090/tts
  -> MP3

Browser phat tung segment theo dung thu tu.

Doi tren web:
  Max ky tu / segment

Khoang cho phep:
  30..150


QUEUE
-----
Mac dinh:
  queue max = 30
  comment qua 20 giay = bo

Doi truoc khi chay:

  set LOA_TTS_QUEUE_MAX=50
  set LOA_TTS_COMMENT_MAX_AGE=30
  START_SPEAKER.cmd


TTS API URL KHAC
----------------
Mac dinh:
  http://127.0.0.1:8090/tts

Doi:

  set LOA_TTS_API_URL=http://127.0.0.1:8090/tts
  set LOA_TTS_HEALTH_URL=http://127.0.0.1:8090/health
  START_SPEAKER.cmd


TEST KHONG CAN TIKTOK
---------------------
1. Chay TTS API
2. Chay speaker
3. Mo web :9000 va bam BẬT LOA TIKTOK
4. Chay:
   TEST_COMMENT.cmd

Neu dung, loa doc:
  Xin chào, đây là comment TikTok thử nghiệm bằng Google TTS API.


STATUS
------
  http://127.0.0.1:9000/status

Co:
  TTS API online/offline
  queue
  active speaker
  current comment
  so comment nhan/doc/loi
  so TTS request thanh cong/that bai


FIREWALL
--------
Neu dien thoai khong mo duoc web:

  ALLOW_FIREWALL.cmd

Chay bang:
  Run as administrator


CAU TRUC
--------
app.py
  webhook + queue + handshake + goi TTS API + WebSocket

web/index.html
  giao dien loa tren dien thoai/laptop

START_SPEAKER.cmd
  chay server :9000

INSTALL.cmd
  cai dependency

ALLOW_FIREWALL.cmd
  mo TCP 9000

TEST_COMMENT.cmd
test_comment.py
  gui comment TikTok gia lap

requirements.txt
README.txt


LUU Y
-----
Google jQ1olc la web RPC khong chinh thuc.
Backend TTS co the thay doi.

Speaker nay khong thay doi giao thuc middleware TikTok.
No chi dong vai tro "game-event-server" nhan webhook /tiktok-event.

Hien tai voice da xac nhan:
  default
