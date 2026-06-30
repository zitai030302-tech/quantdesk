#!/bin/zsh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
PYTHON_BIN=""
WEB_URL="http://127.0.0.1:8765"
HEALTH_URL="$WEB_URL/health"
MPL_DIR="$REPO_DIR/.matplotlib"
EXPECTED_UI_VERSION="2026-04-19-web-terminal-v5"

browser_target_url() {
  printf '%s/?launch=%s\n' "$WEB_URL" "$(date +%s)"
}

open_browser_now() {
  local target_url
  target_url="$(browser_target_url)"
  /usr/bin/open "$target_url" >/dev/null 2>&1 || /usr/bin/open -a Safari "$target_url" >/dev/null 2>&1 || true
}

enable_browser_launch() {
  export QUANT_AUTO_OPEN_BROWSER=1
  export QUANT_AUTO_OPEN_URL
  QUANT_AUTO_OPEN_URL="$(browser_target_url)"
}

pause_before_exit() {
  echo ""
  read "reply?按回车关闭窗口..."
}

trap pause_before_exit EXIT

print_header() {
  echo "========================================"
  echo "$1"
  echo "仓库: $REPO_DIR"
  echo "========================================"
}

ensure_env_file() {
  if [[ ! -f "$REPO_DIR/.env" ]]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo "已自动创建 .env，请按需填入 Testnet API Key。"
  fi
}

ensure_venv() {
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "未发现虚拟环境，正在创建 .venv ..."
    python3 -m venv "$VENV_DIR"
  fi
  PYTHON_BIN="$VENV_DIR/bin/python"
}

missing_modules() {
  "$PYTHON_BIN" - <<'PY'
required = ["yaml", "dotenv", "httpx", "websockets", "rich", "matplotlib"]
missing = []
for name in required:
    try:
        __import__(name)
    except Exception:
        missing.append(name)
print(",".join(missing))
PY
}

ensure_dependencies() {
  local missing
  missing="$(missing_modules)"
  if [[ -n "$missing" ]]; then
    echo "检测到缺失依赖: $missing"
    echo "正在安装 requirements.txt ..."
    "$PYTHON_BIN" -m pip install --upgrade pip
    "$PYTHON_BIN" -m pip install -r "$REPO_DIR/requirements.txt"
  fi
}

ensure_runtime_ready() {
  ensure_env_file
  ensure_venv
  mkdir -p "$MPL_DIR"
  export MPLCONFIGDIR="$MPL_DIR"
  ensure_dependencies
}

ensure_testnet_credentials() {
  ensure_env_file
  if ! grep -q '^BINANCE_TESTNET_API_KEY=' "$REPO_DIR/.env" || ! grep -q '^BINANCE_TESTNET_API_SECRET=' "$REPO_DIR/.env"; then
    echo "未找到 Testnet API Key/Secret，请先编辑 $REPO_DIR/.env"
    /usr/bin/open -a TextEdit "$REPO_DIR/.env" >/dev/null 2>&1 || true
    exit 1
  fi
  if grep -q '^BINANCE_TESTNET_API_KEY=your_testnet_api_key$' "$REPO_DIR/.env"; then
    echo "请先把 .env 里的 Testnet API Key 改成真实测试密钥。"
    /usr/bin/open -a TextEdit "$REPO_DIR/.env" >/dev/null 2>&1 || true
    exit 1
  fi
  if grep -q '^BINANCE_TESTNET_API_SECRET=your_testnet_api_secret$' "$REPO_DIR/.env"; then
    echo "请先把 .env 里的 Testnet API Secret 改成真实测试密钥。"
    /usr/bin/open -a TextEdit "$REPO_DIR/.env" >/dev/null 2>&1 || true
    exit 1
  fi
}

existing_dashboard_info() {
  "$PYTHON_BIN" - "$HEALTH_URL" <<'PY'
import json
import sys
from urllib.request import urlopen

health_url = sys.argv[1]
status_url = health_url.rsplit("/", 1)[0] + "/api/status"
with urlopen(health_url, timeout=1.0) as response:
    if response.status != 200:
        raise SystemExit(1)
with urlopen(status_url, timeout=1.0) as response:
    payload = json.load(response)
print(f"{payload.get('mode', 'unknown')}|{payload.get('ui_version', 'unknown')}")
PY
}

