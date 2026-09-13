#!/bin/sh
# 설정 파일 준비 순서: /data/config.yaml (볼륨) > MONITOR_CONFIG_B64 (환경변수) > config.example.yaml
set -e
CFG=/data/config.yaml
if [ ! -f "$CFG" ]; then
  if [ -n "$MONITOR_CONFIG_B64" ]; then
    echo "$MONITOR_CONFIG_B64" | base64 -d > "$CFG"
  else
    cp /app/config.example.yaml "$CFG"
  fi
fi
exec umppa-monitor serve -c "$CFG" --host 0.0.0.0 --port "${PORT:-8000}"
