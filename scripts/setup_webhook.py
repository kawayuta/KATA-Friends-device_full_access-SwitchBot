"""
SwitchBot Webhook 登録・管理スクリプト

使い方:
  python3 scripts/setup_webhook.py setup <webhook_url>
  python3 scripts/setup_webhook.py query
  python3 scripts/setup_webhook.py delete
"""

import hashlib, hmac, base64, time, uuid, json, sys, os
import urllib.request
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["SWITCHBOT_TOKEN"]
SECRET = os.environ["SWITCHBOT_SECRET"]
API_BASE = "https://api.switch-bot.com/v1.1"


def make_headers():
    t = str(int(time.time() * 1000))
    nonce = str(uuid.uuid4())
    string_to_sign = f"{TOKEN}{t}{nonce}"
    sign = base64.b64encode(
        hmac.new(SECRET.encode(), string_to_sign.encode(), hashlib.sha256).digest()
    ).decode()
    return {
        "Authorization": TOKEN,
        "sign": sign,
        "t": t,
        "nonce": nonce,
        "Content-Type": "application/json; charset=utf8",
    }


def api_post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=make_headers(), method="POST")
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def setup_webhook(url):
    print(f"Webhook登録: {url}")
    api_post("/webhook/setupWebhook", {
        "action": "setupWebhook",
        "url": url,
        "deviceList": "ALL",
    })


def query_webhook():
    print("=== Webhook URL ===")
    api_post("/webhook/queryWebhook", {
        "action": "queryUrl",
    })
    print("\n=== Webhook 詳細 ===")
    api_post("/webhook/queryWebhook", {
        "action": "queryDetails",
    })


def delete_webhook():
    print("Webhook削除")
    api_post("/webhook/deleteWebhook", {
        "action": "deleteWebhook",
    })


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python3 scripts/setup_webhook.py [setup <url> | query | delete]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "setup" and len(sys.argv) >= 3:
        setup_webhook(sys.argv[2])
    elif cmd == "query":
        query_webhook()
    elif cmd == "delete":
        delete_webhook()
    else:
        print("使い方: python3 scripts/setup_webhook.py [setup <url> | query | delete]")
