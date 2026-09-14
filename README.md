# umppa-monitor — 서울형 키즈카페 빈자리 감시·알림

서울시 우리동네키움포털(umppa.seoul.go.kr)의 **서울형 키즈카페 회차 예약** 또는 **키즈카페 프로그램 예약** 페이지를 주기적으로 확인해, 마감이던 자리가 **예약 가능으로 바뀌면** 텔레그램·디스코드·슬랙·ntfy·이메일로 알려줍니다.

- 감시 대상은 설정 파일에서 `type: kidscafe`(시설 ID) / `type: program`(프로그램 번호) 중 골라 여러 개 등록
- 요일·날짜·회차·최소 잔여 인원 필터
- 상태 전환(마감→가능)만 알림, 재알림·마감 알림 옵션
- 로컬 상시 실행 또는 GitHub Actions 10분 주기 실행, 무료 호스팅(Render/Koyeb) 모바일 대시보드
- 계획서: [docs/PLAN.md](docs/PLAN.md)

> **참고**: 초기 버전은 사이트 HTML 을 직접 확인하지 못한 환경에서 작성되었으나, 2026-09-13 GitHub Actions 실행에서 실제 사이트(YF260101)에 접속해 달력 표기 방식을 확인하고 파서를 맞췄습니다. 실제 사이트는 "예약가능/마감" 같은 문구 대신 **"N회 개인/공용 잔여인원"** 처럼 회차별 숫자를 나열하는 방식이며(0=마감), 이 형식을 인식하도록 `parsers/common.py` 의 `extract_round_counts()` 가 처리합니다. 다른 시설/사이트는 마크업이 다를 수 있으니, 새 대상을 추가하면 아래 **3단계(inspect)** 로 한 번 확인하는 것을 권장합니다.

## 1. 설치

```bash
git clone <this repo> && cd youido-english
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[web,dev]"
python -m playwright install chromium                   # 헤드리스 크로미움 설치
```

## 2. 설정

```bash
cp config.example.yaml config.yaml
```

`config.yaml` 핵심 항목:

```yaml
targets:
  - type: kidscafe          # 키즈카페 회차 예약 (달력)
    id: YF260101            # URL 의 q_fcltyId 값
    name: 여의도점
    months_ahead: 1         # 이번 달 + 다음 달
    weekdays: [5, 6]        # 토·일만 (0=월 … 6=일). 비우면 전체
    sessions: ["2회차"]     # 회차/시간 부분일치. 비우면 전체
    min_remaining: 1
  - type: program           # 프로그램 예약
    id: 8644                # URL 의 q_progrmSn 값
    name: 공예교실

notifiers:
  - type: telegram
    token: ${UMPPA_TELEGRAM_TOKEN}
    chat_id: ${UMPPA_TELEGRAM_CHAT_ID}

schedule:
  interval_sec: 300         # 5분
  quiet_hours: ["00:30-06:30"]
```

알림 채널 설정 방법:

| 채널 | 준비 | 설정 키 |
|---|---|---|
| Telegram | @BotFather 로 봇 생성 → 봇에게 말 걸기 → `https://api.telegram.org/bot<TOKEN>/getUpdates` 에서 chat_id 확인 | `token`, `chat_id` |
| ntfy (가장 간단) | 휴대폰에 ntfy 앱 설치 → 임의 토픽 구독 | `topic` |
| Discord | 채널 설정 → 연동 → 웹후크 URL | `webhook_url` |
| Slack | Incoming Webhook 앱 | `webhook_url` |
| Email | SMTP 계정 (Gmail 은 앱 비밀번호) | `smtp_host`, `smtp_port`, `username`, `password`, `to` |

```bash
umppa-monitor test-notify -c config.yaml     # 채널 동작 확인
```

## 3. 최초 1회: 페이지 구조 진단 (필수)

```bash
umppa-monitor inspect -c config.yaml
```

`artifacts/inspect/<시각>/<대상>/` 에 저장되는 것:

| 파일 | 내용 |
|---|---|
| `page_0.html`, `page_1.html` | 이번 달/다음 달 달력(또는 프로그램 상세) 렌더 결과 |
| `slot_<n>_<날짜>.html` | 날짜를 클릭했을 때 나타난 회차 목록 |
| `network.json`, `xhr_<n>.json` | 페이지가 호출한 `.do` 요청/응답 (JSON 이면 별도 저장) |
| `*.png` | 스크린샷 |
| `parsed_slots.json` | 현재 휴리스틱 파서가 인식한 슬롯 |

터미널에 파싱 결과가 함께 출력됩니다. 확인 포인트:

