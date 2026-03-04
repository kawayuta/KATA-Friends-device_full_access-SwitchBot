"""
Kata Friends BLE GATTサービス探索

使い方:
  python3 scripts/ble_gatt_explore.py
"""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from bleak import BleakScanner, BleakClient

SWITCHBOT_MFR_ID = 2409
KATA_BLE_MAC = os.environ.get("KATA_BLE_MAC", "").replace(":", "").lower()


async def find_kata():
    """BLEスキャンでKata Friendsを探す"""
    print("Kata Friendsを探索中...")
    devices = await BleakScanner.discover(timeout=10, return_adv=True)
    for addr, (device, adv) in devices.items():
        mfr = dict(adv.manufacturer_data)
        if SWITCHBOT_MFR_ID in mfr:
            data = mfr[SWITCHBOT_MFR_ID]
            mac_bytes = data[:6].hex()
            name = adv.local_name or ""
            print(f"  SwitchBotデバイス: {device.address} | {name} | mac={mac_bytes}")
            if mac_bytes == KATA_BLE_MAC or "WoAIPE" in name:
                print(f"  → Kata Friends発見!")
                return device.address
    print("見つかりませんでした。SwitchBotデバイス一覧は上記の通り。")
    return None


def notification_handler(sender, data):
    """GATT通知のハンドラ"""
    print(f"  通知: {sender} -> {data.hex()} ({len(data)} bytes)")
    try:
        text = data.decode("utf-8", errors="replace")
        if text.isprintable():
            print(f"  テキスト: {text}")
    except Exception:
        pass


async def explore(address):
    """GATTサービスとキャラクタリスティックを列挙"""
    print(f"\n接続中: {address}")
    async with BleakClient(address) as client:
        print(f"接続成功: {client.is_connected}")
        print("\n=== サービス一覧 ===")

        for service in client.services:
            print(f"\nサービス: {service.uuid}")
            print(f"  説明: {service.description}")

            for char in service.characteristics:
                props = ", ".join(char.properties)
                print(f"  キャラクタリスティック: {char.uuid}")
                print(f"    プロパティ: {props}")

                # 読み取り可能なら値を取得
                if "read" in char.properties:
                    try:
                        value = await client.read_gatt_char(char)
                        print(f"    値: {value.hex()} ({len(value)} bytes)")
                        try:
                            text = value.decode("utf-8", errors="replace")
                            if text.isprintable():
                                print(f"    テキスト: {text}")
                        except Exception:
                            pass
                    except Exception as e:
                        print(f"    読み取りエラー: {e}")

                # 通知可能ならサブスクライブ
                if "notify" in char.properties:
                    try:
                        await client.start_notify(char, notification_handler)
                        print(f"    通知サブスクライブ開始")
                    except Exception as e:
                        print(f"    通知サブスクライブ失敗: {e}")

        # 通知を30秒間待つ
        print("\n=== 通知待機中（30秒）===")
        print("Kata Friendsに話しかけてください...")
        await asyncio.sleep(30)
        print("\n探索完了")


async def main():
    address = await find_kata()
    if not address:
        print("Kata Friendsが見つかりません")
        return
    await explore(address)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n中断")
