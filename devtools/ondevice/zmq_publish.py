"""
ZMQ publish script — デバイス上の /data/pylib/zmq_publish.py に配置
ADB経由で python3 /data/pylib/zmq_publish.py <topic_json> で実行

ctypes + libzmq.so.5 を直接使用 (pyzmq不要)
masterプロキシの port 5558 に PUB ソケットで connect
"""
import ctypes
import json
import struct
import sys
import time

zmq = ctypes.CDLL("libzmq.so.5")

ZMQ_PUB = 1
ZMQ_SNDMORE = 2

zmq.zmq_ctx_new.restype = ctypes.c_void_p
zmq.zmq_socket.restype = ctypes.c_void_p
zmq.zmq_socket.argtypes = [ctypes.c_void_p, ctypes.c_int]
zmq.zmq_connect.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
zmq.zmq_send.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
zmq.zmq_send.restype = ctypes.c_int
zmq.zmq_close.argtypes = [ctypes.c_void_p]
zmq.zmq_ctx_destroy.argtypes = [ctypes.c_void_p]


def msgpack_str(s: str) -> bytes:
    data = s.encode("utf-8")
    length = len(data)
    if length <= 31:
        return bytes([0xA0 | length]) + data
    elif length <= 255:
        return bytes([0xD9, length]) + data
    else:
        return struct.pack(">BH", 0xDA, length) + data


def publish(topic: str, payload_json: str):
    ctx = zmq.zmq_ctx_new()
    sock = zmq.zmq_socket(ctx, ZMQ_PUB)
    zmq.zmq_connect(sock, b"tcp://127.0.0.1:5558")
    time.sleep(1.0)

    topic_bytes = ("#" + topic).encode()
    payload_bytes = msgpack_str(payload_json)

    rc1 = zmq.zmq_send(sock, topic_bytes, len(topic_bytes), ZMQ_SNDMORE)
    rc2 = zmq.zmq_send(sock, payload_bytes, len(payload_bytes), 0)

    time.sleep(0.5)
    zmq.zmq_close(sock)
    zmq.zmq_ctx_destroy(ctx)
    print(json.dumps({"ok": True, "topic_rc": rc1, "payload_rc": rc2}))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python3 zmq_publish.py \'{"topic":"/agent/start_cc_task","payload":{...}}\'')
        sys.exit(1)

    msg = json.loads(sys.argv[1])
    topic = msg.get("topic", "/agent/start_cc_task")
    payload = msg.get("payload", {})
    publish(topic, json.dumps(payload, separators=(",", ":")))
