**[English](README_en.md)** | 日本語

# Kata Friends 自宅API連携プロジェクト

SwitchBot Kata Friendsのイベントを検知し、自宅APIへ転送するシステム。

## デバイス情報

| 項目 | 値 |
|---|---|
| デバイス名 | KATAフレンズ |
| BLE名 | WoAIPE (WonderLabs AI Pet) |
| メーカー | Woan Technology (Shenzhen) |
| BLE メーカーID | 2409 (SwitchBot/WonderLabs) |
| SwitchBot API deviceId | .envに記載 |
| Wi-Fi IP | .envに記載 |
| Wi-Fi | 2.4GHz帯に接続 |
| ローカルAPIポート | 22090（要auth） |

## 調査結果

### 1. Wi-Fi通信

インターネットへの通信はほぼなし。音声認識・カメラの結果をクラウドに送信していない。

### 2. SwitchBot公式API（v1.1）

| エンドポイント | 結果 |
|---|---|
| `GET /v1.1/devices` | デバイスリストに「KATAフレンズ」として表示される。ただし`deviceType`フィールドが欠落（他デバイスにはある） |
| `GET /v1.1/devices/{id}/status` | `statusCode: 100`（成功）だがbodyが空 `{}` |
| Webhook登録 | 登録は可能だがKata Friendsからのイベントは送信されない |

認証方式: HMAC-SHA256署名（`setup_webhook.py`に実装済み）

### 3. ローカルAPI（ポート22090）

Kata FriendsはLAN上の `http://<KATA_IP>:22090` でHTTPサーバーを稼働。

| 項目 | 値 |
|---|---|
| エンドポイント | `POST /thing_model/func_request` |
| 認証 | `auth` ヘッダー必須（生成方法不明） |
| 現状 | 401 Unauthorized |

**判明している機能**（`kata_local_api.py` — authが通れば利用可能）:

| functionID | 機能 |
|---|---|
| 9206 | ストレージ情報 |
| 9217 | 写真タイムライン（顔認識付き） |
| 9225 | 顔認識データ（登録者・未登録者） |

リクエスト形式:
```json
{
  "version": "1",
  "code": 3,
  "deviceID": "<KATA_DEVICE_ID>",
  "payload": {
    "functionID": 9206,
    "requestID": "UUID",
    "timestamp": 1709500000000,
    "params": {}
  }
}
```

### 4. BLEアドバタイズ（動作中）

状態変化をパッシブに検知可能。現在のシステムはこの方式で動作。

```
xxxxxxxxxxxx | 4c | 01 | 2132 | 0010 | 39 | 00
[  MAC  6B ] |seq | ?? | 固定  | 固定  |b12 |b13
```

| バイト | 内容 | 備考 |
|---|---|---|
| 0-5 | BLE MACアドレス | 固定 |
| 6 | シーケンス番号 | リクエストごとにインクリメント |
| 7 | 不明 | 常に01 |
| 8-9 | 不明 | 常に2132 |
| 10-11 | 不明 | 常に0010 |
| 12 | アクションカウンタ | アクション実行ごとにデクリメント |
| 13 | インタラクションフラグ | 00=待機中, 03=音声応答中 |

### 5. BLE GATT

SwitchBot標準サービス `cba20d00-224d-11e6-9fb8-0002a5d5c51b` を持つ。Writeキャラ（cba20002）とNotifyキャラ（cba20003）あり。通知のプッシュはなくリクエスト-レスポンス型。

| コマンド | 応答 | 解釈 |
|---|---|---|
| 0x5702 (get_status) | `01 64 19` | 01=OK, 64=バッテリー100%?, 19=状態値 |
| 0x5701, 0x5708, 0x5711, 0x5721 | `05` | 非対応 |

## 現在の検知能力

### 検知できること

- **インタラクション開始**: byte[13]が00→03に変化（呼びかけ検知）
- **インタラクション終了**: byte[13]が03→00に変化
- **アクション実行**: byte[12]がデクリメント（ダンス・写真撮影等）

### 検知できないこと

- **音声認識テキスト**: デバイス内で完結、外部に送信されない
- **認識コマンドの種類**: 何を指示したかは不明（反応したかどうかのみ）
- **カメラ映像・顔認識結果**: 外部に送信されない（ただしローカルAPIのauthが解明できれば取得可能）

## アーキテクチャ

```
┌──────────────┐  BLE Advertisement  ┌──────────────┐  HTTP POST  ┌──────────────┐
│ Kata Friends │ ──────────────────→ │ ble_watcher  │ ──────────→ │  home_api    │
│  (WoAIPE)    │  byte[12],[13]変化   │  (Mac上)     │  /events    │  (FastAPI)   │
└──────────────┘                     └──────────────┘             └──────────────┘
```

## ディレクトリ構成