stop_existing_dashboard() {
  local pids
  pids="$(lsof -n -P -ti TCP:8765 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return
  fi
  echo "检测到旧的本地控制台进程，正在尝试停止并重启..."
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    local command_line
    command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$command_line" == *"$REPO_DIR"* || "$command_line" == *"main.py"* || "$command_line" == *"quant"* ]]; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done <<< "$pids"
  sleep 1
}

handle_existing_dashboard() {
  local desired_mode="$1"
  local dashboard_info=""
  local current_mode=""
  local current_version=""
  dashboard_info="$(existing_dashboard_info 2>/dev/null || true)"
  if [[ -z "$dashboard_info" ]]; then
    return 1
  fi
  current_mode="${dashboard_info%%|*}"
  current_version="${dashboard_info#*|}"

  if [[ "$current_version" != "$EXPECTED_UI_VERSION" ]]; then
    echo "检测到旧版控制台（$current_version），将自动重启到最新版。"
    stop_existing_dashboard
    return 1
  fi

  if [[ "$current_mode" == "$desired_mode" ]]; then
    echo "检测到已有 $desired_mode 会话正在运行，直接打开控制台。"
    open_browser_now
    return 0
  fi

  echo "检测到已有 $current_mode 会话正在使用 $WEB_URL。"
  echo "将先停止旧会话，再启动 $desired_mode。"
  stop_existing_dashboard
  return 1
}

run_install() {
  print_header "首次安装 / 修复运行环境"
  ensure_runtime_ready
  echo "环境准备完成。"
  echo ""
  echo "之后可直接双击以下任一启动器："
  echo "- 启动仿真盘.command"
  echo "- 启动主网观察.command"
  echo "- 启动测试盘.command"
  echo "- 运行回测.command"
}

run_paper() {
  print_header "启动仿真盘（Paper + Web）"
  ensure_runtime_ready
  local dashboard_check=1
  if handle_existing_dashboard "paper"; then
    dashboard_check=0
  else
    dashboard_check=$?
  fi
  if [[ $dashboard_check -eq 0 ]]; then
    return
  fi
  echo "如果 Binance 公网行情被限制访问，系统会自动切换到本地示例回放。"
  enable_browser_launch
  cd "$REPO_DIR"
  "$PYTHON_BIN" main.py trade -c config/freqtrade_compat.json --dry-run --dashboard both
}

run_monitor() {
  print_header "启动主网观察（只读 + Web）"
  ensure_runtime_ready
  local dashboard_check=1
  if handle_existing_dashboard "monitor"; then
    dashboard_check=0
  else
    dashboard_check=$?
  fi
  if [[ $dashboard_check -eq 0 ]]; then
    return
  fi
  echo "主网观察模式只读取 Binance 官方数据并生成计划，不会自动下单。"
  echo "如果已在 .env 填入只读主网 API Key/Secret，还会同步账户余额与现货持仓。"
  enable_browser_launch
  cd "$REPO_DIR"
  "$PYTHON_BIN" main.py trade -c config/freqtrade_compat.json --monitor --dashboard both
}

run_testnet() {
  print_header "启动测试盘（Testnet + Web）"
  ensure_runtime_ready
  local dashboard_check=1
  if handle_existing_dashboard "testnet"; then
    dashboard_check=0
  else
    dashboard_check=$?
  fi
  if [[ $dashboard_check -eq 0 ]]; then
    return
  fi
  ensure_testnet_credentials
  enable_browser_launch
  cd "$REPO_DIR"
  "$PYTHON_BIN" main.py trade -c config/freqtrade_compat.json --sandbox --no-dry-run --dashboard both
}

run_backtest() {
  print_header "运行回测示例"
  ensure_runtime_ready
  cd "$REPO_DIR"
  "$PYTHON_BIN" main.py backtesting -c config/freqtrade_compat.json --csv tests/fixtures/btcusdt_1m_sample.csv
}

run_network_check() {
  print_header "Binance / Testnet 网络自检"
  ensure_runtime_ready
  cd "$REPO_DIR"
  "$PYTHON_BIN" scripts/check_binance_network.py
}

case "${1:-}" in
  install)
    run_install
    ;;
  paper)
    run_paper
    ;;
  monitor)
    run_monitor
    ;;
  testnet)
    run_testnet
    ;;
  backtest)
    run_backtest
    ;;
  networkcheck)
    run_network_check
    ;;
  *)
    print_header "未知启动参数"
    echo "用法: scripts/desktop_common.sh {install|paper|monitor|testnet|backtest|networkcheck}"
    exit 1
    ;;
esac