1. **`parsed slots: 0`** 이거나 날짜/회차가 이상하면 → `page_0.html` 에서 달력 셀의 태그·클래스, 회차 표기, 잔여 문구를 보고 `config.yaml` 의 `parser` 항목을 지정합니다.
   ```yaml
   parser:
     calendar_cell_selector: "table.calendar tbody td"   # 날짜 셀
     date_attr: "data-date"                              # 셀에 날짜 속성이 있으면
     slot_selector: "#timeList li"                       # 날짜 클릭 후 회차 항목
     next_month_selector: "a.btn_next"
     open_keywords: ["예약가능"]
     closed_keywords: ["마감", "휴관"]
     remaining_regex: "잔여\\s*(\\d+)"
   ```
2. **`xhr_*.json` 에 달력 데이터가 있으면** JSON 파서가 자동으로 이를 우선 사용합니다. 키 이름이 특이해 인식되지 않으면 `umppa_monitor/parsers/network.py` 의 키 정규식에 추가하세요.
3. 달력이 **로그인 후에만** 보이면:
   ```bash
   umppa-monitor login -c config.yaml      # 창이 열리면 로그인 후 Enter → storage_state.json 저장
   ```
   그리고 `browser.storage_state: storage_state.json` 지정.
4. 저장된 HTML 로 파서를 오프라인 재검증:
   ```bash
   umppa-monitor parse-file artifacts/inspect/.../page_0.html --type kidscafe
   umppa-monitor parse-file artifacts/inspect/.../slot_0_2026-09-20.html --mode slots --date 2026-09-20
   umppa-monitor parse-file artifacts/inspect/.../page_0.html --type program
   ```
5. `scripts/dump_calendar_cells.py <저장된 html>` 을 실행하면 파서가 후보로 보는 셀의 class/onclick/원문 텍스트를 그대로 출력합니다. `parsed slots` 수가 이상할 때 원인을 빠르게 파악하는 용도입니다 (실제 YF260101 사이트 구조를 확인할 때 이렇게 찾았습니다).

## 4. 실행

```bash
umppa-monitor once -c config.yaml              # 1회 확인 (cron 용)
umppa-monitor run  -c config.yaml              # 상시 감시 (Ctrl+C 로 종료)
umppa-monitor show-state -c config.yaml
umppa-monitor discover-programs -c config.yaml # 프로그램 목록 수집 (웹 앱의 선택지)
umppa-monitor export-status -c config.yaml --out site   # 달력 웹 앱 + data.json 생성
```

`once` / `run` 은 `webstate/prefs.json` 이 있으면 그 조건(요일·날짜·회차·최소 잔여 인원)을 `config.yaml` 의 필터 위에 덮어씁니다. 즉 웹에서 고른 조건이 그대로 감시에 적용됩니다.

백그라운드 상시 실행 예 (Linux/macOS):

```bash
nohup umppa-monitor run -c config.yaml > monitor.log 2>&1 &
```

Windows 는 작업 스케줄러에 `umppa-monitor once` 를 5분 주기로 등록해도 됩니다.

## 5. 웹 앱 (달력에서 날짜·회차 고르기)

`export-status` 가 만드는 정적 사이트는 단순 목록이 아니라 **달력 웹 앱**입니다. 첫 화면에서 당월 현황을 보고, 감시할 조건을 화면에서 직접 고릅니다. YAML 을 편집할 필요가 없습니다.

- **당월 달력 히트맵**: 날짜 × 회차 잔여 인원. 색이 진할수록 자리가 많고, 점(·)은 "확인했지만 빈자리 없음", 빈 칸은 "정보 없음"
- **요일별 빈자리 합계**: 그 달의 요일별 총 잔여. 요일을 누르면 바로 감시 조건에 들어감
- **날짜를 누르면** 그 날의 회차 목록이 열리고, 회차를 눌러 감시 대상에 넣고 뺌. "이 날짜만 감시"도 가능
- **대상 탭**: 키즈카페와 프로그램을 각각 독립된 조건으로 감시 (요일·회차·최소 잔여 인원이 대상별로 따로 저장됨)
- **프로그램 선택**: `discover-programs` 가 수집한 프로그램 목록에서 체크만 하면 다음 확인부터 별도 대상으로 감시
- 다크 모드, 홈 화면에 추가(PWA), 390px 폭 대응

조건 저장 방식은 두 가지입니다.

| 배포 | 조건 저장 | 비고 |
|---|---|---|
| **GitHub Pages 만** | 브라우저(localStorage) | 화면 필터로는 즉시 동작. 알림까지 반영되지는 않음 |
| **+ Vercel API** | 저장소 `webstate/prefs.json` | 웹에서 고른 조건이 다음 감시부터 알림에 그대로 적용 |

### 5-1. 알림 주기 — cron 을 믿으면 안 됩니다

