#!/usr/bin/env bash
# PIH Phase 0 协议 / 生命周期 / 数据库集成检查（qa-security 独立验证脚本）
#
# 用法：bash Tests/phase0_integration_check.sh
# 特性：
#   - 每次运行生成一次性 Token（脚本内不含任何真实 Token）与 mktemp 数据目录
#   - 全部使用真实子进程与真实 HTTP，不使用 mock / in-process ASGI
#   - 退出时清理本次启动的 Sidecar 进程与临时目录
#   - 任一项失败时脚本以非 0 退出，并打印失败清单
#
# 覆盖：API_CONTRACT.md §2.3/§2.4/§4/§5/§6/§7/§9/§10、DATABASE_BASELINE.md §2/§4/§7/§8/§11
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/Backend/.venv/bin/python"
ENTRY="$ROOT/Backend/main.py"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/pih-qa.XXXXXX")"
DATA="$WORK/data"
SIDE_PID=""
CHILD_PIDS=()
PASS=0
FAIL=0
FAILED_ITEMS=()

ok() { PASS=$((PASS + 1)); printf 'PASS  %s\n' "$1"; }
no() { FAIL=$((FAIL + 1)); FAILED_ITEMS+=("$1"); printf 'FAIL  %s\n' "$1"; }

expect_eq() {
  local name="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then ok "${name}（实际 ${actual}）"; else no "${name}（期望 [$expected]，实际 [$actual]）"; fi
}

expect_grep() {
  local name="$1" needle="$2" file="$3"
  if grep -qF -- "$needle" "$file" 2>/dev/null; then ok "$name"; else no "${name}（未在 $file 中命中 [$needle]）"; fi
}

expect_not_in_file() {
  local name="$1" needle="$2" file="$3"
  if [ ! -f "$file" ]; then no "${name}（文件缺失 ${file}）"; return; fi
  if grep -qF -- "$needle" "$file"; then no "${name}（命中敏感值）"; else ok "$name"; fi
}

stop_pid() {
  local pid="$1"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 60); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.1
  done
  kill -KILL "$pid" 2>/dev/null || true
}

