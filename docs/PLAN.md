# 서울형 키즈카페 빈자리 감시 시스템 — 개발 계획서

작성일: 2026-09-13

## 1. 요약

- **목표**: 서울시 우리동네키움포털(umppa.seoul.go.kr)의 서울형 키즈카페 **회차 예약(달력)** 과 **프로그램 예약** 페이지를 주기적으로 확인해, 마감/불가였던 자리가 **예약 가능으로 바뀌는 순간** 알림을 보낸다.
- **대상 선택**: 설정 파일에서 `type: kidscafe`(시설 ID) 또는 `type: program`(프로그램 번호)을 골라 감시한다. 두 종류를 동시에 여러 개 등록할 수 있다.
- **핵심 설계 원칙**: (1) 취소표는 언제든 나오므로 *상태 전환*만 알린다 (2) 공공 사이트에 부담을 주지 않는 주기·지터·야간 중지 (3) 사이트 마크업을 사전에 확정할 수 없으므로 **진단(inspect) 모드 + 휴리스틱 파서 + 설정으로 정밀화** 하는 3단 구조.

## 2. 배경 조사 (출처)

| 항목 | 내용 | 출처 |
|---|---|---|
| 예약 페이지 | `/icare/user/kidsCafeResve/BD_selectKidsCafeResveCal.do?q_fcltyId=<시설ID>` — 월별 달력에서 일자·회차 선택 후 예약 | [우리동네키움포털 키즈카페 예약](https://umppa.seoul.go.kr/icare/user/kidsCafe/BD_selectKidsCafeList.do) |
| 프로그램 페이지 | `/icare/user/kidsCafeProgrm/BD_selectKidsCafeProgrm.do?q_progrmSn=<번호>` (상세), `BD_selectKidsCafeProgrmList.do` (목록). 프로그램은 회차 예약과 별도로 신청 | [프로그램 예약](https://umppa.seoul.go.kr/icare/user/kidsCafeProgrm/BD_selectKidsCafeProgrmList.do) |
| 회차 구성(일반적) | 평일 3회차(10:00~12:00, 13:30~15:30, 16:00~18:00), 주말 4회차(09:00~10:50, 11:00~12:50, 14:00~15:50, 16:00~17:50). 시설별 상이 | [서울시 미디어허브](https://mediahub.seoul.go.kr/archives/2014750) |
| 예약 개시 | 매주 화요일 예약창 개시, 2026-04-14부터 4개 권역 순차 오픈, 15:00 이후 전체 오픈 | [키즈카페 소개](https://umppa.seoul.go.kr/icare/dolbomMENU5/dolbomMENU5_1.jsp) |
| 빈자리 | 대기 신청 제도 폐지, 취소로 빈자리 발생 시 수시 온라인 예약 가능 → **감시 시스템의 필요성** | 동일 |
| 시설 목록 | 서울 열린데이터광장 "서울형 키즈카페 시설현황정보" | [data.seoul.go.kr OA-21716](https://data.seoul.go.kr/dataList/OA-21716/S/1/datasetView.do) |

> 제약: 본 개발 환경에서는 조직 네트워크 정책으로 `umppa.seoul.go.kr` 접속이 차단되어 **실제 HTML/AJAX 구조를 직접 확인하지 못했다.** 따라서 파서는 한국 공공 예약 시스템에서 흔한 패턴(잔여 N, N/정원, 예약가능/마감/휴관, 회차·시간 표기, disabled 라디오/버튼, JSON 키 `resveDe/psncpa/nmpr/rmndr/…At`)을 넓게 인식하도록 만들고, 사용자가 실제 환경에서 `umppa-monitor inspect` 를 1회 실행해 구조를 확인한 뒤 필요 시 `config.parser` 로 선택자를 지정하는 절차를 둔다.

## 3. 개발 환경

| 구분 | 선택 | 이유 |
|---|---|---|
| 언어 | Python 3.11+ | 스크래핑·알림 라이브러리 성숙, 유지보수 용이 |
| 브라우저 자동화 | Playwright (Chromium, headless) | 달력이 JS/AJAX 로 그려지거나 날짜 클릭 후 회차가 뜨는 구조에 대응. XHR 응답을 그대로 가로챌 수 있어 HTML 파싱보다 안정적 |
| HTML 파싱 | BeautifulSoup4 + lxml | 휴리스틱 셀렉터 작성 편의 |
| 설정 | YAML + `${ENV}` 치환 | 토큰을 코드/설정에 넣지 않고 환경변수·GitHub Secrets 사용 |
| 알림 | Telegram / Discord / Slack / ntfy / Email / Console | 별도 서버 없이 무료로 모바일 푸시 가능 (Telegram, ntfy 권장) |
| 실행 방식 | (A) 로컬 PC·라즈베리파이 상시 `run` (B) GitHub Actions cron `once` | A 는 분 단위 정밀 감시, B 는 PC 없이 10분 간격 감시 |
| 테스트 | pytest + 고정 HTML/JSON 픽스처 | 사이트 접속 없이 파서·diff·알림 포맷 검증 |

## 4. 아키텍처

```
config.yaml ─▶ config.py ─▶ scheduler.run_loop
                                │  (interval + jitter, quiet hours, backoff)
                                ▼
                    browser.fetch_target  (Playwright)
                      ├─ kidscafe: 달력 로드 → 다음달 이동(months_ahead) → 날짜 클릭(click_dates) → 회차 HTML 수집
                      ├─ program : 상세 페이지 로드
                      └─ 모든 XHR/fetch 응답 캡처 (JSON 이면 파싱)
                                │ FetchResult(pages, slot_pages, network)
                                ▼
                    scanner.slots_from_result
                      ├─ parsers/calendar.py  (달력 셀 / 회차 목록 DOM 휴리스틱)
                      ├─ parsers/program.py   (정원/신청인원/버튼 상태, 회차 표)
                      └─ parsers/network.py   (JSON 키 패턴)
                                │ list[Slot]  (date, session, status, remaining, capacity)
                                ▼
                    scanner.apply_filters (dates / weekdays / sessions / min_remaining)
                                ▼
                    state.compute_diff  (이전 스냅샷 대비 opened / closed / still_open)
                                ▼
                    notify.*  (console, telegram, discord, slack, ntfy, email)
                                ▼
                    state.save (state/<target>.json)
```

### 상태 판별 규칙 (parsers/common.classify_text)
1. 잔여 숫자가 있으면 숫자 우선 (`잔여 N`, `N/정원`, `정원 X · 신청 Y` → X−Y, 표 헤더 기반 열 매핑)
2. 닫힘 키워드(마감·불가·휴관·대기·만석·예약완료…) > 열림 키워드(예약가능·신청가능·접수중…)
3. 키워드가 없으면 클릭 가능 요소(a/button/활성 input) 유무
4. 그래도 없으면 `unknown` (알림 대상 아님, 로그로만 남김)

### 알림 규칙
- `opened`: 직전 스냅샷에 없었거나 열려 있지 않던 슬롯이 열림 → 알림 (대상 필터·`min_remaining` 통과 시)
- `still_open` + `renotify_after_min` > 0 → 지정 시간 경과 시 재알림
- `closed` + `notify_on_close: true` → 마감 알림 (기본 꺼짐)
- 첫 실행은 현재 열려 있는 모든 슬롯을 한 번 알린다 (이후는 전환만)

## 5. 단계별 계획 및 상태

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 사이트 조사, 요구사항·환경 정의, 계획 수립 | 완료 (사이트 직접 접근은 차단되어 2차 자료 기반) |
| 2 | 도메인 모델·설정 로더 | 완료 |
| 3 | Playwright 수집기 (달력/프로그램, 월 이동, 날짜 클릭, XHR 캡처, inspect 덤프) | 완료 (실사이트 검증 필요) |
| 4 | 파서 3종 (DOM 달력·회차, 프로그램, JSON) | 완료, 픽스처 테스트 통과 |
| 5 | 상태 저장·diff·알림 채널 6종·스케줄러·CLI | 완료 |
| 6 | 테스트(pytest) 및 CI | 완료 |
| 7 | GitHub Actions cron 실행 워크플로 | 완료 |
| 8 | **실사이트 진단(inspect) → 파서 정밀화** | 사용자 환경에서 수행 필요 (README 3단계 참고) |
| 9 | 운영: 알림 채널 연결, 대상 추가, 주기 조정 | 사용자 |

## 6. 리스크와 대응

| 리스크 | 대응 |
|---|---|
| 실제 마크업이 휴리스틱과 다름 | `inspect` 로 HTML/XHR 덤프 → `config.parser` 선택자·키워드·정규식 지정. `parse-file` 로 오프라인 재검증 |
| 달력이 로그인 후에만 보임 | `umppa-monitor login` 으로 브라우저 로그인 쿠키(storage_state) 저장 후 재사용 |
| 봇 차단·과도한 요청 | 기본 5분 주기 + 지터, 야간 중지, 실패 시 지수 백오프, 실제 브라우저 UA. 60초 미만 주기는 권장하지 않음 |
| GitHub Actions cron 지연 | 정밀 감시는 로컬 상시 실행 권장. Actions 는 보조 수단 |
| 알림 채널 장애 | 채널별 예외 격리(safe_send), 여러 채널 병행 가능 |
| 사이트 개편 | 파서를 모듈로 분리, 픽스처만 갱신하면 테스트로 회귀 확인 |

## 7. 운영·윤리 지침
- 본 도구는 **빈자리 알림**만 수행하며 자동 예약(매크로)은 구현하지 않는다. 예약은 사람이 직접 수행한다.
- 요청 주기를 과도하게 짧게 설정하지 않는다 (공공 서비스 부하 및 이용약관 고려).
- 개인 로그인 정보는 저장하지 않으며, 선택적으로 저장하는 쿠키 파일은 `.gitignore` 로 제외된다.