`monitor.yml` 의 cron 은 `*/10`(10분)이지만, **GitHub 는 활동이 적은 저장소의 `schedule` 이벤트를 크게 지연·생략합니다.** 실측하니 10분이 아니라 약 2시간 간격으로 실행됐습니다(run #8~#13). cron 을 더 촘촘히 적어도 같은 제약을 받습니다.

그래서 감시는 **`watch.yml`** 이 담당합니다. 작업 하나가 5시간 35분 동안 살아 있으면서 **내부 루프로 10분마다** 확인하므로, schedule 지연과 무관하게 실제 확인 간격이 유지됩니다. 6시간 cron 이 다음 작업을 띄워 앞 작업을 이어받고, `monitor.yml` 은 백스톱으로 남습니다. 공개 저장소는 Actions 분수가 무제한이라 비용은 늘지 않습니다.

```
watch.yml    (6시간마다 시작 → 5h35m 동안 10분 주기 확인)  ← 알림은 이쪽이 담당
  └─ 매 확인마다 data.json 을 webdata 브랜치에 올림        ← 앱이 먼저 읽는 최신 사본
monitor.yml  (cron, 지연 가능)                             ← 백스톱 + GitHub Pages 게시
diagnose.yml (수동 실행 전용)                              ← 실사이트 마크업 확인
```

비공개 저장소로 바꾸면 Actions 분수(월 2,000분)를 쓰므로 `watch.yml` 을 끄고 `monitor.yml` 만 남기세요.

### 5-2. Vercel 에 배포해 조건까지 반영하기

1. [vercel.com](https://vercel.com) → **Add New → Project** → 이 저장소 import (`vercel.json` 이 빌드를 알아서 처리)
2. 프로젝트 **Settings → Environment Variables** 에 등록
   | 이름 | 값 |
   |---|---|
   | `UMPPA_REPO` | `<계정>/<저장소>` |
   | `UMPPA_GITHUB_TOKEN` | 저장소 **Contents: Read and write** 권한의 fine-grained PAT (즉시 확인까지 쓰려면 **Actions: Read and write** 도) |
   | `UMPPA_PIN` | 조건 저장 시 요구할 비밀번호 (비우면 누구나 저장 가능) |
3. 저장소 **Settings → Secrets and variables → Actions → Variables** 에 `WEB_API_BASE` = 배포된 주소(`https://<앱>.vercel.app`) 등록
4. 다음 감시 실행부터 Pages 의 앱이 이 API 로 조건을 저장합니다

> **`403 forbidden: You don't have permission to create a project`** 이 나오면, 연결된 Vercel 신원에 프로젝트 생성 권한이 없는 상태입니다. 개인 계정으로 직접 로그인해 import 하거나, 팀 소속이라면 Owner 에게 권한을 요청하세요.

**Vercel 없이도 조건을 반영할 수 있습니다.** 저장 API 가 설정되지 않으면 앱이 "고른 조건을 알림에도 반영하기" 카드를 띄웁니다. `조건 복사` → `조건 파일 열기`(`webstate/prefs.json` 편집 화면) → 붙여넣고 Commit 하면 다음 확인부터 적용됩니다.

배포된 앱은 빈자리 데이터를 `webdata` 브랜치의 `data.json` 에서 먼저 읽고, 실패하면 GitHub Pages 사본으로 되돌립니다. 감시 자체는 GitHub Actions 에 남겨 두어 무료 인스턴스가 잠들 걱정이 없습니다.

### 5-3. 다른 호스팅

자세한 절차는 **[docs/DEPLOY.md](docs/DEPLOY.md)** 를 보세요.

| 방식 | 특징 |
|---|---|
| **GitHub Actions + GitHub Pages (기본)** | 서버·카드 불필요. 10분마다 확인 → ntfy/텔레그램 푸시 → 달력 앱을 `https://<계정>.github.io/<저장소>/` 에 게시 |
| **Render / Koyeb 무료 Docker** | 감시까지 한 프로세스에서 도는 자립형(`umppa-monitor serve`). 무료 인스턴스는 무활동 시 잠들므로 UptimeRobot 으로 `/healthz` 핑 |

관리자용 폼 대시보드(대상 추가·중지, 지금 확인, 로그)를 로컬에서 띄우려면:

```bash
UMPPA_WEB_PASSWORD=1234 umppa-monitor serve -c config.yaml --port 8000
# 휴대폰과 같은 Wi-Fi 에서 http://<PC IP>:8000 접속 → "홈 화면에 추가"
```

## 5-1. GitHub Actions 로 실행 (PC 없이)

`.github/workflows/monitor.yml` 이 10분마다 `umppa-monitor once` 를 실행하고 상태를 캐시에 보관합니다.

1. 저장소 **Settings → Secrets and variables → Actions** 에 알림 토큰 등록
   (`UMPPA_TELEGRAM_TOKEN`, `UMPPA_TELEGRAM_CHAT_ID`, `UMPPA_DISCORD_WEBHOOK`, `UMPPA_SLACK_WEBHOOK`, `UMPPA_NTFY_TOPIC` 중 사용하는 것)
2. `config.yaml` 을 커밋하거나(토큰은 `${ENV}` 참조만), **Variables** 에 `MONITOR_CONFIG_B64` = `base64 -w0 config.yaml` 결과 등록
3. Actions 탭에서 워크플로 활성화 후 `Run workflow` 로 수동 1회 실행해 로그 확인

주의: GitHub cron 은 최소 5분·지연 가능. 취소표를 빠르게 잡으려면 로컬 상시 실행을 권장합니다.

## 6. 동작 원리 요약

```
[감시 → 웹]
브라우저로 페이지 로드 → (달력) 다음달 이동·날짜 클릭으로 회차 수집, XHR JSON 캡처
→ 파서가 (날짜, 회차, 상태, 잔여, 정원) 으로 정규화
→ 필터 통과분: 이전 스냅샷과 비교해 새로 열린 슬롯만 알림 (state/)
→ 필터 이전 전체: state/webdata.json → data.json → 달력 앱이 월 전체를 그림

[웹 → 감시]
앱에서 요일·날짜·회차 선택 → /api/prefs (Vercel) → webstate/prefs.json 커밋
→ 다음 `once` 실행이 이 조건을 config 필터에 덮어씀 → 알림 범위가 바뀜
```

달력에 "빈자리 없는 날"까지 보이려면 필터 이전 데이터가 필요해, 알림용 스냅샷과 화면용 스냅샷을 따로 둡니다.

상태 판별: 잔여 숫자 > 닫힘 키워드(마감·불가·휴관·대기) > 열림 키워드(예약가능·신청) > 클릭 가능 여부.

## 7. 테스트

```bash
python -m pytest -q
```

## 8. 프로젝트 구조

```
umppa_monitor/
  cli.py            명령어 (run / once / serve / export-status / discover-programs /
                    inspect / parse-file / test-notify / login / show-state)
  webapp/           달력 웹 앱 (index.html, app.js, style.css, sw.js, manifest, icon) — 정적, 빌드 불필요
                    sw.js 는 화면 파일만 캐시한다. 현황은 캐시하지 않고 앱이 마지막 값을
                    "저장된 현황"이라고 밝혀 보여주므로 오래된 값을 새 것처럼 띄우지 않는다
  webdata.py        웹 앱이 읽는 data.json 생성 + 웹에서 고른 감시 조건(prefs) 적용
  web.py            관리자용 폼 대시보드 (FastAPI), service.py 백그라운드 감시, config_store.py 설정 편집
  render_html.py    대시보드·요약 페이지 HTML
  config.py         YAML 설정
  models.py         Target / Slot
  browser.py        Playwright 수집 + XHR 캡처 + inspect 덤프 + 프로그램 목록 수집
  scanner.py        수집 결과 → Slot 병합·필터
  parsers/          calendar.py (달력·회차 DOM), program.py (상세·목록), network.py (JSON), common.py (휴리스틱)
  state.py          스냅샷 저장·diff
  scheduler.py      감시 루프
  notify/           채널 구현 및 메시지 포맷
api/prefs.js        웹에서 고른 감시 조건을 webstate/prefs.json 으로 커밋하는 Vercel 함수
vercel.json, scripts/vercel-build.sh   Vercel 배포 설정
webstate/prefs.json 현재 적용 중인 감시 조건 (웹 앱이 갱신)
tests/              픽스처 기반 단위 테스트
docs/PLAN.md        개발 계획서, docs/DEPLOY.md 무료 배포 가이드
Dockerfile, render.yaml, koyeb.yaml   무료 Docker 호스팅용
.github/workflows/  monitor.yml (cron + Pages 게시), ci.yml (테스트)
```

내보낸 사이트 구성: `index.html`(달력 앱) · `data.json`(달력 데이터) · `config.js`(데이터/API 주소) ·
`summary.html`(자바스크립트 없이 보는 요약) · `status.json`(기존 연동용)

## 9. 유의사항

- 이 도구는 **알림만** 보냅니다. 예약은 직접 하셔야 하며 자동 예약 기능은 의도적으로 넣지 않았습니다.
- 공공 사이트에 부담을 주지 않도록 60초 미만 주기는 권장하지 않습니다.
- 시설 ID 는 예약 페이지 URL 의 `q_fcltyId`, 프로그램 번호는 `q_progrmSn` 값입니다. 시설 목록은 [서울 열린데이터광장](https://data.seoul.go.kr/dataList/OA-21716/S/1/datasetView.do)에서도 확인할 수 있습니다.
