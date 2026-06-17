# DureClaw bridge — collaborate as a fleet

This makes **PicoClaw** a member of a [DureClaw](https://github.com/DureClaw/dureclaw)
collaboration fleet. A master can **fan-out** a task to many PicoClaw instances (and
other agents) over one Phoenix-Channel bus, then **fan-in** the results — *distributed
brains, human decisions*.

## How it works

```
DureClaw bus ──task.assign──▶ dureclaw_bridge.py ──runs──▶ `picoclaw agent -m {}` ──stdout──▶ task.result
```

The bridge is pure-Python stdlib (no deps) — it joins the bus, listens for tasks
addressed to this agent (or broadcast), runs the local CLI on the instruction, and
pushes the answer back.

## Run

```bash
STATE_SERVER=<bus-host:4000> OAH_SECRET=<token> WORK_KEY=<WK> \
  AGENT_NAME=picoclaw@$(hostname) ./dureclaw/run.sh
```

| Env | Meaning |
|-----|---------|
| `STATE_SERVER` | DureClaw bus `host:port` |
| `OAH_SECRET` | bus bearer token |
| `WORK_KEY` | collaboration session key |
| `AGENT_NAME` / `AGENT_ROLE` / `CAPABILITIES` | how this node appears in the fleet |
| `AGENT_CMD` | command template; `{}` ← instruction (default: `picoclaw agent -m {}`) |

> Keyless edges, master absorbs LLM cost, approved decisions compiled into rules.
