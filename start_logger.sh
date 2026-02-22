#!/bin/bash
# ============================================================
# Shell wrapper for interleaved_logger.py
# Використовується Launch Agent-ом для правильного середовища
# Скрипти живуть у: ~/scripts/activitylogger/
# ============================================================

# --- Критично для launchd: явно встановлюємо змінні середовища ---
export HOME=/Users/mk
export USER=mk
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

# Шлях до pip --user site-packages (де встановлено pynput, requests)
export PYTHONPATH=/Users/mk/Library/Python/3.9/lib/python/site-packages

# --- Логування старту ---
LOG_DIR="/Users/mk/scripts/activitylogger/logs"
mkdir -p "$LOG_DIR"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] start_logger.sh launched" >> "$LOG_DIR/wrapper.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Python: $(/usr/bin/python3 --version 2>&1)" >> "$LOG_DIR/wrapper.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] PYTHONPATH: $PYTHONPATH" >> "$LOG_DIR/wrapper.log"

# --- Запуск скрипта ---
exec /usr/bin/python3 -u /Users/mk/scripts/activitylogger/interleaved_logger.py
