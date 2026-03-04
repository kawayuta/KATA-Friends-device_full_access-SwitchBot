"""
Kata Friends BLEコマンド送信・応答取得

使い方:
  python3 scripts/ble_command.py
"""

import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from bleak import BleakScanner, BleakClient

SWITCHBOT_MFR_ID = 2409
KATA_BLE_MAC = os.environ.get("KATA_BLE_MAC", "").replace(":", "").lower()

WRITE_CHAR = "cba20002-224d-11e6-9fb8-0002a5d5c51b"
NOTIFY_CHAR = "cba20003-224d-11e6-9fb8-0002a5d5c51b"

# SwitchBot BLE標準コマンド
COMMANDS = {
    "get_info": bytes([0x57, 0x01]),        # デバイス情報取得
    "get_status": bytes([0x57, 0x02]),      # ステータス取得
    "get_timer": bytes([0x57, 0x08]),       # タイマー情報
    "get_settings": bytes([0x57, 0x11]),    # 設定取得
    "extended_info": bytes([0x57, 0x21]),   # 拡張情報
}


async def find_kata():
    print("Kata Friendsを探索中...")
    devices = await BleakScanner.discover(timeout=10, return_adv=True)
    for addr, (device, adv) in devices.items():
        mfr = dict(adv.manufacturer_data)
        if SWITCHBOT_MFR_ID in mfr:
            data = mfr[SWITCHBOT_MFR_ID]
            mac_bytes = data[:6].hex()
            name = adv.local_name or ""
            if mac_bytes == KATA_BLE_MAC or "WoAIPE" in name:
                print(f"発見: {device.address} ({name})")
                return device.address
    return None


responses = []


def notification_handler(sender, data):
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    responses.append(data)
    print(f"  [{ts}] 応答: {data.hex()} ({len(data)} bytes)")
    try:
        text = data.decode("utf-8", errors="replace")
        if any(c.isalpha() for c in text):
            print(f"  テキスト: {text}")
    except Exception:
        pass


async def send_commands(address):
    print(f"\n接続中: {address}")
    async with BleakClient(address) as client:
        print(f"接続成功\n")

        await client.start_notify(NOTIFY_CHAR, notification_handler)

        for name, cmd in COMMANDS.items():
            print(f"--- コマンド: {name} ({cmd.hex()}) ---")
            responses.clear()
            try:
                await client.write_gatt_char(WRITE_CHAR, cmd)
                await asyncio.sleep(2)
                if not responses:
                    print("  応答なし")
            except Exception as e:
                print(f"  エラー: {e}")
            print()

        # 追加: 0x00-0xFF の1バイトプレフィクスで探索
        print("=== 追加探索: 各種プレフィクス ===")
        for prefix in [0x01, 0x02, 0x03, 0x04, 0x05, 0x0A, 0x0F, 0x10, 0x11, 0x12, 0x20, 0x30, 0x40, 0x50, 0xA0, 0xB0, 0xC0, 0xE0, 0xF0]:
            cmd = bytes([prefix])
            responses.clear()
            try:
                await client.write_gatt_char(WRITE_CHAR, cmd)
                await asyncio.sleep(0.5)
                if responses:
                    print(f"  0x{prefix:02x} → 応答あり: {responses[0].hex()}")
            except Exception:
                pass

        # 通知を待つ（話しかけてみる）
        print("\n=== 通知待機（30秒）===")
        print("Kata Friendsに話しかけてください...")
        responses.clear()
        await asyncio.sleep(30)
        if not responses:
            print("通知なし")

        print("\n完了")


async def main():
    address = await find_kata()
    if not address:
        print("Kata Friendsが見つかりません")
        return
    await send_commands(address)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n中断")
