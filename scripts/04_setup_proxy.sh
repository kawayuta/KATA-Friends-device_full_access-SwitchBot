#!/bin/bash
# mitmproxy インストールと証明書セットアップ

echo "=== mitmproxy インストール ==="
brew install mitmproxy

echo ""
echo "=== CA証明書の生成 ==="
echo "一度 mitmproxy を起動して証明書を生成します（5秒後に自動終了）"
timeout 5 mitmproxy || true

CA_PATH="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"
echo ""
echo "CA証明書の場所: $CA_PATH"
echo ""
echo "=== 次のステップ ==="
echo "1. ルーターの管理画面で Kata Friends の静的IPを設定"
echo "2. ルーターでDNSを自宅Macに向ける（または個別ルーティング）"
echo "3. macOSのCA証明書を信頼:"
echo "   sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain $CA_PATH"
