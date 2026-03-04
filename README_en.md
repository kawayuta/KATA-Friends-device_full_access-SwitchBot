English | **[日本語](README.md)**

# Kata Friends Home API Integration

A system that detects SwitchBot Kata Friends events via BLE and forwards them to a home API server.

## Device Info

| Item | Value |
|---|---|
| Device Name | KATA Friends |
| BLE Name | WoAIPE (WonderLabs AI Pet) |
| Manufacturer | Woan Technology (Shenzhen) |
| BLE Manufacturer ID | 2409 (SwitchBot/WonderLabs) |
| SwitchBot API deviceId | See .env |
| Wi-Fi IP | See .env |
| Wi-Fi | Connected to 2.4GHz band |
| Local API Port | 22090 (auth required) |

## Findings

### 1. Wi-Fi Traffic

Almost no internet communication. Voice recognition and camera results are not sent to the cloud.

### 2. SwitchBot Official API (v1.1)

| Endpoint | Result |
|---|---|
| `GET /v1.1/devices` | Listed as "KATA Friends", but `deviceType` field is missing (present for other devices) |
| `GET /v1.1/devices/{id}/status` | `statusCode: 100` (success) but body is empty `{}` |
| Webhook | Registration succeeds but no events are sent from Kata Friends |

Auth: HMAC-SHA256 signature (implemented in `setup_webhook.py`)

### 3. Local API (Port 22090)

Kata Friends runs an HTTP server at `http://<KATA_IP>:22090` on LAN.

| Item | Value |
|---|---|
| Endpoint | `POST /thing_model/func_request` |
| Auth | `auth` header required (generation method unknown) |
| Status | 401 Unauthorized |

**Known functions** (`kata_local_api.py` — usable once auth is solved):

| functionID | Function |
|---|---|
| 9206 | Storage info |
| 9217 | Photo timeline (with face recognition) |
| 9225 | Face recognition data (registered/unregistered) |

Request format:
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

### 4. BLE Advertisement (Working)

State changes can be passively detected. The current system uses this method.

```
xxxxxxxxxxxx | 4c | 01 | 2132 | 0010 | 39 | 00
[  MAC  6B ] |seq | ?? | fixed | fixed |b12 |b13
```

| Byte | Content | Notes |
|---|---|---|
| 0-5 | BLE MAC address | Fixed |
| 6 | Sequence number | Increments per request |
| 7 | Unknown | Always 01 |
| 8-9 | Unknown | Always 2132 |
| 10-11 | Unknown | Always 0010 |
| 12 | Action counter | Decrements on action execution |
| 13 | Interaction flag | 00=idle, 03=voice responding |

### 5. BLE GATT

Has SwitchBot standard service `cba20d00-224d-11e6-9fb8-0002a5d5c51b`. Write characteristic (cba20002) and Notify characteristic (cba20003) available. No push notifications — request-response only.

| Command | Response | Interpretation |
|---|---|---|
| 0x5702 (get_status) | `01 64 19` | 01=OK, 64=battery 100%?, 19=state value |
| 0x5701, 0x5708, 0x5711, 0x5721 | `05` | Not supported |

## Current Detection Capabilities

### What Can Be Detected

- **Interaction start**: byte[13] changes 00→03 (voice command detected)
- **Interaction end**: byte[13] changes 03→00
- **Action execution**: byte[12] decrements (dance, photo, etc.)

### What Cannot Be Detected

- **Voice recognition text**: Processed entirely on-device, not sent externally
- **Command type**: Unknown what was instructed (only whether it reacted)
- **Camera/face recognition results**: Not sent externally (but accessible via local API if auth is solved)

## Architecture

```
┌──────────────┐  BLE Advertisement  ┌──────────────┐  HTTP POST  ┌──────────────┐
│ Kata Friends │ ──────────────────→ │ ble_watcher  │ ──────────→ │  home_api    │
│  (WoAIPE)    │  byte[12],[13]      │  (on Mac)    │  /events    │  (FastAPI)   │
└──────────────┘                     └──────────────┘             └──────────────┘
```

## Directory Structure