cleanup() {
  if [ -n "$SIDE_PID" ]; then stop_pid "$SIDE_PID"; fi
  for pid in "${CHILD_PIDS[@]:-}"; do
    [ -n "$pid" ] && stop_pid "$pid"
  done
  pkill -f "$WORK" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

wait_for_file_line() {
  local file="$1" timeout="${2:-10}"
  local i
  for i in $(seq 1 $((timeout * 20))); do
    if [ -s "$file" ] && grep -q $'\n' "$file" 2>/dev/null; then return 0; fi
    sleep 0.05
  done
  return 1
}

read_port() {
  "$PY" - "$1" <<'PY'
import json, sys
line = open(sys.argv[1], encoding="utf-8").readline().strip()
prefix, payload = line.split(" ", 1)
assert prefix == "PIH_SIDECAR_READY", prefix
print(int(json.loads(payload)["port"]))
PY
}

start_sidecar() {
  # $1=stdout 文件 $2=stderr 文件 $3=data dir（可选） $4=PORT（默认 0）
  local out="$1" err="$2" data_dir="${3:-}" port="${4:-0}"
  local args=(env "PIH_SIDECAR_TOKEN=$TOKEN" "PIH_PORT=$port" "PYTHONUNBUFFERED=1")
  if [ -n "$data_dir" ]; then args+=("PIH_DATA_DIR=$data_dir"); fi
  "${args[@]}" "$PY" "$ENTRY" >"$out" 2>"$err" &
  SIDE_PID=$!
}

echo "== 环境 =="
echo "ROOT=$ROOT"
"$PY" -c 'import sys, sqlite3, platform; print("python", sys.version.split()[0], "| sqlite", sqlite3.sqlite_version, "|", platform.machine())'
sw_vers 2>/dev/null | tr '\n' ' ' || true
echo
echo "WORK=$WORK"

TOKEN="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')"
if [ "${#TOKEN}" -eq 43 ]; then ok "Token 长度 43（随机生成，未落盘）"; else no "Token 长度异常 ${#TOKEN}"; fi
STAMP="$(date -u +%H%M%S)"

# ---------------------------------------------------------------------------
echo
echo "== B. 协议与生命周期 =="

OUT1="$WORK/stdout1.txt"
ERR1="$WORK/stderr1.txt"
start_sidecar "$OUT1" "$ERR1" "$DATA" 0
PID1="$SIDE_PID"

if wait_for_file_line "$OUT1" 10; then ok "10 秒内收到握手"; else no "10 秒内未收到握手"; fi

HANDSHAKE="$(head -n 1 "$OUT1")"
echo "握手原文: $HANDSHAKE"
expect_eq "stdout 行数" "1" "$(wc -l < "$OUT1" | tr -d ' ')"

if "$PY" - "$OUT1" "$PID1" <<'PY'
import json, sys, re
line = open(sys.argv[1], encoding="utf-8").readline().rstrip("\n")
assert line.startswith("PIH_SIDECAR_READY "), "前缀错误"
assert len(line.encode()) <= 4096, "超长"
data = json.loads(line.split(" ", 1)[1])
assert isinstance(data, dict)
assert isinstance(data["port"], int) and 1 <= data["port"] <= 65535, data
assert isinstance(data["pid"], int) and data["pid"] > 0, data
assert data["service"] == "pih-backend", data
assert data["version"] == "0.4.0", data
assert data["pid"] == int(sys.argv[2]), (data["pid"], sys.argv[2])
assert set(data) == {"port", "pid", "service", "version"}, sorted(data)
PY
then ok "握手字段合法（port/pid/service/version，pid 与子进程一致）"; else no "握手字段非法"; fi

PORT1="$(read_port "$OUT1")"
BASE="http://127.0.0.1:$PORT1"
echo "PID1=$PID1 PORT1=$PORT1"

H2="$(mktemp "$WORK/h2.XXXXXX")"
H_NONE="$(mktemp "$WORK/h_none.XXXXXX")"
H_WRONG="$(mktemp "$WORK/h_wrong.XXXXXX")"
H_UNAUTH404="$(mktemp "$WORK/h_u404.XXXXXX")"
H_404="$(mktemp "$WORK/h_404.XXXXXX")"
H_405="$(mktemp "$WORK/h_405.XXXXXX")"
H_DOCS="$(mktemp "$WORK/h_docs.XXXXXX")"

CODE200="$(curl -sS -o "$H2" -D "$WORK/h2.headers" -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json' "$BASE/health" || true)"
expect_eq "正确 Token → HTTP" "200" "$CODE200"
expect_grep "响应含 X-Request-ID 头" "x-request-id" "$WORK/h2.headers"
expect_grep "响应含 Cache-Control: no-store" "cache-control: no-store" "$WORK/h2.headers"
expect_grep "Content-Type 为 application/json; charset=utf-8" "content-type: application/json; charset=utf-8" "$WORK/h2.headers"
expect_not_in_file "响应体不含 Token" "$TOKEN" "$H2"
expect_not_in_file "响应体不含数据库绝对路径" "$DATA" "$H2"

if "$PY" - "$H2" "$WORK/h2.headers" <<'PY'
import json, re, sys
body = json.load(open(sys.argv[1], encoding="utf-8"))
assert body["status"] in ("ok", "degraded"), body
assert body["service"] == "pih-backend"
assert body["version"] == "0.4.0"
assert isinstance(body["uptime_seconds"], (int, float)) and body["uptime_seconds"] >= 0
assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z", body["timestamp"]), body["timestamp"]
db = body["database"]
assert db["status"] in ("ok", "error")
assert db["path_kind"] == "custom", db
assert db["schema_version"] == 5, db
assert "code" not in db, db
headers = open(sys.argv[2], encoding="utf-8", errors="replace").read().lower()
rid = re.search(r"x-request-id: *([0-9a-f-]{36})", headers)
assert rid and re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", rid.group(1)), rid
print("health_body_ok")
PY
then ok "/health 字段齐全且值合法（ok / schema_version=5 / custom）"; else no "/health 字段不合法"; fi

C_NONE="$(curl -sS -o "$H_NONE" -w '%{http_code}' "$BASE/health" || true)"
expect_eq "无 Token → HTTP" "401" "$C_NONE"
expect_grep "无 Token 错误体 code=unauthorized" '"code":"unauthorized"' "$H_NONE"

C_WRONG="$(curl -sS -o "$H_WRONG" -w '%{http_code}' -H "Authorization: Bearer wrong-token" "$BASE/health" || true)"
expect_eq "错误 Token → HTTP" "401" "$C_WRONG"

C_U404="$(curl -sS -o "$H_UNAUTH404" -w '%{http_code}' "$BASE/no-such-path" || true)"
expect_eq "未认证访问不存在路径 → HTTP（鉴权先于路由）" "401" "$C_U404"
expect_grep "未认证 404 路径返回 unauthorized 而非 not_found" '"code":"unauthorized"' "$H_UNAUTH404"

C_404="$(curl -sS -o "$H_404" -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$BASE/no-such-path" || true)"
expect_eq "认证后不存在路径 → HTTP" "404" "$C_404"
expect_grep "404 统一错误体 not_found" '"code":"not_found"' "$H_404"
expect_grep "404 错误体为中文 message" '请求的资源不存在' "$H_404"

