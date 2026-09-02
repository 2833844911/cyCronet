#!/usr/bin/env python3
"""
Comprehensive WS/WSS test for cycronet.
Requires local echo server: python3 /Volumes/D/myxm/test_me/wss_echo_server.py
  WS  on ws://127.0.0.1:19876
  WSS on wss://127.0.0.1:19877
"""
import sys
import time
import threading

import cycronet
from cycronet.cronet_cloak import PyCronetClient

PASS = 0
FAIL = 0

WS_URL  = "ws://127.0.0.1:19876"
WSS_URL = "wss://ws.postman-echo.com/raw"

def test(name, func):
    global PASS, FAIL
    try:
        func()
        PASS += 1
        print(f"  [PASS] {name}")
    except Exception as e:
        FAIL += 1
        print(f"  [FAIL] {name}: {e}")

native = PyCronetClient()

# ============================================================
# 1. WS (plain) low-level tests
# ============================================================
print("=== 1. WS Low-Level (plain WebSocket) ===")

def test_ws_text_echo():
    sid = native.create_session(None, True, 30000, None, None, None)
    ws = None
    try:
        ws = native.websocket_connect(sid, WS_URL)
        evt = ws.recv_timeout(5000)
        assert evt and evt["type"] == "open", f"Expected open, got {evt}"
        ws.send("hello cycronet")
        evt = ws.recv_timeout(5000)
        assert evt and evt["type"] == "message", f"Expected message, got {evt}"
        assert evt["data"] == "hello cycronet", f"Expected echo, got {evt['data']}"
        ws.close()
        evt = ws.recv_timeout(3000)
    finally:
        if ws:
            ws.destroy()
            time.sleep(0.2)
        native.close_session(sid)

test("WS text echo", test_ws_text_echo)

def test_ws_binary_echo():
    sid = native.create_session(None, True, 30000, None, None, None)
    ws = None
    try:
        ws = native.websocket_connect(sid, WS_URL)
        evt = ws.recv_timeout(5000)
        assert evt and evt["type"] == "open"
        data = bytes(range(256))
        ws.send_bytes(data)
        evt = ws.recv_timeout(5000)
        assert evt and evt["type"] == "message", f"Expected message, got {evt}"
        assert bytes(evt["data"]) == data, "Binary data mismatch"
        ws.close()
        evt = ws.recv_timeout(3000)
    finally:
        if ws:
            ws.destroy()
            time.sleep(0.2)
        native.close_session(sid)

test("WS binary echo", test_ws_binary_echo)

def test_ws_rapid_messages():
    sid = native.create_session(None, True, 30000, None, None, None)
    ws = None
    try:
        ws = native.websocket_connect(sid, WS_URL)
        evt = ws.recv_timeout(5000)
        assert evt and evt["type"] == "open"
        msgs = [f"rapid-{i}" for i in range(5)]
        for m in msgs:
            ws.send(m)
        received = []
        for _ in range(5):
            evt = ws.recv_timeout(5000)
            assert evt and evt["type"] == "message"
            received.append(evt["data"])
        assert received == msgs, f"Mismatch: {received} != {msgs}"
        ws.close()
        evt = ws.recv_timeout(3000)
    finally:
        if ws:
            ws.destroy()
            time.sleep(0.2)
        native.close_session(sid)

test("WS rapid x5 messages", test_ws_rapid_messages)

def test_ws_clean_close():
    sid = native.create_session(None, True, 30000, None, None, None)
    ws = None
    try:
        ws = native.websocket_connect(sid, WS_URL)
        evt = ws.recv_timeout(5000)
        assert evt and evt["type"] == "open"
        ws.close(1000, "bye")
        evt = ws.recv_timeout(5000)
        assert evt and evt["type"] == "close", f"Expected close, got {evt}"
    finally:
        if ws:
            ws.destroy()
            time.sleep(0.2)
        native.close_session(sid)

test("WS clean close", test_ws_clean_close)

# ============================================================
# 2. WSS (TLS) low-level tests
# ============================================================
print("\n=== 2. WSS Low-Level (TLS WebSocket) ===")

def test_wss_text_echo():
    sid = native.create_session(None, True, 30000, None, None, None)
    ws = None
    try:
        ws = native.websocket_connect(sid, WSS_URL)
        evt = ws.recv_timeout(5000)
        assert evt and evt["type"] == "open", f"Expected open, got {evt}"
        ws.send("hello wss")
        evt = ws.recv_timeout(5000)
        assert evt and evt["type"] == "message", f"Expected message, got {evt}"
        assert evt["data"] == "hello wss", f"Expected echo, got {evt['data']}"
        ws.close()
        evt = ws.recv_timeout(3000)
    finally:
        if ws:
            ws.destroy()
            time.sleep(0.2)
        native.close_session(sid)

