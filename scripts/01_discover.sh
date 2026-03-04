#!/bin/bash
# Kata FriendsのMACアドレス先頭(SwitchBot OUI)でIPを特定
# SwitchBot OUI: E8:D0:3C / F0:8D:78 など（要確認）

echo "=== ネットワーク上のSwitchBotデバイスを探索 ==="
arp -a | grep -iE "e8:d0|f0:8d|ac:23|d8:f1"

echo ""
echo "=== 全デバイス一覧 ==="
arp -a
