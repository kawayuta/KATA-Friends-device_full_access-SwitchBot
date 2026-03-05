"""
iPhoneアプリ → Kata Friends ローカルAPI の通信をキャプチャし、
authヘッダーの生成ロジックを解析する。

起動方法:
  mitmweb -s proxy/capture_auth.py -p 8888 --set connection_strategy=lazy

iPhone側設定:
  Wi-Fi → プロキシ → 手動 → サーバー: MacのIP, ポート: 8888
"""

import hashlib
import json
import logging
from datetime import datetime

from mitmproxy import http

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("capture_auth")

LOG_FILE = "logs/auth_capture.jsonl"
captures = []


class CaptureAuth:
    def request(self, flow: http.HTTPFlow):
        host = flow.request.host
        port = flow.request.port

        # Kata Friends宛の通信のみ対象
        if "192.168.11" not in host:
            return

        method = flow.request.method
        path = flow.request.path
        auth = flow.request.headers.get("auth", "")
        body_raw = flow.request.get_text() or ""
        body_md5 = hashlib.md5(body_raw.encode()).hexdigest()

        logger.info(f"\n{'='*60}")
        logger.info(f"[REQ] {method} http://{host}:{port}{path}")
        logger.info(f"  auth header : {auth}")
        logger.info(f"  body MD5    : {body_md5}")
        logger.info(f"  MD5 match   : {auth == body_md5}")
        logger.info(f"  body length : {len(body_raw)}")
        logger.info(f"  body raw    : {body_raw[:500]}")

        # 全ヘッダーを表示
        logger.info(f"  headers:")
        for k, v in flow.request.headers.items():
            logger.info(f"    {k}: {v}")

        # ログ保存
        entry = {
            "timestamp": datetime.now().isoformat(),
            "method": method,
            "host": host,
            "port": port,
            "path": path,
            "auth": auth,
            "body_raw": body_raw,
            "body_md5": body_md5,
            "md5_match": auth == body_md5,
            "headers": dict(flow.request.headers),
        }
        captures.append(entry)

        import os
        os.makedirs("logs", exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def response(self, flow: http.HTTPFlow):
        host = flow.request.host
        if "192.168.11" not in host:
            return

        status = flow.response.status_code
        body = flow.response.get_text() or ""
        logger.info(f"[RES] {status} → {body[:500]}")


addons = [CaptureAuth()]
