# 무료 퍼블리싱 및 모바일 사용 가이드

작성일: 2026-09-13

## 1. 요약

| 방식 | 비용 | 카드 | 서버 | 모바일에서 하는 일 | 추천 |
|---|---|---|---|---|---|
| **A. GitHub Actions + GitHub Pages + 텔레그램/ntfy** | 무료 (공개 저장소는 Actions 분수 무제한) | 불필요 | 불필요 | 푸시 알림 수신, Pages 상태 페이지 확인, GitHub 앱에서 `config.yaml` 수정 | **기본 추천** |
| **B. Render 무료 웹 서비스 (Docker)** | 무료 750시간/월 | 정책상 요구될 수 있음 | Render 가 운영 | 로그인 후 대시보드에서 대상 추가·중지, "지금 확인", 로그 열람 | 대시보드가 필요할 때 |
| C. Koyeb 무료 인스턴스 (Docker) | 무료 1개 | 보통 불필요 | Koyeb 가 운영 | B 와 동일 | B 의 대안 |
| D. Hugging Face Spaces (Docker) | 무료 CPU basic | 불필요 | HF 가 운영 | B 와 동일 | 정책 변동 잦음 (아래 주의) |

- 이 저장소는 **공개(public)** 이므로 A 방식의 GitHub Actions 사용량은 무제한입니다. 비공개로 바꾸면 월 2,000분 한도가 적용됩니다.
- 어떤 방식이든 **푸시 알림은 텔레그램 또는 ntfy** 로 받습니다. 두 서비스 모두 무료이며 앱만 설치하면 됩니다.

