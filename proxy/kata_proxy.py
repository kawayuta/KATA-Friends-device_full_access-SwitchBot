"""
Kata Friends 透過プロキシ
mitmproxy スクリプトとして動作

起動方法:
  mitmweb -s proxy/kata_proxy.py --mode transparent -p 8080 --ssl-insecure
"""

import json
import logging
import os
import subprocess
from datetime import datetime

import httpx
from mitmproxy import http

# 設定
from dotenv import load_dotenv
load_dotenv()

HOME_API_URL = "http://localhost:9000/events"
KATA_MAC = os.environ["KATA_MAC"]
LOG_FILE = "logs/kata_events.jsonl"


def resolve_ip_from_mac(mac: str) -> str | None:
    """ARPテーブルからMACアドレスに対応するIPを取得"""
    try:
        result = subprocess.run(["arp", "-a"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if mac.lower() in line.lower():
                # "? (x.x.x.x) at xx:xx:xx:xx:xx:xx ..." からIP抽出
                start = line.find("(")
                end = line.find(")")
                if start != -1 and end != -1:
                    return line[start + 1:end]
    except Exception:
        pass
    return None


KATA_IP = resolve_ip_from_mac(KATA_MAC)
if KATA_IP:
    logging.info(f"Kata Friends detected at {KATA_IP}")
else:
    logging.warning(f"Kata Friends ({KATA_MAC}) not found in ARP table")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("kata_proxy")


def is_kata_request(flow: http.HTTPFlow) -> bool:
    """Kata Friendsからのリクエストか判定"""
    return flow.client_conn.peername[0] == KATA_IP


def classify_event(host: str, path: str, body: dict) -> dict | None:
    """
    リクエスト内容からイベントを分類する
    Phase 1のキャプチャ結果に基づいてここを充実させる
    """
    # 音声認識イベント（パスは調査後に更新）
    if "voice" in path or "speech" in path or "asr" in path:
        return {
            "type": "voice",
            "data": body,
        }

    # 顔認識・カメライベント
    if "face" in path or "vision" in path or "camera" in path:
        return {
            "type": "camera",
            "data": body,
        }

    # センサー・移動イベント
    if "sensor" in path or "motion" in path or "tof" in path:
        return {
            "type": "sensor",
            "data": body,
        }

    # 汎用イベント（全送信をキャッチ）
    return {
        "type": "unknown",
        "host": host,
        "path": path,
        "data": body,
    }


def forward_to_home_api(event: dict):
    """自宅APIにWebhookとして転送"""
    payload = {
        "timestamp": datetime.now().isoformat(),
        "source": "kata_friends",
        **event,
    }

    # ログ保存
    os.makedirs("logs", exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    # 自宅APIへ送信
    try:
        response = httpx.post(HOME_API_URL, json=payload, timeout=2.0)
        logger.info(f"→ 自宅API転送: {event['type']} → {response.status_code}")
    except Exception as e:
        logger.warning(f"自宅API転送失敗: {e}")


class KataProxy:
    def request(self, flow: http.HTTPFlow):
        if not is_kata_request(flow):
            return

        host = flow.request.host
        path = flow.request.path
        logger.info(f"[REQ] {flow.request.method} {host}{path}")

        # ボディをパース
        body = {}
        content_type = flow.request.headers.get("content-type", "")
        if "json" in content_type:
            try:
                body = json.loads(flow.request.get_text())
            except Exception:
                body = {"raw": flow.request.get_text()[:500]}

        # イベント分類 & 転送
        event = classify_event(host, path, body)
        if event:
            forward_to_home_api(event)

    def response(self, flow: http.HTTPFlow):
        if not is_kata_request(flow):
            return

        host = flow.request.host
        path = flow.request.path
        status = flow.response.status_code
        logger.info(f"[RES] {status} {host}{path}")


addons = [KataProxy()]
