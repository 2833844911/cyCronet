#!/usr/bin/env python3
"""Verify WSS headers: check if custom headers are applied and Pragma/Cache-Control are gone."""
import sys
import time
import cycronet

PROXY = "http://host.docker.internal:9000"
WSS_URL = "wss://ws.postman-echo.com/raw"

print(f"Python: {sys.version}")
print()

# Test 1: No custom headers - should NOT have Pragma/Cache-Control
print("=== Test 1: No headers (check Pragma/Cache-Control removed) ===")
result1 = {"done": False}

def on_open1(ws):
    print("  [open] connected (no custom headers)")
    ws.send("test1")

def on_message1(ws, data, is_text):
    print(f"  [msg] {data}")
    result1["done"] = True
    ws.close()

def on_close1(ws, code, reason, was_clean):
    print(f"  [close] code={code}")

def on_error1(ws, msg, err):
    print(f"  [error] {msg}")

session1 = cycronet.CronetClient(verify=False, proxies={"https": PROXY})
ws1 = session1.websocket(WSS_URL, on_open=on_open1, on_message=on_message1,
                          on_close=on_close1, on_error=on_error1)
ws1.run_in_background()
ws1.wait(timeout=15)
session1.close()
print(f"  >> Check proxy log: should NOT have Pragma/Cache-Control")
print()

time.sleep(1)

# Test 2: With custom headers - should have User-Agent and Accept-Language
print("=== Test 2: With custom headers ===")
result2 = {"done": False}

CUSTOM_HEADERS = [
    ("User-Agent", "CycronetDockerTest/1.0 Linux-ARM64"),
    ("Accept-Language", "zh-CN,zh;q=0.9"),
    ("Accept-Encoding", "gzip, deflate, br, zstd"),
]

def on_open2(ws):
    print("  [open] connected (with custom headers)")
    ws.send("test2")

def on_message2(ws, data, is_text):
    print(f"  [msg] {data}")
    result2["done"] = True
    ws.close()

def on_close2(ws, code, reason, was_clean):
    print(f"  [close] code={code}")

def on_error2(ws, msg, err):
    print(f"  [error] {msg}")

session2 = cycronet.CronetClient(verify=False, proxies={"https": PROXY})
ws2 = session2.websocket(WSS_URL, headers=CUSTOM_HEADERS,
                          on_open=on_open2, on_message=on_message2,
                          on_close=on_close2, on_error=on_error2)
ws2.run_in_background()
ws2.wait(timeout=15)
session2.close()
print(f"  >> Check proxy log: should have User-Agent=CycronetDockerTest/1.0 Linux-ARM64")
print(f"  >> Check proxy log: should have Accept-Language=zh-CN,zh;q=0.9")
print()

print("DONE - check proxy logs on Mac host to verify headers")