```
kata/
├── .env                      # 秘密情報（トークン、MAC等）
├── .env.example              # .envのテンプレート
├── .gitignore
├── README.md                 # このファイル
├── requirements.txt          # Python依存関係
├── ble_watcher.py            # BLEアドバタイズ監視 → APIイベント送信
├── home_api/
│   └── main.py               # FastAPIイベント受信サーバー
├── proxy/
│   └── kata_proxy.py         # mitmproxy透過プロキシ（未使用: Wi-Fi通信なし）
├── scripts/
│   ├── 01_discover.sh        # ネットワークデバイス探索
│   ├── 02_capture.sh         # tcpdumpパケットキャプチャ
│   ├── 03_analyze_pcap.sh    # pcap解析
│   ├── 04_setup_proxy.sh     # mitmproxyセットアップ（未使用）
│   ├── 05_setup_routing.sh   # macOSルーティング設定（未使用）
│   ├── 06_teardown_routing.sh # ルーティング解除（未使用）
│   ├── setup_webhook.py      # SwitchBot公式API Webhook登録・管理
│   ├── kata_local_api.py     # ローカルAPI（ポート22090）クライアント ※auth未解決
│   ├── ble_monitor.py        # BLEアドバタイズ監視（デバッグ用）
│   ├── ble_gatt_explore.py   # GATT サービス探索
│   └── ble_command.py        # BLEコマンド送信テスト
├── logs/                     # イベントログ（自動生成）
└── captures/                 # pcapファイル（自動生成）
```

## 起動方法

### ターミナル1: APIサーバー
```bash
cd ~/Documents/kata
python3 -m uvicorn home_api.main:app --host 0.0.0.0 --port 9000
```

### ターミナル2: BLE監視
```bash
cd ~/Documents/kata
python3 ble_watcher.py
```

Kata Friendsに話しかけるとイベントが検知され、APIに送信される。

## 依存関係

```bash
pip3 install -r requirements.txt
pip3 install bleak python-dotenv
```

## スクリプト

### メインシステム

#### ble_watcher.py

BLEアドバタイズを監視し、Kata Friendsの状態変化を検知してAPIサーバーにイベントを送信する。

```bash
python3 ble_watcher.py
```

送信されるイベント:
- `interaction_start` — 呼びかけ検知（byte[13]: 00→03）
- `interaction_end` — 応答終了（byte[13]: 03→00）
- `action` — アクション実行（byte[12]がデクリメント）

#### home_api/main.py

BLE監視からのイベントを受信するFastAPIサーバー。イベントは `logs/kata_events.jsonl` に記録される。

```bash
python3 -m uvicorn home_api.main:app --host 0.0.0.0 --port 9000
```

エンドポイント:
- `POST /events` — イベント受信
- `GET /health` — ヘルスチェック

### 調査・デバッグ用スクリプト

#### scripts/ble_monitor.py

BLEアドバタイズの生データを表示するデバッグツール。変化したバイトをハイライト表示する。

```bash
python3 scripts/ble_monitor.py
```

#### scripts/ble_gatt_explore.py

BLE GATTサービスとキャラクタリスティックを列挙する。読み取り可能な値の取得と通知のサブスクライブも行う。

```bash
python3 scripts/ble_gatt_explore.py
```

#### scripts/ble_command.py

BLE GATTキャラクタリスティックにコマンドを送信して応答を確認する。SwitchBot標準コマンド（0x5701〜0x5721）と各種プレフィクスを試行する。

```bash
python3 scripts/ble_command.py
```

#### scripts/kata_local_api.py

Kata Friendsのローカルhttp API（ポート22090）クライアント。authヘッダーの生成方法が未解明のため現在は動作しない。

```bash
python3 scripts/kata_local_api.py discover   # functionID探索
python3 scripts/kata_local_api.py photos     # 写真一覧
python3 scripts/kata_local_api.py faces      # 顔認識データ
python3 scripts/kata_local_api.py storage    # ストレージ情報
python3 scripts/kata_local_api.py raw <ID>   # 任意のfunctionID
```

#### scripts/setup_webhook.py

SwitchBot公式API（v1.1）のWebhook管理。`.env`の`SWITCHBOT_TOKEN`と`SWITCHBOT_SECRET`が必要。

```bash
python3 scripts/setup_webhook.py setup <webhook_url>  # Webhook登録
python3 scripts/setup_webhook.py query                 # 登録状況確認
python3 scripts/setup_webhook.py delete                # Webhook削除
```

### ネットワーク調査スクリプト

```bash
# 1. ネットワーク上のデバイス探索（ARPテーブル表示）
bash scripts/01_discover.sh

# 2. Kata Friendsのパケットキャプチャ（sudo必要）
bash scripts/02_capture.sh <KATA_IP>

# 3. pcapファイルの解析（宛先IP、SNI、HTTPリクエスト抽出）
bash scripts/03_analyze_pcap.sh <pcapファイル>

# 4. mitmproxyのインストールとCA証明書セットアップ
bash scripts/04_setup_proxy.sh

# 5. macOSパケットフォワーディング設定（HTTPS通信をmitmproxyへ転送、sudo必要）
bash scripts/05_setup_routing.sh

# 6. パケットフォワーディング解除
bash scripts/06_teardown_routing.sh
```

## 次のステップ

| アプローチ | 概要 | 難易度 |
|---|---|---|
| Macマイク併用 | BLE検知をトリガーにMacのマイクで録音→Whisper等で音声認識 | 低 |
| ローカルAPI auth解明 | mitmproxy等でSwitchBotアプリの通信を傍受してauthヘッダーの生成ロジックを特定。解決すれば写真・顔認識データにアクセス可能 | 中 |
| ファームウェア解析 | デバイスへのSSHアクセス等で内部データを読む | 高 |
