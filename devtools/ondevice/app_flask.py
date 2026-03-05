"""
Kata Friends Developer Tools — Flask on-device backend

Device dependencies only: Flask 3.0.2, requests, jinja2
Runs directly on device at /data/devtools/, port 9001.
"""

import glob
import hashlib
import json
import os
import re
import time
import uuid

import requests
from flask import Flask, abort, jsonify, request, send_from_directory

# --- Config ---
# On-device: everything is localhost
LOCAL_API_PORT = int(os.environ.get("KATA_LOCAL_PORT", "27999"))
DEVICE_ID = os.environ.get("KATA_DEVICE_ID", "")
LOCAL_TOKEN = os.environ.get("KATA_LOCAL_TOKEN", "")

app = Flask(__name__, static_folder="static", static_url_path="/static")


# --- Auto-discover device ID and token from MQTT logs ---

def _read_token_from_logs():
    """Read local token from MQTT log files (functionID:1021 response)."""
    log_pattern = "/data/cache/log/cc_mqtt.*.log"
    files = sorted(glob.glob(log_pattern), key=os.path.getmtime, reverse=True)
    for f in files:
        try:
            with open(f, "r", errors="ignore") as fh:
                content = fh.read()
            # Look for token in functionID:1021 responses
            for m in re.finditer(r'"token"\s*:\s*"([0-9a-f-]{36})"', content):
                return m.group(1)
        except Exception:
            continue
    return ""


def _read_device_id_from_logs():
    """Read device ID from MQTT log files."""
    log_pattern = "/data/cache/log/cc_mqtt.*.log"
    files = sorted(glob.glob(log_pattern), key=os.path.getmtime, reverse=True)
    for f in files:
        try:
            with open(f, "r", errors="ignore") as fh:
                content = fh.read()
            for m in re.finditer(r'"deviceID"\s*:\s*"([A-F0-9]+)"', content):
                return m.group(1)
        except Exception:
            continue
    return ""


def _ensure_config():
    global DEVICE_ID, LOCAL_TOKEN
    if not DEVICE_ID:
        DEVICE_ID = _read_device_id_from_logs()
    if not LOCAL_TOKEN:
        LOCAL_TOKEN = _read_token_from_logs()


# --- ZMQ publish (import from local module) ---

from zmq_publish import publish as zmq_publish_msg


# --- Helpers ---

def make_auth(body_str):
    return hashlib.md5((body_str + LOCAL_TOKEN).encode()).hexdigest()


def build_local_payload(function_id, params=None):
    payload = {
        "version": "1",
        "code": 3,
        "deviceID": DEVICE_ID,
        "payload": {
            "functionID": function_id,
            "requestID": str(uuid.uuid4()).upper(),
            "timestamp": int(time.time() * 1000),
            "params": params or {},
        },
    }
    return json.dumps(payload, separators=(",", ":"))


def flask_error(status, message):
    return jsonify({"detail": message}), status


