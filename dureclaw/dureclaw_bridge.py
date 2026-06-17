#!/usr/bin/env python3
"""
DureClaw bridge — join any CLI agent to the DureClaw collaboration bus.

DureClaw (https://github.com/DureClaw/dureclaw) is a Phoenix-Channel bus that
turns scattered machines into one collaborating AI crew. This bridge registers
THIS agent on the bus (presence), listens for `task.assign`, runs your local
agent CLI on the instruction, and pushes the answer back as `task.result`.

So your fork (nanobot / picoclaw / anything with a one-shot CLI) becomes a
DureClaw fleet member: a master can fan-out a task to many of these and fan-in
the results — "distributed brains, human decisions".

Pure Python stdlib (no deps) — runs anywhere, including tiny Linux devices.

Env:
  STATE_SERVER   bus host:port (e.g. 100.108.196.12:4000)   [required]
  OAH_SECRET     bus bearer token                           [required]
  WORK_KEY       collaboration session key (default WK-demo)
  AGENT_NAME     unique fleet name (default <cmd>@<host>)
  AGENT_ROLE     builder | executor | analyst | ...          (default builder)
  AGENT_MACHINE  machine label                               (default hostname)
  CAPABILITIES   comma list                                  (default agent,cli)
  AGENT_CMD      command template; "{}" is replaced by the instruction as a
                 single argv item (no shell). e.g.:
                   picoclaw: "picoclaw agent -m {}"
                   nanobot:  "nanobot run {}"
  TASK_TIMEOUT   seconds per task (default 180)
"""
import base64
import json
import os
import shlex
import socket
import struct
import subprocess
import threading
import time

HP = os.environ.get("STATE_SERVER", "127.0.0.1:4000").replace("ws://", "").replace("http://", "")
HOST, PORT = HP.split(":")
PORT = int(PORT)
TOKEN = os.environ.get("OAH_SECRET", "")
WK = os.environ.get("WORK_KEY", "WK-demo")
ROLE = os.environ.get("AGENT_ROLE", "builder")
MACHINE = os.environ.get("AGENT_MACHINE", socket.gethostname())
CMD_TMPL = os.environ.get("AGENT_CMD", "echo {}")
TIMEOUT = int(os.environ.get("TASK_TIMEOUT", "180"))
CAPS = [c.strip() for c in os.environ.get("CAPABILITIES", "agent,cli").split(",") if c.strip()]
NAME = os.environ.get("AGENT_NAME", f"{shlex.split(CMD_TMPL)[0]}@{MACHINE}")

sock = None
ref = [0]
joinref = [None]
lock = threading.Lock()


def nref():
    ref[0] += 1
    return str(ref[0])


# ── WebSocket (Phoenix v2.0.0) ──────────────────────────────────────────────
def connect():
    global sock
    s = socket.create_connection((HOST, PORT), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    path = "/socket/websocket?vsn=2.0.0" + (("&token=" + TOKEN) if TOKEN else "")
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(1024)
        if not chunk:
            raise Exception("closed during handshake")
        buf += chunk
    if b"101" not in buf.split(b"\r\n")[0]:
        raise Exception("WS upgrade failed: " + buf[:80].decode(errors="replace"))
    sock = s
    print(f"[dureclaw] WebSocket connected to {HOST}:{PORT}")


def send_frame(text):
    payload = text.encode()
    n = len(payload)
    hdr = bytearray([0x81])
    mask = os.urandom(4)
    if n < 126:
        hdr.append(0x80 | n)
    elif n < 65536:
        hdr.append(0x80 | 126)
        hdr += struct.pack(">H", n)
    else:
        hdr.append(0x80 | 127)
        hdr += struct.pack(">Q", n)
    hdr += mask
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    with lock:
        sock.sendall(bytes(hdr) + masked)


def _recvn(n):
    d = b""
    while len(d) < n:
        c = sock.recv(n - len(d))
        if not c:
            raise Exception("closed")
        d += c
    return d


def recv_frame():
    b1 = _recvn(1)[0]
    b2 = _recvn(1)[0]
    ln = b2 & 0x7f
    if ln == 126:
        ln = struct.unpack(">H", _recvn(2))[0]
    elif ln == 127:
        ln = struct.unpack(">Q", _recvn(8))[0]
    data = _recvn(ln) if ln else b""
    op = b1 & 0x0f
    if op == 8:
        return None
    if op in (9, 10):
        return ""
    return data.decode(errors="replace")


def push(event, payload):
    send_frame(json.dumps([joinref[0], nref(), "work:" + WK, event, payload]))


def join():
    joinref[0] = nref()
    send_frame(json.dumps([joinref[0], joinref[0], "work:" + WK, "phx_join", {
        "agent_name": NAME, "role": ROLE, "machine": MACHINE,
        "capabilities": CAPS, "preferred_model": "cli-bridge", "version": "dureclaw-bridge/1.0"}]))
    print(f"[dureclaw] joined work:{WK} as {NAME} (role={ROLE}, caps={CAPS})")


def heartbeat():
    while True:
        time.sleep(15)
        try:
            send_frame(json.dumps([None, nref(), "phoenix", "heartbeat", {}]))
        except Exception:
            return


# ── Task execution: run the local agent CLI ─────────────────────────────────
def run_agent(instruction):
    argv = [instruction if tok in ("{}", "{prompt}") else tok
            for tok in shlex.split(CMD_TMPL)]
    if not any(t in ("{}", "{prompt}") for t in shlex.split(CMD_TMPL)):
        argv = argv + [instruction]  # no placeholder → append as last arg
    p = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT)
    out = (p.stdout or "").strip() or (p.stderr or "").strip()
    return out, p.returncode


def handle(p):
    tid = p.get("task_id", "")
    instr = p.get("instructions", "")
    frm = p.get("from", "http@controller")
    if not instr.strip():
        return
    print(f"[dureclaw] task {tid}: {instr[:80]}")
    try:
        out, rc = run_agent(instr)
        push("task.result", {"task_id": tid, "to": frm, "from": NAME,
                             "status": "done" if rc == 0 else "blocked",
                             "output": out[:1800], "exit_code": rc, "backend": "dureclaw-bridge"})
        print(f"[dureclaw] result {tid}: rc={rc} ({len(out)} chars)")
    except subprocess.TimeoutExpired:
        push("task.result", {"task_id": tid, "to": frm, "from": NAME,
                             "status": "blocked", "output": f"timeout ({TIMEOUT}s)", "exit_code": 124})
    except Exception as e:
        push("task.result", {"task_id": tid, "to": frm, "from": NAME,
                             "status": "blocked", "output": str(e), "exit_code": 1})


def main():
    if not TOKEN:
        print("[dureclaw] warning: OAH_SECRET not set")
    while True:
        try:
            connect()
            join()
            threading.Thread(target=heartbeat, daemon=True).start()
            while True:
                msg = recv_frame()
                if msg is None:
                    break
                if not msg:
                    continue
                try:
                    _, _, _topic, event, p = json.loads(msg)
                except Exception:
                    continue
                if event == "task.assign":
                    to = p.get("to")
                    if not to or to == NAME or to == "broadcast":
                        threading.Thread(target=handle, args=(p,), daemon=True).start()
        except Exception as e:
            print("[dureclaw] error:", e, "— reconnecting in 3s")
            time.sleep(3)


if __name__ == "__main__":
    main()