출처
- GitHub Actions 요금: [GitHub Docs - About billing for GitHub Actions](https://docs.github.com/billing/managing-billing-for-github-actions/about-billing-for-github-actions), [GitHub Actions 2026 pricing changes](https://github.com/resources/insights/2026-pricing-changes-for-github-actions)
- Render 무료 티어(750시간, 15분 무활동 시 중지): [Render - Platforms with a real free tier (2026)](https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026)
- Hugging Face Spaces 무료 CPU 48시간 무활동 시 슬립: [HF Docs - Spaces Overview](https://huggingface.co/docs/hub/en/spaces-overview) (Docker Space 무료 여부는 시점에 따라 달라 확인 필요)

## 2. 방식 A: GitHub Actions + GitHub Pages (기본)

### 2.1 동작
1. `.github/workflows/monitor.yml` 이 10분마다 `umppa-monitor once` 를 실행합니다.
2. 새로 열린 자리는 텔레그램/ntfy/디스코드/슬랙으로 즉시 푸시됩니다.
3. 마지막 결과가 정적 페이지로 GitHub Pages 에 게시됩니다. 휴대폰 브라우저에서 열고 "홈 화면에 추가" 하면 앱처럼 쓸 수 있습니다.
4. 이전 실행 상태는 Actions 캐시에 보관되어 상태 전환(마감 → 가능)만 알립니다.

### 2.2 설정 절차 (휴대폰 GitHub 앱 또는 웹에서 가능)
1. **알림 채널 만들기** (택 1)
   - ntfy: 휴대폰에 ntfy 앱 설치 → 아무도 못 맞출 긴 토픽 이름 구독 (예: `kidscafe-a8f3k2z9`)
   - 텔레그램: @BotFather 로 봇 생성 → 봇에게 아무 말이나 보냄 → `https://api.telegram.org/bot<토큰>/getUpdates` 에서 `chat.id` 확인
2. **Secrets 등록**: 저장소 → Settings → Secrets and variables → Actions → New repository secret
   - `UMPPA_NTFY_TOPIC` 또는 `UMPPA_TELEGRAM_TOKEN` + `UMPPA_TELEGRAM_CHAT_ID`
3. **config.yaml 만들기**: 저장소 루트에 `config.yaml` 을 추가 (공개 저장소이므로 **토큰은 절대 직접 쓰지 말고** `${ENV}` 참조만 사용)
   ```yaml
   targets:
     - type: kidscafe
       id: YF260101
       name: 여의도점
       weekdays: [5, 6]
   notifiers:
     - type: ntfy
       topic: ${UMPPA_NTFY_TOPIC}
   schedule:
     quiet_hours: ["00:30-06:30"]
   ```
   config.yaml 을 커밋하기 싫으면 Settings → Variables 에 `MONITOR_CONFIG_B64` 로 base64 인코딩 값을 등록해도 됩니다.
4. **Pages 켜기**: Settings → Pages → Build and deployment → Source: **GitHub Actions**
5. Actions 탭 → `kidscafe-vacancy-monitor` → **Run workflow** 로 1회 실행 → 로그와 알림 확인
6. 상태 페이지 주소: `https://<계정>.github.io/<저장소명>/` (이 저장소 기준 `https://khrias86-oss.github.io/youido-english/`)

### 2.3 모바일에서 대상 바꾸기
GitHub 모바일 앱(또는 브라우저)에서 `config.yaml` 을 열어 `targets` 를 수정·커밋하면 다음 실행부터 반영됩니다.

### 2.4 제약
- GitHub cron 은 최소 5분 간격이며 혼잡 시 수 분에서 수십 분 지연될 수 있습니다.
- 각 실행이 1~2분 걸립니다(크로미움 캐시 사용 시 단축). 취소표를 초 단위로 잡아야 한다면 방식 B 나 로컬 상시 실행을 병행하세요.
- Pages 상태 페이지는 공개됩니다. 시설 ID 와 빈자리 현황만 노출되며 개인 정보는 없습니다.

## 3. 방식 B: Render 무료 웹 서비스 (대시보드)

### 3.1 동작
Docker 컨테이너 하나가 **감시 루프 + 모바일 대시보드**를 함께 실행합니다. 대시보드에서 대상 추가·중지·삭제, 주기 변경, "지금 확인", 알림 테스트, 로그 열람이 가능합니다.

### 3.2 절차
1. https://render.com 가입 → New → **Blueprint** → 이 저장소 선택 (`render.yaml` 자동 인식)
2. 환경변수 입력: `UMPPA_WEB_PASSWORD`(대시보드 비밀번호), 알림 토큰(`UMPPA_NTFY_TOPIC` 등)
3. 배포가 끝나면 `https://umppa-monitor-xxxx.onrender.com` 접속 → 로그인 → 대상 관리에서 시설 ID 추가
4. **무료 인스턴스는 15분간 접속이 없으면 잠듭니다.** 잠들면 감시도 멈추므로, 무료 외부 핑 서비스로 5분마다 `/healthz` 를 호출하세요.
   - [UptimeRobot](https://uptimerobot.com) (무료, 5분 간격) 또는 [cron-job.org](https://cron-job.org) (무료, 1분 간격)
   - 모니터 URL: `https://<서비스>.onrender.com/healthz`
5. 휴대폰 브라우저에서 대시보드를 열고 "홈 화면에 추가"

### 3.3 제약
- 무료 인스턴스는 메모리 512MB, CPU 0.1 이라 한 번 확인에 30초~1분 걸릴 수 있습니다.
- 디스크가 영구적이지 않아 **재배포하면 대시보드에서 바꾼 설정이 초기화**됩니다. 확정된 설정은 `MONITOR_CONFIG_B64` 환경변수(또는 커밋한 config.yaml)에 넣어 두세요.
- Render 정책상 카드 등록을 요구할 수 있습니다. 카드 없이 쓰려면 Koyeb(방식 C)로 같은 Dockerfile 을 배포하세요.

## 4. 방식 C: Koyeb
1. https://www.koyeb.com 가입 → Create Service → GitHub 저장소 선택 → Builder: **Dockerfile**
2. Instance: **Free**, Port: 8000, Health check: `/healthz`
3. 환경변수는 방식 B 와 동일. `koyeb.yaml` 참고.

## 5. 방식 D: Hugging Face Spaces
1. New Space → SDK: **Docker** → 이 저장소 내용을 Space 저장소에 push
2. Space README 상단에 아래 front matter 추가:
   ```
   ---
   title: umppa-monitor
   sdk: docker
   app_port: 8000
   ---
   ```
3. Settings → Variables and secrets 에 `UMPPA_WEB_PASSWORD`, 알림 토큰 등록. Space 는 **Private** 로 두세요.
4. 48시간 무활동 시 슬립되므로 UptimeRobot 으로 `/healthz` 를 주기 호출하세요. Docker Space 의 무료 제공 여부는 HF 정책 변경이 잦으니 생성 시 화면에서 확인하세요.

## 6. 로컬 Docker 실행 (참고)
```bash
docker build -t umppa-monitor .
docker run -p 8000:8000 -v $PWD/data:/data -e UMPPA_WEB_PASSWORD=1234 -e UMPPA_NTFY_TOPIC=my-topic umppa-monitor
# http://localhost:8000
```

## 7. 보안 메모
- 공개 저장소에 토큰을 커밋하지 마세요. Secrets/환경변수만 사용합니다.
- 대시보드는 반드시 `UMPPA_WEB_PASSWORD` 를 설정하세요. 미설정 시 인증이 꺼지며 로컬 전용입니다.
- 이 도구는 알림만 보내며 자동 예약은 하지 않습니다.
