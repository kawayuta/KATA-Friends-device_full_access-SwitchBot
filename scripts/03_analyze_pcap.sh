#!/bin/bash
# キャプチャファイルから宛先ドメイン・ポート・プロトコルを抽出
PCAP=${1}

echo "=== 宛先IP・ポート一覧 ==="
tcpdump -r "$PCAP" -nn | awk '{print $3}' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' \
  | sort | uniq -c | sort -rn | head -20

echo ""
echo "=== HTTPSドメイン（SNI）==="
# tsharkがある場合
if command -v tshark &> /dev/null; then
  tshark -r "$PCAP" -Y "ssl.handshake.extensions_server_name" \
    -T fields -e ssl.handshake.extensions_server_name | sort | uniq
fi

echo ""
echo "=== プレーンHTTPのURL（あれば）==="
tcpdump -r "$PCAP" -A 2>/dev/null | grep -oE 'Host: [^\r\n]+|GET [^ ]+ |POST [^ ]+ ' | head -30