C_405="$(curl -sS -o "$H_405" -w '%{http_code}' -X POST -H "Authorization: Bearer $TOKEN" "$BASE/health" || true)"
expect_eq "认证后 POST /health → HTTP" "405" "$C_405"
expect_grep "405 统一错误体 method_not_allowed" '"code":"method_not_allowed"' "$H_405"

C_DOCS="$(curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$BASE/openapi.json" || true)"
expect_eq "认证后 /openapi.json → HTTP（契约要求关闭）" "404" "$C_DOCS"

# --- Phase 2: 文章与采集 API 冒烟 ---
H_ART="$WORK/articles.json"
C_ART="$(curl -sS -o "$H_ART" -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/articles?limit=5" || true)"
expect_eq "文章列表（空库）→ HTTP" "200" "$C_ART"
expect_grep "文章列表返回 total=0" '"total":0' "$H_ART"

C_ART_UNAUTH="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/api/v1/articles" || true)"
expect_eq "文章列表未认证 → HTTP" "401" "$C_ART_UNAUTH"

H_CSTATUS="$WORK/collection_status.json"
C_CSTATUS="$(curl -sS -o "$H_CSTATUS" -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/collection/status" || true)"
expect_eq "采集状态 → HTTP" "200" "$C_CSTATUS"
expect_grep "采集状态含 max_concurrency=3" '"max_concurrency":3' "$H_CSTATUS"

H_NOJOB="$WORK/no_job.json"
C_NOJOB="$(curl -sS -o "$H_NOJOB" -w '%{http_code}' -X POST \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"trigger_type":"manual","source_ids":null}' "$BASE/api/v1/collection-jobs" || true)"
expect_eq "无可用来源触发采集 → HTTP" "409" "$C_NOJOB"
expect_grep "无可用来源错误码" '"code":"no_enabled_sources"' "$H_NOJOB"

# --- Phase 3: 本地 AI 状态、白名单与错误面 ---
H_AI_STATUS="$WORK/ai_status.json"
C_AI_STATUS="$(curl -sS -o "$H_AI_STATUS" -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/ai/status" || true)"
expect_eq "AI 状态 → HTTP" "200" "$C_AI_STATUS"
expect_grep "AI Provider 仅本机" '"base_url":"http://127.0.0.1:11434"' "$H_AI_STATUS"
expect_grep "AI 并发=1" '"concurrency":1' "$H_AI_STATUS"
expect_grep "Embedding 默认禁用" '"embedding":{"enabled":false' "$H_AI_STATUS"

H_AI_MODELS="$WORK/ai_models.json"
C_AI_MODELS="$(curl -sS -o "$H_AI_MODELS" -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/ai/models" || true)"
expect_eq "AI 模型列表 → HTTP" "200" "$C_AI_MODELS"
expect_grep "模型列表含本地默认模型" '"model_name":"qwen3.5:4b-mlx"' "$H_AI_MODELS"

