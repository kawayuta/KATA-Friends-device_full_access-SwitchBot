"""
Kata Friends BLEアドバタイズ監視スクリプト

使い方:
  python3 scripts/ble_monitor.py
"""

import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from bleak import BleakScanner

KATA_BLE_MAC = os.environ.get("KATA_BLE_MAC", "").replace(":", "").lower()

last_data = None


def callback(device, adv):
    global last_data
    mfr = dict(adv.manufacturer_data)
    if 2409 not in mfr:
        return
    data = mfr[2409]
    mac_bytes = data[:6].hex()
    if KATA_BLE_MAC and mac_bytes != KATA_BLE_MAC.lower():
        return

    if data != last_data:
        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        hex_str = data.hex()
        # バイト単位で変化箇所を表示
        diff = ""
        if last_data:
            for i, (a, b) in enumerate(zip(last_data, data)):
                if a != b:
                    diff += f" byte[{i}]:{a:02x}->{b:02x}"
        print(f"[{ts}] RSSI={adv.rssi} | {hex_str}{diff}")
        last_data = data


async def monitor():
    print(f"Kata Friends BLE監視開始 (MAC: {KATA_BLE_MAC})")
    print("話しかけてデータ変化を観察してください。Ctrl+Cで停止。")
    print()
    scanner = BleakScanner(detection_callback=callback)
    await scanner.start()
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await scanner.stop()
        print("\n監視終了")


if __name__ == "__main__":
    try:
        asyncio.run(monitor())
    except KeyboardInterrupt:
        print("\n監視終了")
