"""
自宅API - Kata FriendsのBLEイベントを受け取ってスマートホーム制御

起動方法:
  python3 -m uvicorn home_api.main:app --host 0.0.0.0 --port 9000 --reload
"""

import json
import os
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

load_dotenv()

app = FastAPI(title="Kata Friends Home API")

LOG_FILE = "logs/kata_events.jsonl"


# ========== イベントハンドラ ==========

async def handle_interaction_start(data: dict):
    """Kata Friendsへの呼びかけ検知"""
    print(f"  → 呼びかけ検知!")
    # TODO: 例えば部屋の照明を明るくする等


async def handle_interaction_end(data: dict):
    """Kata Friendsのアクション完了"""
    print(f"  → アクション完了")


async def handle_action(data: dict):
    """Kata Friendsがアクション実行（ダンス・写真等）"""
    print(f"  → アクション実行 (カウンタ: {data.get('action_counter')})")


HANDLERS = {
    "interaction_start": handle_interaction_start,
    "interaction_end": handle_interaction_end,
    "action": handle_action,
}


# ========== エンドポイント ==========

@app.post("/events")
async def receive_event(request: Request):
    payload = await request.json()
    event_type = payload.get("type", "unknown")
    data = payload.get("data", {})

    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"\n[{timestamp}] イベント受信: {event_type}")

    # ログ保存
    os.makedirs("logs", exist_ok=True)
    with open(LOG_FILE, "a") as f:
        log_entry = {"received_at": datetime.now().isoformat(), **payload}
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    handler = HANDLERS.get(event_type)
    if handler:
        await handler(data)
    else:
        print(f"  未分類: {json.dumps(payload, ensure_ascii=False)}")

    return JSONResponse({"status": "ok"})


@app.get("/health")
async def health():
    return {"status": "running"}