H_AI_BAD="$WORK/ai_bad.json"
C_AI_BAD="$(curl -sS -o "$H_AI_BAD" -w '%{http_code}' -X POST \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"scope":"selected"}' "$BASE/api/v1/ai/runs" || true)"
expect_eq "AI 指定文章但缺少 article_ids → HTTP" "422" "$C_AI_BAD"

H_AI_MISS="$WORK/ai_missing.json"
C_AI_MISS="$(curl -sS -o "$H_AI_MISS" -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/ai/runs/00000000-0000-4000-8000-000000000000" || true)"
expect_eq "不存在的 AI 运行 → HTTP" "404" "$C_AI_MISS"
expect_grep "不存在的 AI 运行错误码" '"code":"ai_run_not_found"' "$H_AI_MISS"

C_AI_UNAUTH="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/api/v1/ai/status" || true)"
expect_eq "AI 状态未认证 → HTTP" "401" "$C_AI_UNAUTH"

LSOF_OUT="$(lsof -nP -iTCP:"$PORT1" -sTCP:LISTEN || true)"
echo "$LSOF_OUT"
if [ -n "$LSOF_OUT" ] && [ "$(printf '%s\n' "$LSOF_OUT" | grep -c 'LISTEN')" -eq 1 ] \
  && printf '%s\n' "$LSOF_OUT" | grep -q "127.0.0.1:$PORT1"; then
  ok "仅监听 127.0.0.1:$PORT1"
else
  no "监听地址不是唯一 127.0.0.1:$PORT1"
fi
if printf '%s\n' "$LSOF_OUT" | grep -Eq '(\*:|0\.0\.0\.0:|\[::\])'; then no "检测到非 loopback 监听"; else ok "无 0.0.0.0 / :: 监听"; fi

# Token 泄漏（stdout / stderr / argv）
for f in "$OUT1" "$ERR1"; do
  expect_not_in_file "Token 未出现在 $(basename "$f")" "$TOKEN" "$f"
done
PS_ARGV="$(ps -o command= -p "$PID1" 2>/dev/null || true)"
if printf '%s' "$PS_ARGV" | grep -qF -- "$TOKEN"; then no "Token 出现在 ps argv"; else ok "Token 未出现在 ps argv"; fi
if printf '%s' "$PS_ARGV" | grep -q -- '--token\|PIH_SIDECAR_TOKEN='; then no "argv 出现 Token 参数/环境串"; else ok "argv 仅入口路径"; fi

# SIGTERM：3 秒内退出、exit 0、端口可重绑
T0="$("$PY" -c 'import time; print(time.time())')"
kill -TERM "$PID1"
set +e
wait "$PID1"
RC1=$?
set -e
T1="$("$PY" -c 'import time; print(time.time())')"
ELAPSED="$("$PY" -c "print(round($T1-$T0, 2))")"
expect_eq "SIGTERM 后退出码" "0" "$RC1"
if "$PY" -c "import sys; sys.exit(0 if $ELAPSED <= 3.0 else 1)"; then
  ok "SIGTERM 后 ${ELAPSED}s 内退出（<=3s）"
else
  no "SIGTERM 后 ${ELAPSED}s 仍未退出（>3s）"
fi
SIDE_PID=""

if "$PY" - "$PORT1" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", port))
s.listen(1)
s.close()
PY
then ok "退出后端口 $PORT1 可重绑"; else no "端口 $PORT1 被占用/无法重绑"; fi
expect_grep "stderr 记录 sidecar_stopping" '"event":"sidecar_stopping"' "$ERR1"
LL="$(wc -l < "$OUT1" | tr -d ' ')"
expect_eq "全程 stdout 行数保持 1" "1" "$LL"

