#!/bin/sh
set -e

CMD="${1:-cron}"

# ── Modalità MENU: long polling Telegram (processo continuo) ─────────────────
if [ "$CMD" = "menu" ]; then
    echo "[entrypoint] Avvio modalità MENU (long polling Telegram)..."
    exec python /app/bandi_bot.py menu
fi

# ── Modalità NOW: esecuzione immediata one-shot ───────────────────────────────
if [ "$CMD" = "now" ]; then
    echo "[entrypoint] Esecuzione immediata..."
    exec python /app/bandi_bot.py search
fi

# ── Modalità CRON: ricerca automatica giornaliera ────────────────────────────
echo "[entrypoint] Avvio modalità CRON: '${CRON_SCHEDULE:-15 7 * * *}'"

which crond 2>/dev/null || (apt-get update -qq && apt-get install -y -qq cron)

printenv | grep -E '^(TELEGRAM|DB_|LOG_|CRON_)' | sed 's/^/export /' > /etc/cron_env.sh
chmod +x /etc/cron_env.sh

cat > /etc/cron.d/bandi-bot << CRONEOF
SHELL=/bin/sh
PATH=/usr/local/bin:/usr/bin:/bin
${CRON_SCHEDULE:-15 7 * * *} root . /etc/cron_env.sh && python /app/bandi_bot.py search >> /data/bandi_cron.log 2>&1
CRONEOF

chmod 0644 /etc/cron.d/bandi-bot
crontab /etc/cron.d/bandi-bot

if [ "${RUN_ON_START:-0}" = "1" ]; then
    echo "[entrypoint] RUN_ON_START=1: esecuzione immediata..."
    python /app/bandi_bot.py search
fi

exec cron -f
