# SentiTrack Deployment Fix List

배포 점검 결과 기준으로 지금 수정이 필요한 항목만 정리한 체크리스트입니다.

## High

- [ ] `gateway/src/jwt.ts`
  - 문제: `JWT_SECRET`이 없을 때 `"dev-secret-change-in-production"` 기본값으로 동작합니다.
  - 이유: 운영 환경변수 주입이 실패해도 서버가 뜨며, 약한/공유된 JWT 서명키로 인증 토큰이 발급될 수 있습니다.
  - 수정 추천: 운영 필수 환경변수 검증을 추가하고, `JWT_SECRET` 누락 시 서버 시작을 실패시키기.

- [ ] `docker-compose.prod.yml`, `.github/workflows/deploy.yml`
  - 문제: `DB_USER`, `DB_PASSWORD`, `JWT_SECRET`, `RESEND_API_KEY`가 비어 있어도 배포가 계속 진행될 수 있습니다.
  - 이유: Compose는 미설정 변수를 빈 문자열로 치환할 수 있어 DB 연결 실패, 인증 취약점, 메일 발송 실패가 운영에서 뒤늦게 발생합니다.
  - 수정 추천: 배포 스크립트에서 secret 누락 검증을 추가하고, Compose에도 필수 변수 문법을 적용하기.

- [ ] `gateway/migrations/001_init.sql`
  - 문제: 운영 DB 초기화 SQL에 `DROP TABLE`이 포함되어 있습니다.
  - 이유: 볼륨 재생성, 수동 실행, 복구 작업 중 운영 데이터가 삭제될 수 있습니다.
  - 수정 추천: 운영용 migration에서 destructive SQL 제거 또는 별도 seed/init 파일로 분리하기.

- [ ] `gateway/migrations/002_add_users.sql`, `gateway/migrations/003_add_scent_category.sql`
  - 문제: Docker init script 방식은 기존 DB에는 재실행되지 않습니다.
  - 이유: 이미 배포된 DB에 `user_id`, `scent_category` 컬럼이 없으면 API가 운영에서만 실패할 수 있습니다.
  - 수정 추천: 실제 운영 DB에 적용 가능한 idempotent migration 절차를 만들고 배포 파이프라인에 반영하기.

- [ ] `docker-compose.prod.yml`
  - 문제: MySQL root password와 앱 유저 password가 같은 `${DB_PASSWORD}`입니다.
  - 이유: 앱 계정 비밀번호 유출 시 root 접근 위험까지 함께 커집니다.
  - 수정 추천: `MYSQL_ROOT_PASSWORD`와 앱용 `MYSQL_PASSWORD`를 별도 secret으로 분리하기.

- [ ] `frontend/lib/AuthContext.tsx`
  - 문제: JWT를 `localStorage`에 저장합니다.
  - 이유: XSS 발생 시 토큰 탈취가 쉽습니다.
  - 수정 추천: HttpOnly Secure SameSite cookie 기반 인증으로 전환하거나, 최소한 CSP와 토큰 수명 단축을 함께 적용하기.

- [ ] `gateway/src/authRoutes.ts`
  - 문제: 이메일 인증 코드가 `Math.random()` 기반이고, 인증/로그인/회원가입 요청 제한이 없습니다.
  - 이유: 6자리 인증 코드 brute force와 메일 발송 남용 위험이 있습니다.
  - 수정 추천: `crypto.randomInt` 사용, rate limit, 인증 코드 시도 횟수 제한, 재발송 제한 추가하기.

- [ ] `docker-compose.prod.yml`
  - 문제: `nginx-proxy`, `letsencrypt` 컨테이너가 Docker socket을 마운트합니다.
  - 이유: 프록시/인증서 컨테이너가 침해되면 호스트 Docker 제어권으로 이어질 수 있습니다.
  - 수정 추천: socket 노출을 최소화하거나 Docker socket proxy, 별도 reverse proxy 구성, 권한 제한 방식을 검토하기.

## Medium

- [ ] `python-inference/main.py`
  - 문제: 모델을 이미지 빌드 시점이 아니라 컨테이너 시작 시 다운로드/로드합니다.
  - 이유: 운영 서버 outbound 네트워크, Hugging Face rate limit, 다운로드 지연에 따라 inference 컨테이너가 늦게 뜨거나 실패할 수 있습니다.
  - 수정 추천: 모델을 이미지에 사전 캐싱하거나 persistent cache volume과 startup timeout 전략을 정리하기.

- [ ] `docker-compose.prod.yml`
  - 문제: gateway가 inference의 `service_started`만 기다립니다.
  - 이유: inference 컨테이너가 시작됐지만 모델 로딩이 끝나지 않은 상태에서 리뷰 요청이 들어오면 502/503이 발생할 수 있습니다.
  - 수정 추천: `condition: service_healthy`로 바꾸고 inference healthcheck가 모델 로딩 상태를 반영하도록 유지하기.

- [ ] `gateway/src/server.ts`
  - 문제: inference 호출에 timeout/abort 처리가 없습니다.
  - 이유: 모델 서버 응답이 멈추면 gateway 요청이 오래 붙잡힐 수 있습니다.
  - 수정 추천: `AbortController` 기반 timeout과 재시도/실패 응답 정책 추가하기.

