# umppa-monitor — 서울형 키즈카페 빈자리 감시·알림

서울시 우리동네키움포털(umppa.seoul.go.kr)의 **서울형 키즈카페 회차 예약** 또는 **키즈카페 프로그램 예약** 페이지를 주기적으로 확인해, 마감이던 자리가 **예약 가능으로 바뀌면** 텔레그램·디스코드·슬랙·ntfy·이메일로 알려줍니다.

- 감시 대상은 설정 파일에서 `type: kidscafe`(시설 ID) / `type: program`(프로그램 번호) 중 골라 여러 개 등록
- 요일·날짜·회차·최소 잔여 인원 필터
- 상태 전환(마감→가능)만 알림, 재알림·마감 알림 옵션
- 로컬 상시 실행 또는 GitHub Actions 10분 주기 실행
- 계획서: [docs/PLAN.md](docs/PLAN.md)

> **중요**: 이 코드는 사이트 HTML 을 직접 확인하지 못한 환경에서 작성되었습니다(네트워크 정책 차단). 파서는 공공 예약 사이트의 흔한 패턴을 넓게 인식하지만, 처음 실행 시 반드시 아래 **3단계(inspect)** 로 실제 구조를 확인하세요.

## 1. 설치

```bash
git clone <this repo> && cd youido-english
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
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

## 4. 실행

```bash
umppa-monitor once -c config.yaml     # 1회 확인 (cron 용)
umppa-monitor run  -c config.yaml     # 상시 감시 (Ctrl+C 로 종료)
umppa-monitor show-state -c config.yaml
```

백그라운드 상시 실행 예 (Linux/macOS):

```bash
nohup umppa-monitor run -c config.yaml > monitor.log 2>&1 &
```

Windows 는 작업 스케줄러에 `umppa-monitor once` 를 5분 주기로 등록해도 됩니다.

## 5. GitHub Actions 로 실행 (PC 없이)

`.github/workflows/monitor.yml` 이 10분마다 `umppa-monitor once` 를 실행하고 상태를 캐시에 보관합니다.

1. 저장소 **Settings → Secrets and variables → Actions** 에 알림 토큰 등록
   (`UMPPA_TELEGRAM_TOKEN`, `UMPPA_TELEGRAM_CHAT_ID`, `UMPPA_DISCORD_WEBHOOK`, `UMPPA_SLACK_WEBHOOK`, `UMPPA_NTFY_TOPIC` 중 사용하는 것)
2. `config.yaml` 을 커밋하거나(토큰은 `${ENV}` 참조만), **Variables** 에 `MONITOR_CONFIG_B64` = `base64 -w0 config.yaml` 결과 등록
3. Actions 탭에서 워크플로 활성화 후 `Run workflow` 로 수동 1회 실행해 로그 확인

주의: GitHub cron 은 최소 5분·지연 가능. 취소표를 빠르게 잡으려면 로컬 상시 실행을 권장합니다.

## 6. 동작 원리 요약

```
브라우저로 페이지 로드 → (달력) 다음달 이동·날짜 클릭으로 회차 수집, XHR JSON 캡처
→ 파서가 (날짜, 회차, 상태, 잔여, 정원) 으로 정규화 → 필터 → 이전 스냅샷과 비교
→ 새로 열린 슬롯만 알림 → state/ 에 스냅샷 저장
```

상태 판별: 잔여 숫자 > 닫힘 키워드(마감·불가·휴관·대기) > 열림 키워드(예약가능·신청) > 클릭 가능 여부.

## 7. 테스트

```bash
python -m pytest -q
```

## 8. 프로젝트 구조

```
umppa_monitor/
  cli.py            명령어 (run / once / inspect / parse-file / test-notify / login / show-state)
  config.py         YAML 설정
  models.py         Target / Slot
  browser.py        Playwright 수집 + XHR 캡처 + inspect 덤프
  scanner.py        수집 결과 → Slot 병합·필터
  parsers/          calendar.py (달력·회차 DOM), program.py, network.py (JSON), common.py (휴리스틱)
  state.py          스냅샷 저장·diff
  scheduler.py      감시 루프
  notify/           채널 구현 및 메시지 포맷
tests/              픽스처 기반 단위 테스트
docs/PLAN.md        개발 계획서
.github/workflows/  monitor.yml (cron), ci.yml (테스트)
```

## 9. 유의사항

- 이 도구는 **알림만** 보냅니다. 예약은 직접 하셔야 하며 자동 예약 기능은 의도적으로 넣지 않았습니다.
- 공공 사이트에 부담을 주지 않도록 60초 미만 주기는 권장하지 않습니다.
- 시설 ID 는 예약 페이지 URL 의 `q_fcltyId`, 프로그램 번호는 `q_progrmSn` 값입니다. 시설 목록은 [서울 열린데이터광장](https://data.seoul.go.kr/dataList/OA-21716/S/1/datasetView.do)에서도 확인할 수 있습니다.
