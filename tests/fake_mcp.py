"""Testler için sahte MCP sunucusu (stdio, satır başına bir JSON). Kip: argv[1]."""

import json
import os
import subprocess
import sys
import time

MODE = sys.argv[1] if len(sys.argv) > 1 else "normal"
saw_reply = []


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


TOOLS = [
    {
        "name": "echo",
        "description": "Yankılar.",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
    {"name": "fail", "description": "Hata verir.", "inputSchema": {"type": "object"}},
    {"name": "big", "description": "x" * 5000, "inputSchema": {"type": "object"}},
    {"name": "slow", "description": "Yavaş.", "inputSchema": {"type": "object"}},
    {"name": "env", "description": "Ortam.", "inputSchema": {"type": "object"}},
    {"name": "die", "description": "Çöker.", "inputSchema": {"type": "object"}},
    {"name": "child", "description": "Alt süreç.", "inputSchema": {"type": "object"}},
    {"name": "probe", "description": "Sunucu isteği.", "inputSchema": {"type": "object"}},
    {"name": "mixed", "description": "Karışık.", "inputSchema": {"type": "object"}},
]

if MODE == "hang":
    time.sleep(600)
if MODE == "exit":
    sys.stderr.write("sır-olmayan hata: eksik bağımlılık\n")
    sys.exit(3)

for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    method, mid = msg.get("method"), msg.get("id")
    if method is None:  # istemcinin bizim isteğimize yanıtı
        saw_reply.append(msg)
        continue
    if mid is None:
        continue  # bildirim
    if method == "initialize":
        sys.stdout.write("karışık, JSON olmayan günlük satırı\n")
        send(
            {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake", "version": "1"},
                },
            }
        )
    elif method == "tools/list":
        cursor = (msg.get("params") or {}).get("cursor")
        if MODE == "paged" and cursor is None:
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS[:2], "nextCursor": "p2"}})
        elif MODE == "paged":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS[2:3]}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        p = msg["params"]
        name, args = p["name"], p.get("arguments") or {}
        text, err = "", False
        if name == "echo":
            text = args.get("text", "")
        elif name == "fail":
            text, err = "bir şey ters gitti", True
        elif name == "big":
            text = "b" * 200_000
        elif name == "slow":
            time.sleep(30)
        elif name == "env":
            text = ",".join(sorted(os.environ))
        elif name == "die":
            os._exit(9)
        elif name == "child":
            c = subprocess.Popen(["sleep", "600"])
            text = str(c.pid)
        elif name == "probe":
            send({"jsonrpc": "2.0", "id": 900, "method": "sampling/createMessage", "params": {}})
            send({"jsonrpc": "2.0", "id": 901, "method": "ping"})
            for _ in range(2):  # istemcinin iki yanıtını doğrudan oku
                saw_reply.append(json.loads(sys.stdin.readline()))
            text = json.dumps(saw_reply)
        elif name == "mixed":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "content": [
                            {"type": "text", "text": "metin1"},
                            {"type": "image", "data": "AAAA", "mimeType": "image/png"},
                            {
                                "type": "resource",
                                "resource": {"uri": "file:///etc/passwd", "text": "gizli"},
                            },
                            {"type": "text", "text": "metin2"},
                        ]
                    },
                }
            )
            continue
        send(
            {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"content": [{"type": "text", "text": text}], "isError": err},
            }
        )
    else:
        send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "yok"}})
