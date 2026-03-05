#!/bin/bash
# Setup VLM (Vision Language Model) on Kata Friends device via ADB
# Usage: bash devtools/setup_vlm.sh [KATA_IP]
#
# This script automates:
#   1. Disk space check
#   2. Clone/update rknn-llm repository
#   3. Download VLM model files from HuggingFace
#   4. Update librkllmrt.so (1.2.1 -> 1.2.3)
#   5. Deploy persistent-model flask_server_diary.py
#   6. Create diarymodel.rkllm symlink to VLM model
#   7. Reboot and verify

set -euo pipefail

KATA_IP="${1:-${KATA_IP:-192.168.11.17}}"
ADB_TARGET="${KATA_IP}:5555"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="${SCRIPT_DIR}/.."

# Paths on device
VLM_DIR="/data/ai_brain/vlm"
RKNN_LLM_DIR="/data/rknn-llm"
LIB_DIR="/opt/wlab/sweepbot/lib"
BIN_DIR="/opt/wlab/sweepbot/bin"
OVERLAY_UPPER="/data/overlay_upper"

# Model files
HF_BASE="https://huggingface.co/JiahaoLi/Qwen3-VL-RK3576/resolve/main"
VLM_RKLLM="qwen3-vl-2b-instruct_w4a16_g128_rk3576.rkllm"
VLM_RKNN="qwen3-vl-2b_vision_rk3576.rknn"

echo "============================================"
echo "  Kata Friends VLM Setup"
echo "============================================"
echo "Target: ${ADB_TARGET}"
echo ""

# --- Helper ---
adb_sh() {
    adb -s "${ADB_TARGET}" shell "$@"
}

# --- ADB Connect ---
echo "[0/7] ADB connect..."
adb connect "${ADB_TARGET}" 2>/dev/null || true
adb -s "${ADB_TARGET}" wait-for-device
echo "  Connected."
echo ""

# ============================================================
# [1/7] Disk space check
# ============================================================
echo "[1/7] Checking disk space on /data..."
AVAIL_KB=$(adb_sh "df /data | tail -1 | awk '{print \$4}'" | tr -d '\r\n')
AVAIL_MB=$((AVAIL_KB / 1024))
echo "  Available: ${AVAIL_MB} MB"
if [ "${AVAIL_MB}" -lt 3072 ]; then
    echo "  ERROR: Need at least 3 GB free on /data (have ${AVAIL_MB} MB)"
    exit 1
fi
echo "  OK (>= 3 GB)"
echo ""

# ============================================================
# [2/7] rknn-llm repository
# ============================================================
echo "[2/7] rknn-llm repository..."
HAS_RKNN=$(adb_sh "[ -d ${RKNN_LLM_DIR}/.git ] && echo yes || echo no" | tr -d '\r')
if [ "${HAS_RKNN}" = "yes" ]; then
    echo "  Already exists, pulling latest..."
    adb_sh "cd ${RKNN_LLM_DIR} && git pull" || echo "  Warning: git pull failed (offline?), continuing with existing"
else
    echo "  Cloning rknn-llm (shallow)..."
    adb_sh "git clone --depth 1 https://github.com/airockchip/rknn-llm.git ${RKNN_LLM_DIR}"
fi
echo "  OK"
echo ""

# ============================================================
# [3/7] VLM model download
# ============================================================
echo "[3/7] Downloading VLM model files..."
adb_sh "mkdir -p ${VLM_DIR}"

download_model() {
    local filename="$1"
    local url="${HF_BASE}/${filename}"
    local dest="${VLM_DIR}/${filename}"

    # Check if file already exists with reasonable size
    EXISTING_SIZE=$(adb_sh "[ -f ${dest} ] && stat -c%s ${dest} 2>/dev/null || echo 0" | tr -d '\r\n')

    if [ "${EXISTING_SIZE}" -gt 100000000 ]; then
        echo "  ${filename}: already exists ($(( EXISTING_SIZE / 1024 / 1024 )) MB), skipping"
        return 0
    fi

    echo "  ${filename}: downloading from HuggingFace..."
    adb_sh "wget -c -q --show-progress -O ${dest} '${url}'" || {
        echo "  ERROR: Failed to download ${filename}"
        echo "  URL: ${url}"
        exit 1
    }

    FINAL_SIZE=$(adb_sh "stat -c%s ${dest}" | tr -d '\r\n')
    echo "  ${filename}: done ($(( FINAL_SIZE / 1024 / 1024 )) MB)"
}

download_model "${VLM_RKLLM}"
download_model "${VLM_RKNN}"
echo "  OK"
echo ""

# ============================================================
# [4/7] librkllmrt.so update (1.2.1 -> 1.2.3)
# ============================================================
echo "[4/7] Updating librkllmrt.so (1.2.1 -> 1.2.3)..."
echo "  ⚠  VLM models require runtime >= 1.2.3 (toolkit 1.2.3 format)"

NEW_LIB="${RKNN_LLM_DIR}/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so"

# Verify new lib exists
HAS_NEW_LIB=$(adb_sh "[ -f ${NEW_LIB} ] && echo yes || echo no" | tr -d '\r')
if [ "${HAS_NEW_LIB}" != "yes" ]; then
    echo "  ERROR: New library not found at ${NEW_LIB}"
    echo "  Make sure rknn-llm was cloned successfully in step 2."
    exit 1
fi

# Backup current lib (only if not already backed up)
HAS_BACKUP=$(adb_sh "[ -f ${LIB_DIR}/librkllmrt.so.bak ] && echo yes || echo no" | tr -d '\r')
if [ "${HAS_BACKUP}" != "yes" ]; then
    echo "  Backing up current lib to ${LIB_DIR}/librkllmrt.so.bak"
    adb_sh "cp ${LIB_DIR}/librkllmrt.so ${LIB_DIR}/librkllmrt.so.bak"