# 连续两次启动端口不同
OUT2="$WORK/stdout2.txt"
ERR2="$WORK/stderr2.txt"
start_sidecar "$OUT2" "$ERR2" "$DATA" 0
PID2="$SIDE_PID"
if wait_for_file_line "$OUT2" 10; then ok "第二次启动收到握手"; else no "第二次启动未收到握手"; fi
PORT2="$(read_port "$OUT2")"
if [ "$PORT1" != "$PORT2" ]; then ok "连续两次启动端口不同（$PORT1 vs ${PORT2}）"; else no "两次启动端口相同（${PORT1}）"; fi
# 幂等重启：同一数据目录不重复应用迁移
if [ "$("$PY" - "$DATA/pih.sqlite3" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
print(c.execute("select count(*) from schema_migrations").fetchone()[0])
PY
)" = "5" ]; then ok "同目录二次启动后 schema_migrations 仍仅 5 行"; else no "二次启动迁移记录异常"; fi
stop_pid "$PID2"
set +e; wait "$PID2"; RC2=$?; set -e
expect_eq "第二次 SIGTERM 退出码" "0" "$RC2"
SIDE_PID=""

# 配置错误：exit 2 且无握手
run_exit_case() {
  local name="$1" expected="$2"
  shift 2
  local out="$WORK/ec_out.txt" err="$WORK/ec_err.txt"
  local rc
  set +e
  env -i PATH="$PATH" "$@" "$PY" "$ENTRY" >"$out" 2>"$err"
  rc=$?
  set -e
  expect_eq "$name 退出码" "$expected" "$rc"
  if [ -s "$out" ]; then no "$name stdout 应无握手"; else ok "$name stdout 无握手"; fi
}

run_exit_case "无 Token" "2" "PIH_PORT=0"
run_exit_case "畸形 Token（长度/字符非法）" "2" "PIH_SIDECAR_TOKEN=short-token" "PIH_PORT=0"
run_exit_case "非法 PIH_PORT（非数字）" "2" "PIH_SIDECAR_TOKEN=$TOKEN" "PIH_PORT=abc"
run_exit_case "非法 PIH_PORT（越界 70000）" "2" "PIH_SIDECAR_TOKEN=$TOKEN" "PIH_PORT=70000"
run_exit_case "相对 PIH_DATA_DIR" "2" "PIH_SIDECAR_TOKEN=$TOKEN" "PIH_PORT=0" "PIH_DATA_DIR=relative/path"

# 降级：数据目录不可写 → 200 + degraded + database.code
RO_DIR="$WORK/readonly"
mkdir -p "$RO_DIR"
chmod 500 "$RO_DIR"
OUT3="$WORK/stdout3.txt"
ERR3="$WORK/stderr3.txt"
start_sidecar "$OUT3" "$ERR3" "$RO_DIR/data" 0
PID3="$SIDE_PID"
if wait_for_file_line "$OUT3" 10; then ok "不可写数据目录仍启动并握手（数据库失败不阻止启动）"; else no "不可写数据目录时未握手"; fi
if [ -s "$OUT3" ]; then
  PORT3="$(read_port "$OUT3")"
  H3="$WORK/h3.json"
  C3="$(curl -sS -o "$H3" -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT3/health" || true)"
  expect_eq "降级时 HTTP" "200" "$C3"
  expect_grep "降级体 status=degraded" '"status":"degraded"' "$H3"
  if "$PY" - "$H3" <<'PY'
import json, sys
body = json.load(open(sys.argv[1], encoding="utf-8"))
db = body["database"]
assert db["status"] == "error", db
assert db["code"] in {"database_unavailable", "database_locked", "database_migration_failed", "database_schema_error"}, db
assert db["schema_version"] is None, db
print("degraded_ok", db["code"])
PY
  then ok "降级体含合法 database.code 且 schema_version=null"; else no "降级体 database 字段不合法"; fi
fi
chmod 700 "$RO_DIR"
stop_pid "$PID3"
set +e; wait "$PID3"; RC3=$?; set -e
expect_eq "降级实例 SIGTERM 退出码" "0" "$RC3"
SIDE_PID=""

