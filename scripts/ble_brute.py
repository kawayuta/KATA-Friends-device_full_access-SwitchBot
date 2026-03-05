"""
Kata Friends BLE GATTコマンド総当たり探索

0x57XX (XX=0x00〜0xFF) を全て試し、応答のあるコマンドを発見する。
既知: 0x5701(05), 0x5702(01 64 19), 0x5708(05), 0x5711(05), 0x5721(05)

使い方:
  python3 scripts/ble_brute.py              # 0x5700〜0x57FF
  python3 scripts/ble_brute.py --prefix 01  # 0x0100〜0x01FF
"""

import asyncio
import argparse
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from bleak import BleakScanner, BleakClient

SWITCHBOT_MFR_ID = 2409
KATA_BLE_MAC = os.environ.get("KATA_BLE_MAC", "").replace(":", "").lower()

WRITE_CHAR = "cba20002-224d-11e6-9fb8-0002a5d5c51b"
NOTIFY_CHAR = "cba20003-224d-11e6-9fb8-0002a5d5c51b"

responses = []
results = {}


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


def notification_handler(sender, data):
    responses.append(data)


async def try_command(client, cmd_bytes, delay=0.5):
    """コマンドを送信して応答を返す。切断時はNoneを返す"""
    responses.clear()
    try:
        if not client.is_connected:
            return None
        await client.write_gatt_char(WRITE_CHAR, cmd_bytes)
        await asyncio.sleep(delay)
        if responses:
            return responses[0]
    except Exception:
        pass
    return None


async def connect_with_retry(address, max_retries=5):
    """リトライ付きBLE接続"""
    for attempt in range(max_retries):
        try:
            client = BleakClient(address, timeout=10)
            await client.connect()
            if client.is_connected:
                return client
        except Exception as e:
            print(f"  接続失敗 ({attempt+1}/{max_retries}): {e}")
            await asyncio.sleep(2)
    return None


async def brute_force(address, prefix):
    print(f"\n接続中: {address}")
    client = await connect_with_retry(address)
    if not client:
        print("接続できませんでした")
        return

    try:
        print(f"接続成功")
        await client.start_notify(NOTIFY_CHAR, notification_handler)

        print(f"\n0x{prefix:02x}00〜0x{prefix:02x}FF を探索中...\n")

        for i in range(256):
            cmd = bytes([prefix, i])
            resp = await try_command(client, cmd)

            if resp:
                resp_hex = resp.hex()
                results[f"{prefix:02x}{i:02x}"] = resp_hex
                # 既知の応答(05=非対応)以外をハイライト
                marker = "  " if resp_hex == "05" else "**"
                print(f"{marker} 0x{prefix:02x}{i:02x} → {resp_hex} ({len(resp)}B)")

            # 進捗表示（32コマンドごと）
            if (i + 1) % 32 == 0 and not resp:
                print(f"   ... 0x{prefix:02x}{i:02x} まで完了 ({i+1}/256)")

        # 3バイトコマンドも試す（応答のあった2バイトコマンドに対して）
        interesting = {k: v for k, v in results.items() if v != "05"}
        if interesting:
            print(f"\n=== 3バイト拡張探索 ===")
            for cmd_hex in interesting:
                base = bytes.fromhex(cmd_hex)
                for ext in [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x0F, 0x10, 0xFF]:
                    cmd = base + bytes([ext])
                    resp = await try_command(client, cmd)
                    if resp:
                        resp_hex = resp.hex()
                        if resp_hex != "05":
                            print(f"** 0x{cmd.hex()} → {resp_hex} ({len(resp)}B)")

    finally:
        await client.disconnect()

    # 結果サマリ
    print(f"\n{'='*50}")
    print(f"応答のあったコマンド: {len(results)}個")
    if interesting:
        print(f"\n非対応(05)以外の応答:")
        for cmd_hex, resp_hex in interesting.items():
            print(f"  0x{cmd_hex} → {resp_hex}")
    else:
        print("新しい応答は見つかりませんでした")

    # 結果をファイルに保存
    out_file = f"logs/ble_brute_{prefix:02x}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    os.makedirs("logs", exist_ok=True)
    with open(out_file, "w") as f:
        json.dump({"prefix": f"0x{prefix:02x}", "results": results}, f, indent=2)
    print(f"\n結果保存: {out_file}")


async def main():
    parser = argparse.ArgumentParser(description="BLE GATTコマンド総当たり探索")
    parser.add_argument("--prefix", default="57", help="1バイト目のプレフィクス (hex, デフォルト: 57)")
    args = parser.parse_args()
    prefix = int(args.prefix, 16)

    address = await find_kata()
    if not address:
        print("Kata Friendsが見つかりません")
        return
    await brute_force(address, prefix)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n中断")