# LLM instruction -> ZMQ start_cc_task payload mapping
ACTION_MAP = {
    "dance":        {"action": "RDANCE008", "task_name": "music"},
    "sing":         {"action": "RSING001",  "task_name": "music"},
    "take_photo":   {"action": "RPIC001",   "task_name": "take_photo"},
    "welcome":      {"action": "RHUG002",   "task_name": "welcome"},
    "say_hello":    {"action": "RIMGHI001", "task_name": "hello"},
    "bye":          {"action": "RTHDL50",   "task_name": "bye"},
    "good_morning": {"action": "RIMGHI001", "task_name": "good_morning"},
    "good_night":   {"action": "RTHDL50",   "task_name": "good_night"},
    "wave_hand":    {"action": "RIMGHI001", "task_name": "wave_hand"},
    "show_love":    {"action": "RHAPPY001", "task_name": "show_love"},
    "get_praise":   {"action": "RHAPPY001", "task_name": "get_praise"},
    "wake_up":      {"action": "RAWAKE001", "task_name": "wake_up"},
    "nod":          {"action": "RANodyes",  "task_name": "nod"},
    "shake_head":   {"action": "RANO",      "task_name": "shake_head"},
    "speak":        {"action": "RSAYS001",  "task_name": "speak"},
    "look_left":    {"action": "RAFL",      "task_name": "look_left"},
    "look_right":   {"action": "RAFR",      "task_name": "look_right"},
    "look_up":      {"action": "RAUP",      "task_name": "look_up"},
    "look_down":    {"action": "RADOWN",    "task_name": "look_down"},
    "spin":         {"action": "RWCIR001",  "task_name": "spin"},
    "come_over":    {"task_name": "come_over"},
    "follow_me":    {"task_name": "follow_me"},
    "go_away":      {"task_name": "go_away"},
    "go_play":      {"task_name": "go_play"},
    "go_sleep":     {"task_name": "go_sleep"},
    "go_power":     {"task_name": "go_power"},
    "go_to_kitchen":  {"task_name": "go_to_kitchen"},
    "go_to_bedroom":  {"task_name": "go_to_bedroom"},
    "go_to_balcony":  {"task_name": "go_to_balcony"},
    "move_forward": {"task_name": "move_forward"},
    "move_back":    {"task_name": "move_back"},
    "move_left":    {"task_name": "move_left"},
    "move_right":   {"task_name": "move_right"},
    "turn_left":    {"task_name": "turn_left"},
    "turn_right":   {"task_name": "turn_right"},
    "stop":         {"task_name": "stop"},
    "be_silent":    {"task_name": "be_silent"},
    "volume_up":    {"task_name": "volume_up"},
    "volume_down":  {"task_name": "volume_down"},
    "user_leave":   {"task_name": "user_leave"},
}


# --- Endpoints ---

@app.post("/api/action")
def proxy_action():
    """LLM action server (:8080) proxy."""
    data = request.get_json(force=True)
    voice_text = data.get("voiceText", "")
    if not voice_text:
        return flask_error(400, "voiceText is required")
    try:
        resp = requests.post(
            "http://127.0.0.1:8080/rkllm_action",
            json={"voiceText": voice_text},
            timeout=30,
        )
        text = resp.text.strip()
        parts = text.split("/", 1)
        return jsonify({
            "raw": text,
            "mood": parts[0] if parts else text,
            "instruction": parts[1] if len(parts) > 1 else "",
        })
    except requests.ConnectionError:
        return flask_error(502, "action server unreachable")
    except Exception as e:
        return flask_error(502, str(e))


@app.post("/api/diary")
def proxy_diary():
    """LLM diary server (:8082) proxy."""
    data = request.get_json(force=True)
    events = data.get("events", [])
    language = data.get("language", "ja")
    local_date = data.get("local_date", "") or time.strftime("%Y-%m-%d")

    lang_map = {"ja": "Japanese", "en": "English", "zh": "Chinese"}
    lang_name = lang_map.get(language, language)
    events_str = "\n".join(events)
    prompt = f"language:{lang_name}\nlocal_date:{local_date}\nevents:\n{events_str}"

    try:
        resp = requests.post(
            "http://127.0.0.1:8082/rkllm_diary",
            json={"task": "diary", "prompt": prompt},
            timeout=30,
        )
        try:
            return jsonify(resp.json())
        except Exception:
            return jsonify({"raw": resp.text.strip()})
    except requests.ConnectionError:
        return flask_error(502, "diary server unreachable")
    except Exception as e:
        return flask_error(502, str(e))


@app.post("/api/local")
def proxy_local():
    """Local API (:27999) proxy with MD5 auth."""
    _ensure_config()
    data = request.get_json(force=True)
    function_id = data.get("function_id")
    params = data.get("params")

    body_str = build_local_payload(function_id, params)
    auth = make_auth(body_str)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "auth": auth,
    }
    try:
        resp = requests.post(
            f"http://127.0.0.1:{LOCAL_API_PORT}/thing_model/func_request",
            data=body_str,
            headers=headers,
            timeout=10,
        )
        return jsonify(resp.json())
    except requests.ConnectionError:
        return flask_error(502, "local API unreachable")
    except Exception as e:
        return flask_error(502, str(e))


