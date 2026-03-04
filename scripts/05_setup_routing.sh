#!/bin/bash
# macOSでパケットフォワーディングを有効化し
# Kata FriendsのHTTPS通信をmitmproxyへ向ける

source .env 2>/dev/null
if [ -z "$KATA_MAC" ]; then
  echo "エラー: KATA_MACが設定されていません (.envを確認)"
  exit 1
fi
PROXY_PORT=8080

# MACアドレスからIPを自動解決
KATA_IP=$(arp -a | grep -i "$KATA_MAC" | grep -oE '\(([0-9]+\.)+[0-9]+\)' | tr -d '()')
if [ -z "$KATA_IP" ]; then
  echo "エラー: Kata Friends ($KATA_MAC) がネットワーク上に見つかりません"
  exit 1
fi
echo "Kata Friends IP: $KATA_IP"

echo "=== IPフォワーディング有効化 ==="
sudo sysctl -w net.inet.ip.forwarding=1

echo ""
echo "=== pfctl ルール設定 ==="
# /etc/pf.conf に追記 or 一時ルール
sudo pfctl -f - << EOF
rdr pass on en0 proto tcp from $KATA_IP to any port 443 -> 127.0.0.1 port $PROXY_PORT
pass out route-to lo0 inet proto tcp from $KATA_IP to any port 443
EOF

sudo pfctl -e

echo "完了。mitmproxyを起動してください:"
echo "  mitmweb -s proxy/kata_proxy.py --mode transparent -p $PROXY_PORT --ssl-insecure"
