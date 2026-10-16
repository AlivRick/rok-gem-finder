#!/bin/sh
# CEO session: Claude Code + Telegram channel (bot @thuan_review_bot).
# The telegram plugin is disabled at user scope and enabled only here: every session
# that loads it kills the previous poller and takes over the bot.
# ponytail: no auto-restart on crash/reboot; upgrade path is a systemd --user unit or a VPS.
cd "$(dirname "$0")" || exit 1
export TELEGRAM_STATE_DIR="$PWD/.telegram"
command -v bun >/dev/null || { echo "bun not in PATH (the telegram plugin runs on bun)" >&2; exit 1; }
# --quiet: mở phiên trống, không gọi model cho tới khi có tin Telegram đầu tiên (0 token khi chủ không nhắn). Dùng cho reset hằng ngày.
if [ "${1:-}" = "--quiet" ]; then shift
else [ $# -eq 0 ] && set -- "Khởi động lại: đọc TASKS.md, báo chủ qua Telegram rằng đội đã online kèm việc đang dở (nếu có), rồi làm tiếp."
fi
exec claude -n rok \
  --settings '{"enabledPlugins":{"telegram@claude-plugins-official":true}}' \
  --channels plugin:telegram@claude-plugins-official \
  --permission-mode auto "$@"
