"""İzolasyon testleri için "kötü niyetli" sahte MCP sunucusu (yalnız stdlib).

Konteynerin içinde `python -c <kaynak>` ile çalışır. Araçlar bir saldırganın yapacağı şeyleri dener:
ana makine dosyası okuma, ortam sırlarını görme, ağa çıkma, kök dosya sistemine yazma, süreç bırakma.
"""

SRC = r"""
import json, os, socket, subprocess, sys, time

TOOLS = [
    {"name": n, "description": d, "inputSchema": {"type": "object"}}
    for n, d in [
        ("echo", "yankı"), ("read_file", "dosya oku"), ("list_dir", "dizin listele"),
        ("write_file", "dosya yaz"), ("env_dump", "ortam"), ("identity", "kimlik"),
        ("connect", "ağ"), ("exists", "var mı"), ("spawn", "arka plan süreci"), ("hang", "asılı"),
    ]
]

def send(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()

def call(name, a):
    if name == "echo":
        return a.get("text", "")
    if name == "read_file":
        with open(a["path"], "rb") as f:
            return f.read(4096).decode(errors="replace")
    if name == "list_dir":
        return "\n".join(sorted(os.listdir(a["path"])))
    if name == "write_file":
        with open(a["path"], "w") as f:
            f.write(a.get("text", "x"))
        return "yazıldı"
    if name == "env_dump":
        return json.dumps(dict(os.environ))
    if name == "identity":
        cap = [l for l in open("/proc/self/status") if l.startswith("CapEff")][0].split()[1]
        return json.dumps({"uid": os.getuid(), "capeff": cap, "home": os.environ.get("HOME"), "cwd": os.getcwd()})
    if name == "connect":
        s = socket.create_connection((a["host"], int(a["port"])), timeout=3)
        s.close()
        return "bağlandı"
    if name == "exists":
        return str(os.path.exists(a["path"]))
    if name == "spawn":
        p = subprocess.Popen(["sleep", "300"], start_new_session=True)
        return str(p.pid)
    if name == "hang":
        time.sleep(600)
    raise RuntimeError("bilinmeyen araç")

for line in sys.stdin:
    try:
        m = json.loads(line)
    except ValueError:
        continue
    method, mid = m.get("method"), m.get("id")
    if mid is None or method is None:
        continue
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "probe", "version": "1"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        p = m["params"]
        try:
            out = call(p["name"], p.get("arguments") or {})
            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": out}]}})
        except Exception as e:
            send({"jsonrpc": "2.0", "id": mid, "result": {"isError": True, "content": [{"type": "text", "text": "%s: %s" % (type(e).__name__, e)}]}})
"""
