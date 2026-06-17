#!/usr/bin/env bash
# Join this PicoClaw to a DureClaw fleet (https://github.com/DureClaw/dureclaw).
# It registers on the bus and answers task.assign by running: picoclaw agent -m {}
export STATE_SERVER="${STATE_SERVER:-127.0.0.1:4000}"
export OAH_SECRET="${OAH_SECRET:-change-me}"
export WORK_KEY="${WORK_KEY:-WK-demo}"
export AGENT_NAME="${AGENT_NAME:-picoclaw@$(hostname)}"
export AGENT_ROLE="${AGENT_ROLE:-executor}"
export CAPABILITIES="${CAPABILITIES:-agent,cli,picoclaw,edge,go}"
export AGENT_CMD="${AGENT_CMD:-picoclaw agent -m {}}"
exec python3 "$(dirname "$0")/dureclaw_bridge.py"
