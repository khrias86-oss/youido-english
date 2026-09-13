#!/usr/bin/env bash
# Vercel 빌드: 웹앱 정적 파일을 public/ 으로 모으고 데이터 출처를 config.js 에 심는다.
#
# 빈자리 데이터 자체는 GitHub Actions 가 GitHub Pages 에 올린 data.json 을 그대로 읽는다.
# Pages 는 CORS 를 허용하므로 다른 도메인(Vercel)에서도 fetch 가 된다. 감시를 Actions 에
# 남겨 두는 편이 무료 인스턴스가 잠들 걱정이 없어 더 안정적이다.
#
# 조정용 환경변수: UMPPA_DATA_URL, UMPPA_SOURCE_URL
set -euo pipefail

OUT=public
SRC=umppa_monitor/webapp
DATA_URL="${UMPPA_DATA_URL:-https://khrias86-oss.github.io/youido-english/data.json}"
SOURCE_URL="${UMPPA_SOURCE_URL:-https://github.com/khrias86-oss/youido-english/actions/workflows/monitor.yml}"

rm -rf "$OUT"
mkdir -p "$OUT"
cp -R "$SRC"/. "$OUT"/

# apiBase "/" = 이 배포의 /api/prefs 로 감시 조건을 저장한다.
cat > "$OUT/config.js" <<EOF
window.UMPPA_CONFIG={"dataUrl":"$DATA_URL","apiBase":"/","sourceUrl":"$SOURCE_URL"};
EOF

echo "built $OUT/ from $SRC (data: $DATA_URL)"