```
kata/
├── .env                      # Secrets (tokens, MACs, etc.)
├── .env.example              # .env template
├── .gitignore
├── README.md                 # Japanese documentation
├── README_en.md              # This file
├── requirements.txt          # Python dependencies
├── ble_watcher.py            # BLE advertisement monitor → API event sender
├── home_api/
│   └── main.py               # FastAPI event receiver
├── proxy/
│   └── kata_proxy.py         # mitmproxy transparent proxy (unused: no Wi-Fi traffic)
├── scripts/
│   ├── 01_discover.sh        # Network device discovery
│   ├── 02_capture.sh         # tcpdump packet capture
│   ├── 03_analyze_pcap.sh    # pcap analysis
│   ├── 04_setup_proxy.sh     # mitmproxy setup (unused)
│   ├── 05_setup_routing.sh   # macOS routing setup (unused)
│   ├── 06_teardown_routing.sh # Routing teardown (unused)
│   ├── setup_webhook.py      # SwitchBot official API webhook management
│   ├── kata_local_api.py     # Local API (port 22090) client — auth unsolved
│   ├── ble_monitor.py        # BLE advertisement monitor (debug)
│   ├── ble_gatt_explore.py   # GATT service explorer
│   └── ble_command.py        # BLE command sender/tester
├── logs/                     # Event logs (auto-generated)
└── captures/                 # pcap files (auto-generated)
```

## Getting Started

### Terminal 1: API Server
```bash
pip3 install -r requirements.txt
python3 -m uvicorn home_api.main:app --host 0.0.0.0 --port 9000
```

### Terminal 2: BLE Monitor
```bash
pip3 install bleak python-dotenv
python3 ble_watcher.py
```

Talk to Kata Friends and events will be detected and sent to the API.

## Dependencies

```bash
pip3 install -r requirements.txt
pip3 install bleak python-dotenv
```

## Scripts

### Main System

#### ble_watcher.py

Monitors BLE advertisements, detects Kata Friends state changes, and sends events to the API server.

```bash
python3 ble_watcher.py
```

Events sent:
- `interaction_start` — Voice command detected (byte[13]: 00→03)
- `interaction_end` — Response finished (byte[13]: 03→00)
- `action` — Action executed (byte[12] decrements)

#### home_api/main.py

FastAPI server that receives events from the BLE monitor. Events are logged to `logs/kata_events.jsonl`.

```bash
python3 -m uvicorn home_api.main:app --host 0.0.0.0 --port 9000
```

Endpoints:
- `POST /events` — Receive events
- `GET /health` — Health check

### Investigation & Debug Scripts

#### scripts/ble_monitor.py

Debug tool that displays raw BLE advertisement data. Highlights changed bytes between updates.

```bash
python3 scripts/ble_monitor.py
```

#### scripts/ble_gatt_explore.py

Enumerates BLE GATT services and characteristics. Reads available values and subscribes to notifications.

```bash
python3 scripts/ble_gatt_explore.py
```

#### scripts/ble_command.py

Sends commands to BLE GATT characteristics and checks responses. Tests SwitchBot standard commands (0x5701-0x5721) and various prefixes.

```bash
python3 scripts/ble_command.py
```

#### scripts/kata_local_api.py

Client for Kata Friends' local HTTP API (port 22090). Currently non-functional due to unknown auth header generation method.

```bash
python3 scripts/kata_local_api.py discover   # Scan functionIDs
python3 scripts/kata_local_api.py photos     # Photo list
python3 scripts/kata_local_api.py faces      # Face recognition data
python3 scripts/kata_local_api.py storage    # Storage info
python3 scripts/kata_local_api.py raw <ID>   # Arbitrary functionID
```

#### scripts/setup_webhook.py

SwitchBot official API (v1.1) webhook management. Requires `SWITCHBOT_TOKEN` and `SWITCHBOT_SECRET` in `.env`.

```bash
python3 scripts/setup_webhook.py setup <webhook_url>  # Register webhook
python3 scripts/setup_webhook.py query                 # Check status
python3 scripts/setup_webhook.py delete                # Delete webhook
```

### Network Investigation Scripts

```bash
# 1. Discover devices on network (ARP table)
bash scripts/01_discover.sh

# 2. Capture Kata Friends packets (sudo required)
bash scripts/02_capture.sh <KATA_IP>

# 3. Analyze pcap file (destination IPs, SNI, HTTP requests)
bash scripts/03_analyze_pcap.sh <pcap_file>

# 4. Install mitmproxy and setup CA certificate
bash scripts/04_setup_proxy.sh

# 5. macOS packet forwarding setup (redirect HTTPS to mitmproxy, sudo required)
bash scripts/05_setup_routing.sh

# 6. Tear down packet forwarding
bash scripts/06_teardown_routing.sh
```

## Next Steps

| Approach | Description | Difficulty |
|---|---|---|
| Mac microphone | Use BLE detection as trigger to record with Mac's mic → speech recognition via Whisper etc. | Low |
| Local API auth | Intercept SwitchBot app traffic via mitmproxy to identify auth header generation logic. Unlocks access to photos and face recognition data | Medium |
| Firmware analysis | SSH access to device internals | High |