@app.post("/api/zmq/publish")
def zmq_publish():
    """Publish directly to local ZMQ bus (:5558)."""
    data = request.get_json(force=True)
    topic = data.get("topic", "/ai/do_action")
    payload = data.get("payload", {})

    payload_json = json.dumps(payload, separators=(",", ":"))
    try:
        zmq_publish_msg(topic, payload_json)
        return jsonify({"status": "ok", "topic": topic, "payload": payload})
    except Exception as e:
        return flask_error(502, f"ZMQ publish failed: {e}")


@app.post("/api/execute")
def execute_action():
    """LLM classify -> ZMQ publish pipeline."""
    _ensure_config()
    data = request.get_json(force=True)
    voice_text = data.get("voiceText", "")
    if not voice_text:
        return flask_error(400, "voiceText is required")

    # Step 1: LLM classification
    try:
        resp = requests.post(
            "http://127.0.0.1:8080/rkllm_action",
            json={"voiceText": voice_text},
            timeout=30,
        )
    except requests.ConnectionError:
        return flask_error(502, "action server unreachable")

    text = resp.text.strip()
    parts = text.split("/", 1)
    mood = parts[0] if parts else text
    instruction = parts[1] if len(parts) > 1 else ""

    if not instruction or instruction == "no_action":
        return jsonify({"raw": text, "mood": mood, "instruction": instruction, "executed": False})

    # Step 2: Map instruction -> ZMQ publish
    mapping = ACTION_MAP.get(instruction)
    if not mapping:
        return jsonify({"raw": text, "mood": mood, "instruction": instruction, "executed": False,
                        "error": f"unknown instruction: {instruction}"})

    ts = int(time.time() * 1e9)
    payload_dict = {"task_type": "voice", "timestamp": ts, **mapping}
    payload_json = json.dumps(payload_dict, separators=(",", ":"))

    try:
        zmq_publish_msg("/agent/start_cc_task", payload_json)
    except Exception:
        return jsonify({"raw": text, "mood": mood, "instruction": instruction, "executed": False,
                        "error": "ZMQ publish failed"})

    return jsonify({"raw": text, "mood": mood, "instruction": instruction, "payload": payload_dict, "executed": True})


@app.get("/api/health")
def health_check():
    """Check local service ports."""
    ports = {
        "zmq_xpub": 5558,
        "zmq_xsub": 5559,
        "llm_action": 8080,
        "llm_diary": 8082,
        "llm_router": 8083,
        "local_api": LOCAL_API_PORT,
        "control_center": 50001,
    }
    results = {}
    for name, port in ports.items():
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/", timeout=2)
            results[name] = {"port": port, "status": "up", "code": resp.status_code}
        except requests.ConnectionError:
            results[name] = {"port": port, "status": "down"}
        except requests.Timeout:
            results[name] = {"port": port, "status": "up (timeout)"}
        except Exception:
            results[name] = {"port": port, "status": "up (non-http)"}
    return jsonify({"ip": "127.0.0.1 (on-device)", "services": results})


@app.get("/api/events")
def get_events():
    """Return recent events from log file."""
    log_path = "/data/cache/log/kata_events.jsonl"
    if not os.path.exists(log_path):
        return jsonify({"events": [], "total": 0})
    with open(log_path, "r") as f:
        lines = f.read().strip().split("\n")
    n = request.args.get("n", 50, type=int)
    events = []
    for line in lines[-n:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return jsonify({"events": list(reversed(events)), "total": len(lines)})


# --- Static file serving ---

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    _ensure_config()
    print(f"[DevTools] Device ID: {DEVICE_ID or '(not found)'}")
    print(f"[DevTools] Token: {'***' + LOCAL_TOKEN[-4:] if LOCAL_TOKEN else '(not found)'}")
    app.run(host="0.0.0.0", port=9001, debug=False)