- [ ] `python-inference/main.py`
  - 문제: MLflow에 사용자 리뷰 일부를 `input_text`로 저장합니다.
  - 이유: 리뷰에 개인정보가 포함될 수 있어 로그/실험 기록에 개인정보가 남을 수 있습니다.
  - 수정 추천: 원문 저장 제거, 해시/길이/언어 등 비식별 메타데이터만 기록하기.

- [ ] `gateway/src/email.ts`
  - 문제: `RESEND_API_KEY` 필수 검증이 없습니다.
  - 이유: 서버는 뜨지만 회원가입 메일 발송 시점에 실패합니다.
  - 수정 추천: 서버 시작 시 API key 누락을 검증하고 명확한 로그와 함께 종료하기.

- [ ] `gateway/src/db.ts`
  - 문제: DB 환경변수 기본값이 `shared-db`, `root`, 빈 password입니다.
  - 이유: 운영 설정 누락을 조기 실패시키지 않고 엉뚱한 DB 연결/인증 실패로 이어질 수 있습니다.
  - 수정 추천: 운영 필수 DB 환경변수 검증을 추가하고 위험한 기본값 제거하기.

- [ ] `frontend/app/api/auth/login/route.ts`, `frontend/app/api/products/[id]/reviews/route.ts`
  - 문제: `request.json()`이 `try` 바깥에서 실행됩니다.
  - 이유: 잘못된 JSON 요청이 들어오면 일관된 400 응답 대신 런타임 에러가 날 수 있습니다.
  - 수정 추천: JSON 파싱을 `try` 안으로 옮기고 malformed body에 400 응답 반환하기.

- [ ] `frontend/app/api/reviews/route.ts`
  - 문제: gateway에 없는 `/api/reviews`를 호출합니다.
  - 이유: 현재 미사용이면 죽은 코드이고, 사용되면 404를 반환합니다.
  - 수정 추천: 사용하지 않는 route면 삭제하고, 필요한 기능이면 gateway에 대응 API를 추가하기.

- [ ] `docker-compose.prod.yml`, `.github/workflows/deploy.yml`
  - 문제: 운영 이미지가 모두 `latest` 태그입니다.
  - 이유: 어떤 커밋 이미지가 운영 중인지 추적하기 어렵고, 롤백/재현성이 약합니다.
  - 수정 추천: commit SHA 태그를 함께 push하고, 배포 시 SHA 태그를 사용하기.

- [ ] `frontend/Dockerfile`, `gateway/Dockerfile`
  - 문제: Docker build에서 `npm install`을 사용합니다.
  - 이유: lockfile 기반 재현성이 약합니다.
  - 수정 추천: `package-lock.json`도 먼저 복사하고 `npm ci`로 설치하기.

- [ ] `frontend/.dockerignore`, `gateway/.dockerignore`, `python-inference/.dockerignore`
  - 문제: Docker context 제외 파일 설정이 없습니다.
  - 이유: 로컬 빌드 시 `node_modules`, `.next`, `dist`, cache, log 등이 context에 포함될 수 있습니다.
  - 수정 추천: 서비스별 `.dockerignore` 추가하기.

## Low

- [ ] `.claude/settings.local.json`
  - 문제: 로컬 도구 권한 설정 파일이 Git에 추적 중입니다.
  - 이유: 실제 secret은 아니지만 개인 환경, 이메일, 허용 명령이 저장소에 남습니다.
  - 수정 추천: Git 추적 제거 후 `.gitignore`에 `.claude/settings.local.json` 추가하기.

- [ ] `docker-compose.prod.yml`
  - 문제: `ALLOWED_ORIGIN`, `VIRTUAL_HOST`, `LETSENCRYPT_HOST`, `RESEND_FROM_ADDRESS` 등이 운영 도메인에 하드코딩되어 있습니다.
  - 이유: 도메인 변경, staging, `www` 추가 시 직접 파일 수정이 필요합니다.
  - 수정 추천: 도메인/발신 주소를 `.env` 또는 GitHub Secrets 기반 환경변수로 분리하기.

- [ ] `gateway/src/email.ts`, `frontend/app/*`, `frontend/components/*`
  - 문제: 한국어 문구가 깨진 상태로 보이는 파일들이 있습니다.
  - 이유: 빌드는 통과하지만 운영 UX와 이메일 신뢰도에 영향을 줍니다.
  - 수정 추천: 파일 인코딩과 깨진 문구를 UTF-8 기준으로 복구하기.

- [ ] `.github/workflows/deploy.yml`
  - 문제: 배포 후 health/smoke check가 없습니다.
  - 이유: `docker compose up -d` 성공 후 실제 웹/API/회원가입/리뷰 작성 실패를 CI가 잡지 못합니다.
  - 수정 추천: 배포 후 `/`, `/api/products`, gateway `/health`, inference `/health` 확인 단계를 추가하기.

## Verification Already Done

- `frontend`: `npm run build` 성공
- `gateway`: `npm run build` 성공
- `python-inference`: `pytest python-inference/tests` 성공
- `docker-compose.prod.yml`: `docker compose -f docker-compose.prod.yml config` 유효성 확인
