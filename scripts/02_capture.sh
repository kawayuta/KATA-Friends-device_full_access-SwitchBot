#!/bin/bash
# 引数: KATA_IP
KATA_IP=${1:?"使い方: ./scripts/02_capture.sh <KATA_IP>"}
OUTPUT="captures/kata_$(date +%Y%m%d_%H%M%S).pcap"

mkdir -p captures
echo "キャプチャ開始: $KATA_IP → $OUTPUT"
echo "Ctrl+C で停止"

sudo tcpdump -i en0 host "$KATA_IP" -w "$OUTPUT"

echo "完了: $OUTPUT"
echo "Wiresharkで開くか、次のコマンドで宛先を確認:"
echo "  tcpdump -r $OUTPUT -nn | awk '{print \$3}' | sort | uniq -c | sort -rn"
