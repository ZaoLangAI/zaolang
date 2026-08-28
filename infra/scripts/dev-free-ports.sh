#!/usr/bin/env bash
# Reap leftover listeners on local-dev HTTP ports.
#
# `make dev` backgrounds conda/Next/Celery trees. Ctrl+C plus `kill 0` only
# signals the recipe's process group; uvicorn --reload and next-server often
# sit in another group and keep 3000/3001 bound. This script walks from each
# LISTEN pid to the nearest supervisor (make / a login shell / the IDE) and
# stops that subtree so the reloader cannot immediately rebind the port.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

usage() {
  cat <<'EOF'
用法: dev-free-ports.sh [--dry-run] [--celery] [端口 ...]

默认释放 3000（Next.js）与 3001（FastAPI）。
--celery  同时结束后端目录里残留的 Celery worker / beat
--dry-run 只打印将要停止的进程，不发信号
EOF
}

DRY_RUN=0
FREE_CELERY=0
PORTS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --celery) FREE_CELERY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; PORTS+=("$@"); break ;;
    -*)
      echo "未知参数: $1" >&2
      usage >&2
      exit 2
      ;;
    *) PORTS+=("$1"); shift ;;
  esac
done

if [[ ${#PORTS[@]} -eq 0 ]]; then
  PORTS=(3000 3001)
fi

# Never signal the caller or its parents — a new `make dev` invokes this
# before binding, and the Ctrl+C trap invokes it from the same tree.
protected_pids() {
  local pid=$$
  while [[ -n "$pid" && "$pid" != 0 && "$pid" != 1 ]]; do
    printf '%s\n' "$pid"
    pid="$(ps -p "$pid" -o ppid= 2>/dev/null | tr -d ' ' || true)"
  done
}

is_supervisor() {
  local comm="$1"
  case "$comm" in
    launchd|init|make|gmake|login|zsh|bash|sh|fish|dash|tmux|screen|sshd|Cursor|Code|Electron|Terminal|iTerm2|iTerm)
      return 0
      ;;
  esac
  return 1
}

proc_field() {
  local pid="$1" field="$2"
  ps -p "$pid" -o "$field"= 2>/dev/null | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true
}

is_protected() {
  local pid="$1"
  grep -qx "$pid" <<<"$PROTECTED"
}

# Highest ancestor that is still "our" server stack, not a supervisor.
kill_root_of() {
  local pid="$1" target="$1" parent comm
  while true; do
    parent="$(proc_field "$pid" ppid)"
    [[ -z "$parent" || "$parent" == 0 || "$parent" == 1 ]] && break
    if is_protected "$parent"; then
      break
    fi
    comm="$(proc_field "$parent" comm)"
    comm="${comm##*/}"
    if is_supervisor "$comm"; then
      break
    fi
    target="$parent"
    pid="$parent"
  done
  printf '%s\n' "$target"
}

collect_listen_pids() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | sort -u || true
}

collect_celery_pids() {
  local pid cwd
  ps -ax -o pid= -o command= | awk '/celery -A app.workers.celery_app/ && !/awk/ {print $1}' | while read -r pid; do
    [[ -z "$pid" ]] && continue
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | awk '/^n/ {print substr($0,2); exit}')"
    if [[ -n "$cwd" && "$cwd" == "$ROOT"/* ]]; then
      printf '%s\n' "$pid"
    fi
  done
}

uniq_ints() {
  awk 'NF && $1 ~ /^[0-9]+$/ {print $1}' | sort -u
}

PROTECTED="$(protected_pids | uniq_ints)"
TARGETS=""

consider_pid() {
  local pid="$1" root
  [[ -z "$pid" ]] && return 0
  if is_protected "$pid"; then
    return 0
  fi
  root="$(kill_root_of "$pid")"
  if is_protected "$root"; then
    return 0
  fi
  TARGETS="${TARGETS}
${root}"
}

describe() {
  local pid="$1"
  local args
  args="$(proc_field "$pid" args)"
  printf '  pid %s  %s\n' "$pid" "$args"
}

for port in "${PORTS[@]}"; do
  if ! [[ "$port" =~ ^[0-9]+$ ]]; then
    echo "非法端口: $port" >&2
    exit 2
  fi
  while read -r pid; do
    consider_pid "$pid"
  done < <(collect_listen_pids "$port")
done

if [[ "$FREE_CELERY" == 1 ]]; then
  while read -r pid; do
    consider_pid "$pid"
  done < <(collect_celery_pids)
fi

TARGETS="$(printf '%s\n' "$TARGETS" | uniq_ints)"

if [[ -z "$TARGETS" ]]; then
  echo "开发端口 ${PORTS[*]} 空闲"
  exit 0
fi

echo "释放开发端口 ${PORTS[*]}："
while read -r pid; do
  [[ -n "$pid" ]] && describe "$pid"
done <<<"$TARGETS"

if [[ "$DRY_RUN" == 1 ]]; then
  echo "(dry-run，未发信号)"
  exit 0
fi

while read -r pid; do
  [[ -z "$pid" ]] && continue
  kill -TERM "$pid" 2>/dev/null || true
done <<<"$TARGETS"

sleep 1

leftovers=""
for port in "${PORTS[@]}"; do
  leftovers="${leftovers}
$(collect_listen_pids "$port")"
done
if [[ "$FREE_CELERY" == 1 ]]; then
  leftovers="${leftovers}
$(collect_celery_pids)"
fi
leftovers="$(printf '%s\n' "$leftovers" | uniq_ints)"

if [[ -n "$leftovers" ]]; then
  while read -r pid; do
    [[ -z "$pid" ]] && continue
    if is_protected "$pid"; then
      continue
    fi
    echo "仍占用，改为 SIGKILL pid $pid"
    kill -KILL "$pid" 2>/dev/null || true
  done <<<"$leftovers"
fi
