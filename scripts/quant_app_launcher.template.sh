#!/bin/zsh

set -euo pipefail

REPO_DIR="__REPO_DIR__"
RUNNER_SCRIPT="$REPO_DIR/scripts/desktop_common.sh"
ENV_FILE="$REPO_DIR/.env"
ENV_EXAMPLE="$REPO_DIR/.env.example"
INSTALL_COMMAND="$REPO_DIR/install_runtime.command"
PAPER_COMMAND="$REPO_DIR/launch_paper.command"
MONITOR_COMMAND="$REPO_DIR/launch_monitor.command"
TESTNET_COMMAND="$REPO_DIR/launch_testnet.command"
BACKTEST_COMMAND="$REPO_DIR/run_backtest.command"
NETWORKCHECK_COMMAND="$REPO_DIR/launch_network_check.command"
WEB_URL="http://127.0.0.1:8765/?launch=$(date +%s)"
HEALTH_URL="http://127.0.0.1:8765/health"

show_alert() {
  local title="$1"
  local message="$2"
  /usr/bin/osascript \
    -e "display alert \"$title\" message \"$message\" as critical" \
    >/dev/null 2>&1 || true
}

choose_action() {
  if [[ -n "${QUANT_LAUNCHER_ACTION:-}" ]]; then
    printf '%s\n' "$QUANT_LAUNCHER_ACTION"
    return
  fi

  /usr/bin/osascript <<'APPLESCRIPT'
 set menuItems to {"启动仿真盘（Paper + Web）", "启动主网观察（只读 + Web）", "启动测试盘（Testnet + Web）", "网络自检", "运行回测示例", "首次安装 / 修复环境", "编辑 .env", "打开项目文件夹"}
set chosenItems to choose from list menuItems default items {"启动仿真盘（Paper + Web）"}
if chosenItems is false then
  return ""
end if
return item 1 of chosenItems
APPLESCRIPT
}

open_command_launcher() {
  local launcher_path="$1"
  if [[ "${QUANT_LAUNCHER_DRY_RUN:-0}" == "1" ]]; then
    printf 'launch:%s\n' "$launcher_path"
    return
  fi

  /usr/bin/open -a Terminal "$launcher_path"
}

open_dashboard_when_ready() {
  if [[ "${QUANT_LAUNCHER_DRY_RUN:-0}" == "1" ]]; then
    printf 'open-dashboard:%s\n' "$WEB_URL"
    return
  fi

  /usr/bin/nohup /bin/zsh -c "
    for _ in {1..60}; do
      if /usr/bin/curl -sS '$HEALTH_URL' >/dev/null 2>&1; then
        /usr/bin/open '$WEB_URL' >/dev/null 2>&1 || /usr/bin/open -a Safari '$WEB_URL' >/dev/null 2>&1 || true
        exit 0
      fi
      /bin/sleep 1
    done
  " >/dev/null 2>&1 &
}

ensure_env_file() {
  if [[ ! -f "$ENV_FILE" && -f "$ENV_EXAMPLE" ]]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
  fi
}

main() {
  if [[ ! -x "$RUNNER_SCRIPT" ]]; then
    show_alert "Quant 启动器" "找不到启动脚本：$RUNNER_SCRIPT"
    exit 1
  fi

  local choice
  choice="$(choose_action)"
  if [[ -z "$choice" ]]; then
    exit 0
  fi

  case "$choice" in
    "启动仿真盘（Paper + Web）")
      open_dashboard_when_ready
      open_command_launcher "$PAPER_COMMAND"
      ;;
    "启动主网观察（只读 + Web）")
      open_dashboard_when_ready
      open_command_launcher "$MONITOR_COMMAND"
      ;;
    "启动测试盘（Testnet + Web）")
      open_dashboard_when_ready
      open_command_launcher "$TESTNET_COMMAND"
      ;;
    "运行回测示例")
      open_command_launcher "$BACKTEST_COMMAND"
      ;;
    "网络自检")
      open_command_launcher "$NETWORKCHECK_COMMAND"
      ;;
    "首次安装 / 修复环境")
      open_command_launcher "$INSTALL_COMMAND"
      ;;
    "编辑 .env")
      ensure_env_file
      if [[ "${QUANT_LAUNCHER_DRY_RUN:-0}" == "1" ]]; then
        printf 'open:%s\n' "$ENV_FILE"
        exit 0
      fi
      /usr/bin/open -a TextEdit "$ENV_FILE"
      ;;
    "打开项目文件夹")
      if [[ "${QUANT_LAUNCHER_DRY_RUN:-0}" == "1" ]]; then
        printf 'open:%s\n' "$REPO_DIR"
        exit 0
      fi
      /usr/bin/open "$REPO_DIR"
      ;;
    *)
      show_alert "Quant 启动器" "未识别的菜单项：$choice"
      exit 1
      ;;
  esac
}

main "$@"
