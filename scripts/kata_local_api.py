"""
Kata Friends ローカルAPI クライアント

使い方:
  python3 scripts/kata_local_api.py discover     # functionID探索
  python3 scripts/kata_local_api.py photos        # 写真一覧
  python3 scripts/kata_local_api.py faces         # 顔認識データ
  python3 scripts/kata_local_api.py storage       # ストレージ情報
  python3 scripts/kata_local_api.py raw <funcID>  # 任意のfunctionID
"""

import hashlib
import json
import os
import sys
import time
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

KATA_IP = os.environ["KATA_IP"]
KATA_PORT = 22090
KATA_DEVICE_ID = os.environ["KATA_DEVICE_ID"]
BASE_URL = f"http://{KATA_IP}:{KATA_PORT}"

# キャプチャから判明したfunctionID
FUNC_PHOTOS = 9217
FUNC_STORAGE = 9206
FUNC_FACES = 9225


def make_auth(body_str: str) -> str:
    """authヘッダーを生成（推定: bodyのMD5）"""
    return hashlib.md5(body_str.encode()).hexdigest()


def make_request(function_id: int, params: dict = None) -> dict:
    """Kata FriendsローカルAPIにリクエスト送信"""
    if params is None:
        params = {}

    payload = {
        "version": "1",
        "code": 3,
        "deviceID": KATA_DEVICE_ID,
        "payload": {
            "functionID": function_id,
            "requestID": str(uuid.uuid4()).upper(),
            "timestamp": int(time.time() * 1000),
            "params": params,
        }
    }

    body_str = json.dumps(payload)

    # auth生成（複数パターンを試す）
    auth_candidates = [
        hashlib.md5(body_str.encode()).hexdigest(),
        hashlib.md5(f"{body_str}{KATA_DEVICE_ID}".encode()).hexdigest(),
        hashlib.md5(body_str.encode('utf-8')).hexdigest(),
    ]

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "SwitchBot/27 CFNetwork/3860.300.31 Darwin/25.2.0",
    }

    for auth in auth_candidates:
        headers["auth"] = auth
        try:
            resp = httpx.post(
                f"{BASE_URL}/thing_model/func_request",
                content=body_str,
                headers=headers,
                timeout=5.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 1:
                    return data
                # code != 1 でも返す（エラー内容を見るため）
                return data
        except Exception as e:
            print(f"  接続エラー: {e}")
            return {}

    return {}


def discover_functions():
    """functionIDを探索"""
    # 既知のID周辺と、よくあるID範囲を探索
    known = [9206, 9217, 9225]
    ranges = list(range(9200, 9240)) + list(range(9100, 9130)) + list(range(9000, 9020))
    to_test = sorted(set(known + ranges))

    print(f"functionID探索中 ({len(to_test)}個)...\n")
    found = []

    for fid in to_test:
        result = make_request(fid)
        code = result.get("code", -1)
        payload = result.get("payload", {})
        params = payload.get("params", {})

        if code == 1:
            marker = "★" if fid not in known else "  "
            size = len(json.dumps(params))
            print(f"{marker} functionID={fid}: OK (params size={size})")
            if params:
                preview = json.dumps(params, ensure_ascii=False)[:200]
                print(f"    {preview}")
            found.append(fid)
        elif code != -1:
            # エラーだが応答あり
            print(f"   functionID={fid}: code={code}")

    print(f"\n発見したfunctionID: {found}")


def get_photos():
    """写真タイムライン取得"""
    now = int(time.time())
    params = {
        "0": {
            "is_pic": True,
            "startTime": now - 86400 * 30,  # 30日前から
            "endTime": now,
            "face_ids": [],
        }
    }
    result = make_request(FUNC_PHOTOS, params)
    items = result.get("payload", {}).get("params", {}).get("1", {}).get("list", [])
    print(f"写真数: {len(items)}\n")
    for item in items[:20]:
        ts = item.get("end_time", 0) / 1000
        time_str = time.strftime("%m/%d %H:%M", time.localtime(ts))
        faces = item.get("data", {}).get("faces", [])
        face_names = [f.get("name", "?") for f in faces] if faces else []
        photo_url = f"{BASE_URL}/download/{item['path']}_mini.jpg"
        print(f"  [{time_str}] {item['id']} faces={face_names} url={photo_url}")


def get_faces():
    """顔認識データ取得"""
    result = make_request(FUNC_FACES, {"0": ["stranger", "familiar"]})
    data = result.get("payload", {}).get("params", {}).get("1", {})

    familiar = data.get("familiar", [])
    stranger = data.get("stranger", [])

    print(f"登録者 ({len(familiar)}人):")
    for f in familiar:
        print(f"  {f['name']} (認識回数: {f['count']}, face_id: {f['face_id']})")

    print(f"\n未登録者 ({len(stranger)}人):")
    for s in stranger:
        print(f"  {s['face_id']} (認識回数: {s['count']})")


def get_storage():
    """ストレージ情報"""
    result = make_request(FUNC_STORAGE)
    data = result.get("payload", {}).get("params", {}).get("1", {})
    total = data.get("total", 0) / 1_000_000
    used = data.get("used", 0) / 1_000_000
    print(f"ストレージ: {used:.1f}MB / {total:.1f}MB ({used/total*100:.1f}%)")


def raw_request(func_id: int):
    """任意のfunctionIDを実行"""
    result = make_request(func_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "discover":
        discover_functions()
    elif cmd == "photos":
        get_photos()
    elif cmd == "faces":
        get_faces()
    elif cmd == "storage":
        get_storage()
    elif cmd == "raw" and len(sys.argv) >= 3:
        raw_request(int(sys.argv[2]))
    else:
        print(__doc__)