# 父进程消失：由 python 拉起并存活 1 秒后自身退出（模拟 App 崩溃），
# Sidecar 看门狗应在约 3 秒内优雅退出。
PW="$WORK/parent-loss"
mkdir -p "$PW"
PW_DATA="$PW/data"
PIH_SIDECAR_TOKEN="$TOKEN" PIH_PORT=0 PIH_DATA_DIR="$PW_DATA" "$PY" - "$PY" "$ENTRY" "$PW" <<'PY'
import os, subprocess, sys, time
py, entry, wd = sys.argv[1:4]
out = open(os.path.join(wd, "out.txt"), "wb")
err = open(os.path.join(wd, "err.txt"), "wb")
proc = subprocess.Popen([py, entry], stdout=out, stderr=err, stdin=subprocess.DEVNULL)
open(os.path.join(wd, "pid"), "w").write(str(proc.pid))
time.sleep(1.0)  # 让 Sidecar 完成看门狗初始化后，父进程再消失
PY
PL_PID="$(cat "$PW/pid")"
CHILD_PIDS+=("$PL_PID")
if wait_for_file_line "$PW/out.txt" 10; then ok "父进程消失用例已握手"; else no "父进程消失用例未握手"; fi
PL_T0="$("$PY" -c 'import time; print(time.time())')"
PL_DEAD=0
for _ in $(seq 1 80); do
  if ! kill -0 "$PL_PID" 2>/dev/null; then PL_DEAD=1; break; fi
  sleep 0.05
done
PL_ELAPSED="$("$PY" -c "import time; print(round(time.time()-$PL_T0, 2))")"
if [ "$PL_DEAD" = "1" ] && "$PY" -c "import sys; sys.exit(0 if $PL_ELAPSED <= 4.0 else 1)"; then
  ok "父进程消失后 Sidecar ${PL_ELAPSED}s 内退出（<=4s，含 2s 轮询）"
else
  no "父进程消失后 Sidecar 未在 4s 内退出（已等待 ${PL_ELAPSED}s）"
fi
expect_grep "父进程消失记录 parent_lost 事件" '"event":"parent_lost"' "$PW/err.txt"
if [ -f "$PW/out.txt" ]; then
  expect_eq "父进程消失场景 stdout 行数" "1" "$(wc -l < "$PW/out.txt" | tr -d ' ')"
fi

# 已知偏差探测（不计入 PASS/FAIL）：父进程在 Sidecar 完成看门狗初始化之前退出时，
# 看门狗把 parent_pid 记成 1，进程成为永久孤儿（ppid=1，无 parent_lost）。
RW="$WORK/race"
mkdir -p "$RW"
PIH_SIDECAR_TOKEN="$TOKEN" PIH_PORT=0 PIH_DATA_DIR="$RW/data" "$PY" - "$PY" "$ENTRY" "$RW" <<'PY'
import os, subprocess, sys
py, entry, wd = sys.argv[1:4]
out = open(os.path.join(wd, "out.txt"), "wb")
err = open(os.path.join(wd, "err.txt"), "wb")
proc = subprocess.Popen([py, entry], stdout=out, stderr=err, stdin=subprocess.DEVNULL)
open(os.path.join(wd, "pid"), "w").write(str(proc.pid))
PY
RACE_PID="$(cat "$RW/pid")"
CHILD_PIDS+=("$RACE_PID")
if wait_for_file_line "$RW/out.txt" 10; then
  sleep 8
  if kill -0 "$RACE_PID" 2>/dev/null; then
    echo "WARN  启动竞态：父进程在 watchdog 初始化前退出 → Sidecar 成为孤儿（ppid=$(ps -o ppid= -p "$RACE_PID" | tr -d ' ')），parent_lost 事件 $(grep -c parent_lost "$RW/err.txt" || true) 条（契约 §9.2 偏差，P2）"
  else
    ok "启动竞态用例中 Sidecar 已自行退出"
  fi
  stop_pid "$RACE_PID"
fi

# ---------------------------------------------------------------------------
echo
echo "== C. 数据库 =="