fi

# Copy to merged path (live)
echo "  Copying to ${LIB_DIR}/librkllmrt.so"
adb_sh "cp ${NEW_LIB} ${LIB_DIR}/librkllmrt.so"

# Copy to overlay upper (persist across reboot)
echo "  Copying to overlay upper for persistence"
adb_sh "mkdir -p ${OVERLAY_UPPER}${LIB_DIR}"
adb_sh "cp ${NEW_LIB} ${OVERLAY_UPPER}${LIB_DIR}/librkllmrt.so"

# Show version info
echo "  Version info:"
adb_sh "strings ${LIB_DIR}/librkllmrt.so | grep -i 'version\|1\.2\.' | head -3" || true
echo "  OK"
echo ""

# ============================================================
# [5/7] flask_server_diary.py update
# ============================================================
echo "[5/7] Deploying persistent-model flask_server_diary.py..."
LOCAL_DIARY="${REPO_DIR}/devtools/ondevice/flask_server_diary.py"

if [ ! -f "${LOCAL_DIARY}" ]; then
    echo "  ERROR: ${LOCAL_DIARY} not found"
    exit 1
fi

# Push to overlay upper (persists across reboot)
DEST="${OVERLAY_UPPER}${BIN_DIR}/flask_server_diary.py"
adb -s "${ADB_TARGET}" shell "mkdir -p ${OVERLAY_UPPER}${BIN_DIR}"
adb -s "${ADB_TARGET}" push "${LOCAL_DIARY}" "${DEST}"
echo "  Pushed to ${DEST}"

# Also copy to merged path for immediate effect
adb_sh "cp ${DEST} ${BIN_DIR}/flask_server_diary.py"
echo "  OK"
echo ""

# ============================================================
# [6/7] diarymodel.rkllm symlink
# ============================================================
echo "[6/7] Creating diarymodel.rkllm symlink -> VLM model..."
adb_sh "ln -sf ${VLM_DIR}/${VLM_RKLLM} /data/ai_brain/diarymodel.rkllm"
LINK_TARGET=$(adb_sh "readlink /data/ai_brain/diarymodel.rkllm" | tr -d '\r')
echo "  /data/ai_brain/diarymodel.rkllm -> ${LINK_TARGET}"
echo "  OK"
echo ""

# ============================================================
# [7/7] Reboot and verify
# ============================================================
echo "[7/7] Rebooting device to apply overlay changes..."
adb_sh "reboot"

echo "  Waiting for device to come back online..."
sleep 5
for i in $(seq 1 60); do
    if adb connect "${ADB_TARGET}" 2>/dev/null | grep -q "connected"; then
        if adb_sh "echo ready" 2>/dev/null | grep -q "ready"; then
            echo "  Device is back online (${i}s)"
            break
        fi
    fi
    if [ "$i" -eq 60 ]; then
        echo "  WARNING: Device did not come back within 60s."
        echo "  Please check manually."
        exit 1
    fi
    sleep 1
done

echo "  Waiting for llm_diary service to start..."
for i in $(seq 1 120); do
    STATUS=$(adb_sh "systemctl is-active llm_diary 2>/dev/null" 2>/dev/null | tr -d '\r' || echo "unknown")
    if [ "${STATUS}" = "active" ]; then
        echo "  llm_diary service is active (${i}s)"
        break
    fi
    if [ "$i" -eq 120 ]; then
        echo "  WARNING: llm_diary did not become active within 120s"
        echo "  Status: ${STATUS}"
        adb_sh "journalctl -u llm_diary --no-pager -n 20" 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

echo "  Checking for 'Model loaded successfully' in logs..."
for i in $(seq 1 180); do
    if adb_sh "journalctl -u llm_diary --no-pager -n 50 2>/dev/null" 2>/dev/null | grep -q "Model loaded successfully"; then
        echo "  Model loaded successfully!"
        break
    fi
    if [ "$i" -eq 180 ]; then
        echo "  WARNING: 'Model loaded successfully' not found within 180s"
        echo "  Recent logs:"
        adb_sh "journalctl -u llm_diary --no-pager -n 30" 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

echo ""
echo "  Running test inference..."
TEST_RESULT=$(curl -s --max-time 120 -X POST "http://${KATA_IP}:8082/rkllm_diary" \
    -H "Content-Type: application/json" \
    -d '{"task":"custom","prompt":"Hello, say something short."}' 2>/dev/null || echo "CURL_FAILED")

if [ "${TEST_RESULT}" = "CURL_FAILED" ]; then
    echo "  WARNING: Test inference failed (curl error)"
    echo "  Service may still be loading. Try manually:"
    echo "  curl -X POST http://${KATA_IP}:8082/rkllm_diary -H 'Content-Type: application/json' -d '{\"task\":\"custom\",\"prompt\":\"Hello\"}'"
else
    echo "  Test response: ${TEST_RESULT}"
fi

echo ""
echo "============================================"
echo "  VLM Setup Complete!"
echo "============================================"
echo ""
echo "Endpoints:"
echo "  LLM (diary): http://${KATA_IP}:8082/rkllm_diary"
echo "  VLM (image): http://${KATA_IP}:8082/rkllm_vlm"
echo ""
echo "Model: ${VLM_RKLLM}"
echo "Symlink: /data/ai_brain/diarymodel.rkllm -> ${VLM_DIR}/${VLM_RKLLM}"