test("WSS text echo", test_wss_text_echo)

# WSS binary echo skipped: Postman echo server does not support binary frames.
# Binary echo is fully tested via local WS server in section 1 above.

def test_wss_rapid_messages():
    sid = native.create_session(None, True, 30000, None, None, None)
    ws = None
    try:
        ws = native.websocket_connect(sid, WSS_URL)
        evt = ws.recv_timeout(5000)
        assert evt and evt["type"] == "open"
        msgs = [f"wss-rapid-{i}" for i in range(5)]
        for m in msgs:
            ws.send(m)
        received = []
        for _ in range(5):
            evt = ws.recv_timeout(5000)
            assert evt and evt["type"] == "message"
            received.append(evt["data"])
        assert received == msgs, f"Mismatch: {received} != {msgs}"
        ws.close()
        evt = ws.recv_timeout(3000)
    finally:
        if ws:
            ws.destroy()
            time.sleep(0.2)
        native.close_session(sid)

test("WSS rapid x5 messages", test_wss_rapid_messages)

def test_wss_clean_close():
    sid = native.create_session(None, True, 30000, None, None, None)
    ws = None
    try:
        ws = native.websocket_connect(sid, WSS_URL)
        evt = ws.recv_timeout(5000)
        assert evt and evt["type"] == "open"
        ws.close(1000, "bye")
        evt = ws.recv_timeout(5000)
        assert evt and evt["type"] == "close", f"Expected close, got {evt}"
    finally:
        if ws:
            ws.destroy()
            time.sleep(0.2)
        native.close_session(sid)

test("WSS clean close", test_wss_clean_close)

# ============================================================
# 3. WebSocketApp (high-level) via WS
# ============================================================
print("\n=== 3. WebSocketApp (high-level) ===")

def test_websocketapp_echo():
    session = cycronet.CronetClient(verify=False)
    results = {"open": False, "messages": [], "closed": False, "error": None}
    done = threading.Event()

    def on_open(ws):
        results["open"] = True
        ws.send("wsapp-hello")

    def on_message(ws, msg, is_text):
        results["messages"].append(msg)
        ws.close()

    def on_close(ws, code, reason, was_clean):
        results["closed"] = True
        done.set()

    def on_error(ws, error, net_error):
        results["error"] = error
        done.set()

    try:
        wsapp = cycronet.WebSocketApp(
            session, WS_URL,
            on_open=on_open,
            on_message=on_message,
            on_close=on_close,
            on_error=on_error,
        )
        wsapp.run_in_background()
        done.wait(timeout=10)
        assert results["open"], "on_open not called"
        assert results["messages"] == ["wsapp-hello"], f"Got: {results['messages']}"
        assert results["closed"], "on_close not called"
        assert results["error"] is None, f"Error: {results['error']}"
    finally:
        session.close()

test("WebSocketApp echo + close", test_websocketapp_echo)

def test_websocketapp_multiple():
    session = cycronet.CronetClient(verify=False)
    results = {"messages": [], "closed": False}
    done = threading.Event()
    count = 3

    def on_open(ws):
        for i in range(count):
            ws.send(f"multi-{i}")

    def on_message(ws, msg, is_text):
        results["messages"].append(msg)
        if len(results["messages"]) == count:
            ws.close()

    def on_close(ws, code, reason, was_clean):
        results["closed"] = True
        done.set()

    try:
        wsapp = cycronet.WebSocketApp(
            session, WS_URL,
            on_open=on_open,
            on_message=on_message,
            on_close=on_close,
        )
        wsapp.run_in_background()
        done.wait(timeout=15)
        expected = [f"multi-{i}" for i in range(count)]
        assert results["messages"] == expected, f"Got: {results['messages']}"
        assert results["closed"]
    finally:
        session.close()

test("WebSocketApp multiple messages", test_websocketapp_multiple)

# ============================================================
# 4. Session lifecycle safety
# ============================================================
print("\n=== 4. Session lifecycle safety ===")

def test_session_create_destroy_rapid():
    for i in range(10):
        sid = native.create_session(None, True, 30000, None, None, None)
        native.close_session(sid)

test("Rapid session create/destroy x10", test_session_create_destroy_rapid)

# ============================================================
# Summary
# ============================================================
print(f"\n{'='*40}")
print(f"Results: {PASS} passed, {FAIL} failed")
if FAIL > 0:
    sys.exit(1)
else:
    print("All tests passed!")