DB="$DATA/pih.sqlite3"
if [ -f "$DB" ]; then ok "初始化后真实生成 $DB"; else no "未生成 pih.sqlite3"; fi
if [ -f "$DB" ]; then
  expect_eq "PRAGMA journal_mode" "wal" "$(sqlite3 "$DB" 'PRAGMA journal_mode;')"
  TABLES="$(sqlite3 "$DB" "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;" | tr '\n' ',')"
  expect_eq "业务表清单（Phase 3：信息源 + 文章 + 采集 + 本地 AI）" "ai_model_registry,ai_run_items,ai_runs,app_meta,article_ai_analysis,article_embeddings,articles,collection_job_items,collection_jobs,schema_migrations,source_categories,source_fetch_state,source_health_logs,sources," "$TABLES"
  MIG="$(sqlite3 "$DB" 'SELECT version FROM schema_migrations ORDER BY version;' | tr '\n' ',')"
  expect_eq "schema_migrations 版本" "1,2,3,4,5," "$MIG"
  expect_eq "schema_migrations 行数" "5" "$(sqlite3 "$DB" 'SELECT COUNT(*) FROM schema_migrations;')"
  IDX="$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%';")"
  expect_eq "Phase 3 业务索引数" "27" "$IDX"
  expect_eq "AI 模型注册表种子数" "3" "$(sqlite3 "$DB" 'SELECT COUNT(*) FROM ai_model_registry;')"
  expect_eq "AI 云端模型阻断（DB CHECK）" "0" "$(sqlite3 "$DB" "SELECT COUNT(*) FROM ai_model_registry WHERE model_name LIKE '%-cloud%';")"
  FK_TARGET="$(sqlite3 "$DB" "SELECT \"table\" FROM pragma_foreign_key_list('sources');")"
  expect_eq "sources 外键指向分类表" "source_categories" "$FK_TARGET"
  expect_eq "app_meta 初始行数" "0" "$(sqlite3 "$DB" 'SELECT COUNT(*) FROM app_meta;')"
  expect_eq "PRAGMA quick_check" "ok" "$(sqlite3 "$DB" 'PRAGMA quick_check;')"

  sqlite3 "$DB" "INSERT INTO app_meta(key, value, updated_at) VALUES('qa_probe', 'v1', '2026-11-16T00:00:00Z') ON CONFLICT(key) DO UPDATE SET value=excluded.value;"
  expect_eq "sqlite3 真实写入后读出" "v1" "$(sqlite3 "$DB" "SELECT value FROM app_meta WHERE key='qa_probe';")"
  sqlite3 "$DB" "DELETE FROM app_meta WHERE key='qa_probe';"

  if (cd "$ROOT/Backend" && PIH_DATA_DIR="$DATA" "$PY" - <<'PY'
import sqlite3
import database

try:
    with database.session() as conn:
        conn.execute(
            "INSERT INTO app_meta(key, value, updated_at) VALUES('qa_rollback','x','2026-11-16T00:00:00Z')"
        )
        raise RuntimeError("injected failure")
except RuntimeError:
    pass

conn = sqlite3.connect(database.database_path())
try:
    n = conn.execute("SELECT COUNT(*) FROM app_meta WHERE key='qa_rollback'").fetchone()[0]
finally:
    conn.close()
assert n == 0, f"rollback failed, rows={n}"
print("rollback_ok")
PY
  ); then ok "session() 抛异常后无残留（事务回滚）"; else no "事务回滚验证失败"; fi
fi

DERR="$WORK/dir_mode.txt"
MODE="$(stat -f '%Lp' "$DATA" 2>/dev/null || echo '?')"
echo "数据目录权限: ${MODE}（期望 700）" > "$DERR"
if [ "$MODE" = "700" ]; then ok "数据目录权限 0700"; else no "数据目录权限为 ${MODE}（期望 700）"; fi
FMO="$(stat -f '%Lp' "$DB" 2>/dev/null || echo '?')"
if [ "$FMO" = "600" ]; then ok "数据库文件权限 0600"; else no "数据库文件权限为 ${FMO}（期望 600）"; fi

echo
echo "== 汇总 =="
echo "PASS=$PASS FAIL=$FAIL"
if [ "$FAIL" -ne 0 ]; then
  printf '失败项:\n'
  for item in "${FAILED_ITEMS[@]}"; do printf '  - %s\n' "$item"; done
  exit 1
fi
echo "ALL CHECKS PASSED"
