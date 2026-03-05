#!/bin/env python3
# dev file for diary server
# Modified: persistent model loading (load once at startup, reuse for all requests)
import ctypes
import sys
import os
import subprocess
import resource
import threading
import time
import argparse
from flask import Flask, request, jsonify, Response
import re
import json
import logging
from logging.handlers import TimedRotatingFileHandler

os.environ["TZ"] = "Asia/Shanghai"
time.tzset()
app = Flask(__name__)


# ==========================
# 日志配置
# ==========================
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 终端日志
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter(
    fmt='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# 文件日志
file_handler = TimedRotatingFileHandler(
    filename="/data/cache/log/rkllm_diary_server.log",
    when="midnight",
    interval=1,
    backupCount=7,
    encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(console_formatter)
logger.addHandler(file_handler)


# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# This server loads the model ONCE at startup and keeps it resident.
# Per-request, only the chat template (system prompt) is changed.
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++


def _load_system_prompt_from_disk(task_type):
    """Load the appropriate system prompt based on the task type."""
    base_path = os.environ.get('SYSTEM_PROMPT_FILE', 'system_prompt_diary.txt')

    try:
        if task_type == "diary":
            prompt_file = base_path
        elif task_type == "translation":
            prompt_file = os.environ.get('SYSTEM_PROMPT_TRANSLATION_FILE', 'system_prompt_diary_translation.txt')
        else:
            # custom task: no system prompt (caller provides full prompt)
            return ""

        if os.path.exists(prompt_file):
            with open(prompt_file, 'r', encoding='utf-8') as f:
                logger.info(f"[INFO] Loading system prompt for task '{task_type}' from '{prompt_file}'")
                return f.read()
        else:
            raise FileNotFoundError(f"System prompt file not found: {prompt_file}.")

    except Exception as e:
        logger.error(f"[ERROR] Failed to read system prompt for task '{task_type}': {e}")
        raise Exception(f"Failed to read system prompt: {e}")

# Set the dynamic library path
rkllm_lib = ctypes.CDLL('lib/librkllmrt.so')

# Define the structures from the library
RKLLM_Handle_t = ctypes.c_void_p
userdata = ctypes.c_void_p(None)

LLMCallState = ctypes.c_int
LLMCallState.RKLLM_RUN_NORMAL  = 0
LLMCallState.RKLLM_RUN_WAITING  = 1
LLMCallState.RKLLM_RUN_FINISH  = 2
LLMCallState.RKLLM_RUN_ERROR   = 3

RKLLMInputType = ctypes.c_int
RKLLMInputType.RKLLM_INPUT_PROMPT      = 0
RKLLMInputType.RKLLM_INPUT_TOKEN       = 1
RKLLMInputType.RKLLM_INPUT_EMBED       = 2
RKLLMInputType.RKLLM_INPUT_MULTIMODAL  = 3

RKLLMInferMode = ctypes.c_int
RKLLMInferMode.RKLLM_INFER_GENERATE = 0
RKLLMInferMode.RKLLM_INFER_GET_LAST_HIDDEN_LAYER = 1
RKLLMInferMode.RKLLM_INFER_GET_LOGITS = 2

class RKLLMExtendParam(ctypes.Structure):
    _fields_ = [
        ("base_domain_id", ctypes.c_int32),
        ("embed_flash", ctypes.c_int8),
        ("enabled_cpus_num", ctypes.c_int8),
        ("enabled_cpus_mask", ctypes.c_uint32),
        ("n_batch", ctypes.c_uint8),
        ("use_cross_attn", ctypes.c_int8),
        ("reserved", ctypes.c_uint8 * 104)
    ]

class RKLLMParam(ctypes.Structure):
    _fields_ = [
        ("model_path", ctypes.c_char_p),
        ("max_context_len", ctypes.c_int32),
        ("max_new_tokens", ctypes.c_int32),
        ("top_k", ctypes.c_int32),
        ("n_keep", ctypes.c_int32),
        ("top_p", ctypes.c_float),
        ("temperature", ctypes.c_float),
        ("repeat_penalty", ctypes.c_float),
        ("frequency_penalty", ctypes.c_float),
        ("presence_penalty", ctypes.c_float),
        ("mirostat", ctypes.c_int32),
        ("mirostat_tau", ctypes.c_float),
        ("mirostat_eta", ctypes.c_float),
        ("skip_special_token", ctypes.c_bool),
        ("is_async", ctypes.c_bool),
        ("img_start", ctypes.c_char_p),
        ("img_end", ctypes.c_char_p),
        ("img_content", ctypes.c_char_p),
        ("extend_param", RKLLMExtendParam),
    ]

class RKLLMLoraAdapter(ctypes.Structure):
    _fields_ = [
        ("lora_adapter_path", ctypes.c_char_p),
        ("lora_adapter_name", ctypes.c_char_p),
        ("scale", ctypes.c_float)
    ]

class RKLLMEmbedInput(ctypes.Structure):
    _fields_ = [
        ("embed", ctypes.POINTER(ctypes.c_float)),
        ("n_tokens", ctypes.c_size_t)
    ]

class RKLLMTokenInput(ctypes.Structure):
    _fields_ = [
        ("input_ids", ctypes.POINTER(ctypes.c_int32)),
        ("n_tokens", ctypes.c_size_t)
    ]

class RKLLMMultiModelInput(ctypes.Structure):
    _fields_ = [
        ("prompt", ctypes.c_char_p),
        ("image_embed", ctypes.POINTER(ctypes.c_float)),
        ("n_image_tokens", ctypes.c_size_t),
        ("n_image", ctypes.c_size_t),
        ("image_width", ctypes.c_size_t),
        ("image_height", ctypes.c_size_t)
    ]

class RKLLMInputUnion(ctypes.Union):
    _fields_ = [
        ("prompt_input", ctypes.c_char_p),
        ("embed_input", RKLLMEmbedInput),
        ("token_input", RKLLMTokenInput),
        ("multimodal_input", RKLLMMultiModelInput)
    ]

class RKLLMInput(ctypes.Structure):
    _fields_ = [
        ("role", ctypes.c_char_p),
        ("enable_thinking", ctypes.c_bool),
        ("input_type", RKLLMInputType),
        ("input_data", RKLLMInputUnion)
    ]

class RKLLMLoraParam(ctypes.Structure):
    _fields_ = [
        ("lora_adapter_name", ctypes.c_char_p)
    ]

class RKLLMPromptCacheParam(ctypes.Structure):
    _fields_ = [
        ("save_prompt_cache", ctypes.c_int),
        ("prompt_cache_path", ctypes.c_char_p)
    ]

class RKLLMInferParam(ctypes.Structure):
    _fields_ = [
        ("mode", RKLLMInferMode),
        ("lora_params", ctypes.POINTER(RKLLMLoraParam)),
        ("prompt_cache_params", ctypes.POINTER(RKLLMPromptCacheParam)),
        ("keep_history", ctypes.c_int)
    ]

class RKLLMResultLastHiddenLayer(ctypes.Structure):
    _fields_ = [
        ("hidden_states", ctypes.POINTER(ctypes.c_float)),
        ("embd_size", ctypes.c_int),
        ("num_tokens", ctypes.c_int)
    ]

class RKLLMResultLogits(ctypes.Structure):
    _fields_ = [
        ("logits", ctypes.POINTER(ctypes.c_float)),
        ("vocab_size", ctypes.c_int),
        ("num_tokens", ctypes.c_int)
    ]

class RKLLMPerfStat(ctypes.Structure):
    _fields_ = [
        ("prefill_time_ms", ctypes.c_float),
        ("prefill_tokens", ctypes.c_int),
        ("generate_time_ms", ctypes.c_float),
        ("generate_tokens", ctypes.c_int),
        ("memory_usage_mb", ctypes.c_float)
    ]

class RKLLMResult(ctypes.Structure):
    _fields_ = [
        ("text", ctypes.c_char_p),
        ("token_id", ctypes.c_int),
        ("last_hidden_layer", RKLLMResultLastHiddenLayer),
        ("logits", RKLLMResultLogits),
        ("perf", RKLLMPerfStat)
    ]

# Create a lock to control multi-user access to the server.
lock = threading.Lock()

# Create a global variable to indicate whether the server is currently in a blocked state.
is_blocking = False

# Define global variables to store the callback function output
system_prompt = ''
global_text = []
global_state = -1
split_byte_data = bytes(b"")
global_perf_stats = None
SERVER_ARGS = None

# Persistent model handle (loaded once at startup)
PERSISTENT_MODEL = None

# Define the callback function
def callback_impl(result, userdata, state):
    global global_text, global_state, split_byte_data, global_perf_stats
    if state == LLMCallState.RKLLM_RUN_FINISH:
        global_state = state
        perf = result.contents.perf
        global_perf_stats = {
            "prefill_time_ms": perf.prefill_time_ms,
            "prefill_tokens": perf.prefill_tokens,
            "generate_time_ms": perf.generate_time_ms,
            "generate_tokens": perf.generate_tokens,
            "memory_usage_mb": perf.memory_usage_mb
        }
        logger.info("\n[PERF] === Performance Stats ===")
        logger.info(f"[PERF] Prefill: {perf.prefill_tokens} tokens in {perf.prefill_time_ms:.2f} ms")
        logger.info(f"[PERF] Generate: {perf.generate_tokens} tokens in {perf.generate_time_ms:.2f} ms")
        if perf.generate_time_ms > 0:
            tokens_per_sec = perf.generate_tokens / (perf.generate_time_ms / 1000)
            logger.info(f"[PERF] Speed: {tokens_per_sec:.2f} tokens/sec")
        logger.info(f"[PERF] Memory: {perf.memory_usage_mb:.2f} MB")
        sys.stdout.flush()
    elif state == LLMCallState.RKLLM_RUN_ERROR:
        global_state = state
        logger.error("run error")
        sys.stdout.flush()
    elif state == LLMCallState.RKLLM_RUN_NORMAL:
        global_state = state
        global_text.append(result.contents.text.decode('utf-8'))
    return 0

# Connect the callback function between the Python side and the C++ side
callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(RKLLMResult), ctypes.c_void_p, ctypes.c_int)
callback = callback_type(callback_impl)


def init_persistent_model(model_path, max_context_len, max_new_tokens, temperature,
                          lora_model_path=None, prompt_cache_path=None, is_vlm=False):
    """Initialize the RKLLM model once and return handle + helper functions."""
    rkllm_param = RKLLMParam()
    rkllm_param.model_path = bytes(model_path, 'utf-8')
    rkllm_param.max_context_len = min(max_context_len, 4096)
    rkllm_param.max_new_tokens = max_new_tokens
    rkllm_param.skip_special_token = True
    rkllm_param.n_keep = -1
    rkllm_param.top_k = 1
    rkllm_param.top_p = 0.9
    rkllm_param.temperature = temperature
    rkllm_param.repeat_penalty = 1.1
    rkllm_param.frequency_penalty = 0.0
    rkllm_param.presence_penalty = 0.0
    rkllm_param.mirostat = 0
    rkllm_param.mirostat_tau = 5.0
    rkllm_param.mirostat_eta = 0.1
    rkllm_param.is_async = False

    if is_vlm:
        rkllm_param.img_start = "<|vision_start|>".encode('utf-8')
        rkllm_param.img_end = "<|vision_end|>".encode('utf-8')
        rkllm_param.img_content = "<|image_pad|>".encode('utf-8')
        rkllm_param.extend_param.base_domain_id = 1
    else:
        rkllm_param.img_start = "".encode('utf-8')
        rkllm_param.img_end = "".encode('utf-8')
        rkllm_param.img_content = "".encode('utf-8')
        rkllm_param.extend_param.base_domain_id = 0

    rkllm_param.extend_param.embed_flash = 1
    rkllm_param.extend_param.n_batch = 1
    rkllm_param.extend_param.use_cross_attn = 0
    rkllm_param.extend_param.enabled_cpus_num = 4
    rkllm_param.extend_param.enabled_cpus_mask = (1 << 4)|(1 << 5)|(1 << 6)|(1 << 7)

    handle = RKLLM_Handle_t()

    rkllm_init = rkllm_lib.rkllm_init
    rkllm_init.argtypes = [ctypes.POINTER(RKLLM_Handle_t), ctypes.POINTER(RKLLMParam), callback_type]
    rkllm_init.restype = ctypes.c_int

    logger.info(f"[INIT] Loading model: {model_path} (VLM={is_vlm})")
    ret = rkllm_init(ctypes.byref(handle), ctypes.byref(rkllm_param), callback)
    if ret != 0:
        logger.error(f"[CRITICAL] rkllm_init FAILED with code {ret}")
        return None
    logger.info(f"[INIT] Model loaded successfully. Handle: {handle}")

    # Setup function pointers
    rkllm_run = rkllm_lib.rkllm_run
    rkllm_run.argtypes = [RKLLM_Handle_t, ctypes.POINTER(RKLLMInput), ctypes.POINTER(RKLLMInferParam), ctypes.c_void_p]
    rkllm_run.restype = ctypes.c_int

    set_chat_template = rkllm_lib.rkllm_set_chat_template
    set_chat_template.argtypes = [RKLLM_Handle_t, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
    set_chat_template.restype = ctypes.c_int

    rkllm_destroy = rkllm_lib.rkllm_destroy
    rkllm_destroy.argtypes = [RKLLM_Handle_t]
    rkllm_destroy.restype = ctypes.c_int

    rkllm_abort = rkllm_lib.rkllm_abort

    # Setup infer params
    infer_params = RKLLMInferParam()
    ctypes.memset(ctypes.byref(infer_params), 0, ctypes.sizeof(RKLLMInferParam))
    infer_params.mode = RKLLMInferMode.RKLLM_INFER_GENERATE
    infer_params.lora_params = None
    infer_params.keep_history = 0
    infer_params.prompt_cache_params = None

    # Load LoRA if specified
    if lora_model_path and os.path.exists(lora_model_path):
        lora_adapter_name = "test"
        lora_adapter = RKLLMLoraAdapter()
        ctypes.memset(ctypes.byref(lora_adapter), 0, ctypes.sizeof(RKLLMLoraAdapter))
        lora_adapter.lora_adapter_path = ctypes.c_char_p(lora_model_path.encode('utf-8'))
        lora_adapter.lora_adapter_name = ctypes.c_char_p(lora_adapter_name.encode('utf-8'))
        lora_adapter.scale = 1.0
        rkllm_load_lora = rkllm_lib.rkllm_load_lora
        rkllm_load_lora.argtypes = [RKLLM_Handle_t, ctypes.POINTER(RKLLMLoraAdapter)]
        rkllm_load_lora.restype = ctypes.c_int
        rkllm_load_lora(handle, ctypes.byref(lora_adapter))
        rkllm_lora_params = RKLLMLoraParam()
        rkllm_lora_params.lora_adapter_name = ctypes.c_char_p(lora_adapter_name.encode('utf-8'))
        infer_params.lora_params = ctypes.pointer(rkllm_lora_params)

    return {
        "handle": handle,
        "run": rkllm_run,
        "set_chat_template": set_chat_template,
        "destroy": rkllm_destroy,
        "abort": rkllm_abort,
        "infer_params": infer_params,
    }


def run_inference(model, system_prompt_content, prompt_input):
    """Run inference on the persistent model with a given system prompt and user input."""
    handle = model["handle"]

    # Update chat template with the system prompt for this request
    sys_payload = f"<|im_start|>system\n{system_prompt_content}<|im_end|>"
    prefix = "<|im_start|>user\n"
    postfix = "<|im_end|>\n<|im_start|>assistant\n"
    model["set_chat_template"](
        handle,
        ctypes.c_char_p(sys_payload.encode('utf-8')),
        ctypes.c_char_p(prefix.encode('utf-8')),
        ctypes.c_char_p(postfix.encode('utf-8')))

    # Prepare input
    rkllm_input = RKLLMInput()
    rkllm_input.role = "user".encode('utf-8')
    rkllm_input.enable_thinking = ctypes.c_bool(False)
    rkllm_input.input_type = RKLLMInputType.RKLLM_INPUT_PROMPT
    rkllm_input.input_data.prompt_input = ctypes.c_char_p(prompt_input.encode('utf-8'))

    # Run (synchronous, blocks until done)
    ret = model["run"](handle, ctypes.byref(rkllm_input), ctypes.byref(model["infer_params"]), None)
    return ret


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--rkllm_model_path', type=str, required=True)
    parser.add_argument('--target_platform', type=str, required=True)
    parser.add_argument('--lora_model_path', type=str)
    parser.add_argument('--prompt_cache_path', type=str)
    parser.add_argument('--max_context_len', type=int, default=4096)
    parser.add_argument('--max_new_tokens', type=int, default=128)
    parser.add_argument('--temperature', type=float, default=1.0)
    args = parser.parse_args()
    SERVER_ARGS = args

    if not os.path.exists(args.rkllm_model_path):
        logger.error("Error: Please provide the correct rkllm model path.")
        sys.stdout.flush()
        exit()

    if not (args.target_platform in ["rk3588", "rk3576"]):
        logger.error("Error: Please specify the correct target platform: rk3588/rk3576.")
        sys.stdout.flush()
        exit()

    if args.lora_model_path:
        if not os.path.exists(args.lora_model_path):
            logger.error("Error: Please provide the correct lora_model path.")
            sys.stdout.flush()
            exit()

    if args.prompt_cache_path:
        cache_dir = os.path.dirname(args.prompt_cache_path)
        if cache_dir and not os.path.exists(cache_dir):
            logger.error(f"Error: Directory '{cache_dir}' does not exist.")
            sys.stdout.flush()
            exit()

    # Fix frequency
    command = "sh fix_freq_{}.sh".format(args.target_platform)
    subprocess.run(command, shell=True)

    # Set resource limit
    resource.setrlimit(resource.RLIMIT_NOFILE, (102400, 102400))

    # === Load model ONCE at startup ===
    # Auto-detect VLM: check if model path contains 'vlm' or 'vl'
    model_basename = os.path.basename(os.path.realpath(args.rkllm_model_path)).lower()
    is_vlm = 'vl' in model_basename or 'vlm' in model_basename
    logger.info(f"[INIT] Model file: {os.path.realpath(args.rkllm_model_path)}")
    logger.info(f"[INIT] Auto-detected VLM: {is_vlm}")

    PERSISTENT_MODEL = init_persistent_model(
        args.rkllm_model_path,
        args.max_context_len,
        args.max_new_tokens,
        args.temperature,
        lora_model_path=args.lora_model_path,
        prompt_cache_path=args.prompt_cache_path,
        is_vlm=is_vlm
    )
    if PERSISTENT_MODEL is None:
        logger.error("[CRITICAL] Failed to load model at startup. Exiting.")
        sys.exit(1)
    logger.info("[INIT] Persistent model ready. Server starting...")

    # === Inference endpoint (reuses persistent model) ===
    @app.route('/rkllm_diary', methods=['POST'])
    def inference_endpoint():
        global is_blocking, global_text, global_state, SERVER_ARGS, PERSISTENT_MODEL

        print("[INFERENCE LOG] /rkllm_diary hit")
        request_start = time.time()

        body = request.get_json(silent=True) or {}
        task = body.get("task")
        prompt_input = body.get("prompt")

        if not task or not prompt_input:
            return jsonify({
                'resultCode': 400,
                'message': 'Bad Request: "task" and "prompt" are required.',
                'data': None
            }), 400

        try:
            system_prompt_content = _load_system_prompt_from_disk(task)
        except Exception as e:
            return jsonify({
                'resultCode': 500,
                'message': f'Server Error: Could not load system prompt. {str(e)}',
                'data': None
            }), 500

        request_start_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(request_start))
        print(f"[INFERENCE LOG] Request received at {request_start_str}")

        lock.acquire()

        try:
            logger.info(f"[INFERENCE LOG] Using persistent model: {SERVER_ARGS.rkllm_model_path}")
            if is_blocking:
                print(f"[INFERENCE LOG] Busy: is_blocking={is_blocking}")
                return jsonify({
                    'resultCode': 503,
                    'message': 'RKLLM_Server is busy! Maybe you can try again later.',
                    'data': None
                }, 503)

            is_blocking = True

            print(f"[INFERENCE LOG] Task: {task}")
            print(f"[INFERENCE LOG] System Prompt: {system_prompt_content[:100]}...")
            print(f"[INFERENCE LOG] Prompt Input:\n{prompt_input[:200]}...")

            global_text = []
            global_state = -1

            model_output = ""

            # Run inference in a thread (synchronous rkllm_run, but threaded for output collection)
            model_thread = threading.Thread(
                target=run_inference,
                args=(PERSISTENT_MODEL, system_prompt_content, prompt_input)
            )
            model_thread.start()

            model_thread_finished = False
            while not model_thread_finished:
                while len(global_text) > 0:
                    model_output += global_text.pop(0)
                    time.sleep(0.005)

                model_thread.join(timeout=0.005)
                model_thread_finished = not model_thread.is_alive()

            model_output = model_output.strip()
            model_output = re.sub(r'<think>.*?</think>', '', model_output, flags=re.DOTALL).strip()

            print(f"[INFERENCE LOG] Model raw output: {model_output}")

            return Response(model_output, status=200, mimetype="text/plain")

        except Exception as e:
            print(f"[SERVER ERROR] {str(e)}")
            return jsonify({
                'resultCode': 500,
                'message': f'Server error: {str(e)}',
                'data': None
            }), 500
        finally:
            request_end = time.time()
            duration = request_end - request_start
            print(f"[INFERENCE LOG] Request ended, duration: {duration:.3f} seconds")
            print(88 * "=")
            lock.release()
            is_blocking = False

    # === VLM endpoint (uses C++ demo binary for image+text) ===
    VLM_DEMO = "/data/rknn-llm/examples/multimodal_model_demo/deploy/install/demo_Linux_aarch64/demo"
    VLM_VISION = "/data/ai_brain/vlm/qwen3-vl-2b_vision_rk3576.rknn"
    VLM_LLM = "/data/ai_brain/vlm/qwen3-vl-2b-instruct_w4a16_g128_rk3576.rkllm"

    @app.route("/rkllm_vlm", methods=["POST"])
    def vlm_endpoint():
        """VLM inference via C++ demo binary. Accepts image + text prompt."""
        import base64 as b64mod
        body = request.get_json(silent=True) or {}
        vlm_prompt = body.get("prompt", "").strip()
        image_b64 = body.get("image_base64", "")
        image_path = body.get("image_path", "")
        max_new_tokens = body.get("max_new_tokens", 512)

        if not vlm_prompt:
            return "prompt is required", 400

        img_file = "/tmp/vlm_input.jpg"
        if image_b64:
            with open(img_file, "wb") as f:
                f.write(b64mod.b64decode(image_b64))
        elif image_path:
            img_file = image_path
        else:
            return "image_base64 or image_path is required", 400

        if not os.path.exists(VLM_DEMO):
            return f"VLM demo binary not found: {VLM_DEMO}", 500

        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = os.path.dirname(VLM_DEMO) + "/lib:" + env.get("LD_LIBRARY_PATH", "")

        try:
            proc = subprocess.Popen(
                [VLM_DEMO, img_file, VLM_VISION, VLM_LLM,
                 str(max_new_tokens), "4096", "2",
                 "<|vision_start|>", "<|vision_end|>", "<|image_pad|>"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, cwd=os.path.dirname(VLM_DEMO))
            stdin_data = vlm_prompt + "\nexit\n"
            stdout, stderr = proc.communicate(input=stdin_data.encode(), timeout=180)
            output = stdout.decode("utf-8", errors="replace")
            lines = output.split("\n")
            result_lines = []
            capture = False
            for line in lines:
                if line.startswith("robot:"):
                    capture = True
                    result_lines.append(line[len("robot:"):].strip())
                elif capture:
                    if line.startswith("user:") or line.strip() == "exit":
                        break
                    result_lines.append(line)
            result_text = "\n".join(result_lines).strip()
            if not result_text:
                result_text = output
            logger.info(f"[VLM] Result: {result_text[:200]}")
            return Response(result_text, status=200, mimetype="text/plain")
        except subprocess.TimeoutExpired:
            proc.kill()
            return "VLM inference timeout", 504
        except Exception as e:
            logger.error(f"[VLM] Error: {e}")
            return f"VLM error: {e}", 500

    app.run(host='0.0.0.0', port=8082, threaded=True, debug=False)
    print("====== FLASK SERVER DIARY ======")
