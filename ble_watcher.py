"""
Kata Friends BLEアドバタイズ監視 → 自宅APIへイベント転送

起動方法:
  python3 ble_watcher.py
"""

import asyncio
import os
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

import httpx
from bleak import BleakScanner

SWITCHBOT_MFR_ID = 2409
KATA_BLE_MAC = os.environ.get("KATA_BLE_MAC", "").replace(":", "").lower()
HOME_API_URL = os.environ.get("HOME_API_URL", "http://localhost:9000/events")

last_data = None
last_byte12 = None
last_byte13 = None


def send_event(event_type: str, data: dict):
    """自宅APIにイベント送信"""
    payload = {
        "timestamp": datetime.now().isoformat(),
        "source": "kata_friends_ble",
        "type": event_type,
        "data": data,
    }
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] イベント送信: {event_type} {json.dumps(data, ensure_ascii=False)}")

    try:
        response = httpx.post(HOME_API_URL, json=payload, timeout=2.0)
        print(f"  → API応答: {response.status_code}")
    except Exception as e:
        print(f"  → API送信失敗: {e}")


def callback(device, adv):
    global last_data, last_byte12, last_byte13

    mfr = dict(adv.manufacturer_data)
    if SWITCHBOT_MFR_ID not in mfr:
        return

    data = mfr[SWITCHBOT_MFR_ID]
    mac_bytes = data[:6].hex()
    if KATA_BLE_MAC and mac_bytes != KATA_BLE_MAC:
        return

    if data == last_data:
        return

    byte12 = data[12] if len(data) > 12 else None
    byte13 = data[13] if len(data) > 13 else None

    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{ts}] BLE更新: {data.hex()} RSSI={adv.rssi}")

    # byte[13] の変化を検知（インタラクション）
    if last_byte13 is not None and byte13 is not None:
        if last_byte13 == 0x00 and byte13 == 0x03:
            send_event("interaction_start", {
                "rssi": adv.rssi,
                "raw": data.hex(),
            })
        elif last_byte13 == 0x03 and byte13 == 0x00:
            send_event("interaction_end", {
                "rssi": adv.rssi,
                "raw": data.hex(),
            })

    # byte[12] の減少を検知（アクション実行）
    if last_byte12 is not None and byte12 is not None:
        if byte12 < last_byte12:
            send_event("action", {
                "action_counter": byte12,
                "rssi": adv.rssi,
                "raw": data.hex(),
            })

    last_data = data
    last_byte12 = byte12
    last_byte13 = byte13


async def main():
    print(f"Kata Friends BLE監視開始")
    print(f"  BLE MAC: {KATA_BLE_MAC}")
    print(f"  API URL: {HOME_API_URL}")
    print(f"  Ctrl+C で停止\n")

    scanner = BleakScanner(detection_callback=callback)
    await scanner.start()
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await scanner.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n監視終了")
