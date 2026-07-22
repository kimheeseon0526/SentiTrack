# SentiTrack

글로벌 쇼핑몰(향수 커머스)용 실시간 리뷰 감성 모니터. 리뷰가 등록되는 즉시 감성(POSITIVE/NEGATIVE/MIXED)을 추론해 기록하고, 사용자별 아카이브에서 선호/비선호 향을 통계로 보여준다.

## 주요 기능

- 상품별 리뷰 작성과 감성 자동 분류 (POSITIVE / NEGATIVE / MIXED)
- 대조·혼합 문장("향은 좋은데 지속력이 별로예요")을 절 단위로 분리해 MIXED로 판별
- 이메일 인증 기반 회원가입/로그인 (JWT)
- 로그인 사용자의 리뷰 아카이브 — 선호/비선호 향 카테고리 통계
- MLflow를 통한 추론 요청 로깅 (모델명, confidence, latency)

## 기술 스택과 서비스 구조

| 레이어 | 기술 |
|--------|------|
| 프론트엔드 | Next.js (App Router, TypeScript) |
| 게이트웨이 | Node.js (TypeScript, Fastify) |
| 추론 서버 | Python (FastAPI) + HuggingFace(KoELECTRA) + MLflow |
| DB | MySQL 8.0 |
| 인프라 | Docker Compose |

```
frontend (Next.js) → gateway (Fastify) → inference (FastAPI, KoELECTRA)
                            ↓
                          MySQL
```

- 외부 노출: Next.js만 `sentitrack.levelupseon.com`으로 노출
- 내부망 전용: 게이트웨이, 추론 서버는 외부 도메인 없이 `shared-net` 내부 통신만 사용
- 기존 EC2의 `nginx-proxy` + `acme-companion` + `shared-net` 구조를 재사용

## 실행 방법 (로컬 개발)

```bash
git clone <repo>
cd SentiTrack

# gateway/.env 파일을 직접 작성 (.env는 git에서 제외됨)
# 필요한 변수: JWT_SECRET, RESEND_API_KEY, RESEND_FROM_ADDRESS

docker compose up --build
```

- 프론트엔드: http://localhost:3000
- 게이트웨이: http://localhost:4000 (내부용)
- 추론 서버: http://localhost:8000 (내부용, `/health`로 상태 확인)
- DB: `localhost:3307` (MySQL, 로컬 전용 자격증명)

운영 배포는 `docker-compose.prod.yml` + `.github/workflows/deploy.yml`(OCI 서버로 SSH 배포)로 자동화되어 있다.

## 운영 주소

- 서비스: `sentitrack.levelupseon.com` (Next.js만 외부 노출)
- 실제 운영 서버: OCI 인스턴스 (내부망 전용, 주소는 비공개 secrets로 관리)
- 과거 사용됐던 EC2 인스턴스는 더 이상 서비스에 쓰이지 않는다.

## AI 고도화 — 최종 확정 지표

KoELECTRA 이진 분류기는 대조/혼합 문장을 문장 전체 단위로 판단하는 구조적 한계가 있어, clause split(절 분리) + 절 텍스트 정규화를 실제 `/predict`에 배선해 MIXED 라벨을 도입했다. 아래 KoELECTRA 표는 오프라인 실험 수치가 아니라 **로컬 FastAPI `/predict` 엔드포인트를 40건 평가셋 전체에 실제로 호출하여 측정한 최종 프로덕션 수치**다 — 외부 LLM API 호출과는 무관하다 (2026-07-21 기준, 커밋 `f4e0a09` → `8b5e869`).

| 지표 (실제 `/predict` 기준) | 값 |
|---|---|
| MIXED Recall (clause split + normalization 연결 후) | **0.30** (연결 전 0.20) |
| MIXED Precision | 1.0 |
| POSITIVE/NEGATIVE 정확도 | 1.0 (회귀 없음) |
| False MIXED (신규 오탐) | 0건 |
| 코드 테스트 | 160 passed (성능 지표가 아니라 테스트 스위트 전체 결과) |

LLM(OpenRouter 무료 모델, structured output) 경로는 대조 문장 판별에서 KoELECTRA보다 뚜렷한 우위를 보였다 — 단, 이 환경에 API 키가 없어 아래 수치는 **40건 중 캐시에 있던 31건만** 네트워크 호출 없이 검증한 결과이며, **나머지 9건(POSITIVE 2 / NEGATIVE 1 / NEUTRAL 6)은 평가되지 않았다.** 40건 전체 실시간 평가가 아니다. 외부 API 호출은 이번에도 **0건**이었다.

| 지표 (LLM 캐시 전용 평가, 31/40건) | 값 |
|---|---|
| MIXED Precision / Recall / F1 | 1.0 / 1.0 / 1.0 |
| Overall 정확도 | 0.9677 (30/31) |

> Overall 정확도는 이전에 `0.9355(29/31)`로 기록됐으나, 이는 캐시 선택 정책이 last-write-wins(같은 키에 나중에 쓴 값이 이전 값을 덮어씀)였을 때 읽힌 값이다. 캐시를 write-once/first-write-wins(같은 키의 최초 응답을 항상 보존)로 고친 뒤 같은 31/40건 cache-only 평가를 다시 실행하면 `0.9677(30/31)`이 나온다. **모델·프롬프트·평가 데이터셋은 변경되지 않았으며, 중복 캐시 중 어느 과거 예측 응답을 평가 입력으로 사용하는지가 변경된 결과다.** LLM 성능이 개선된 것이 아니다. 상세 원인과 재현 절차는 [`docs/SENTITRACK_AI_ENHANCEMENT_LOG.md`](docs/SENTITRACK_AI_ENHANCEMENT_LOG.md)에 기록되어 있다.

수치의 산출 과정, 오프라인 실험값과의 차이, 원인 분석은 [`docs/SENTITRACK_AI_ENHANCEMENT_LOG.md`](docs/SENTITRACK_AI_ENHANCEMENT_LOG.md)에 날짜별로 누적 기록되어 있다.

## 현재 한계

- **LLM 캐시 재현성**: 캐시가 세션 간 last-write-wins로 덮어써지던 버그는 write-once 정책 + 충돌 감지로 코드 레벨에서 수정됐다(상세: [`docs/SENTITRACK_AI_ENHANCEMENT_LOG.md`](docs/SENTITRACK_AI_ENHANCEMENT_LOG.md) 기술 부채 1번). 다만 이미 드리프트됐던 과거 캐시 파일의 값 자체를 자동으로 복구하지는 않는다.
- **LLM 평가 미완**: 40건 중 9건은 API 키가 없어 여전히 미평가 상태다.
- **DB 계정 정합성**: 운영 DB의 root 계정 비밀번호와 `.env`의 `DB_PASSWORD`가 불일치한다 (앱 계정은 정상 동작하며 마이그레이션 수행에는 지장 없음).
- **기존 데이터 미재채점**: 버그 수정 이전에 저장된 리뷰(예: id=2)는 재분석하지 않아 여전히 이전 라벨로 남아있다.
- **MIXED confidence_score**: 절별 확신도가 아니라 원문 전체(baseline) 확신도를 재사용한다.
- 보안/운영 점검에서 발견된 나머지 항목은 [`DEPLOYMENT_FIXES.md`](DEPLOYMENT_FIXES.md) 체크리스트로 별도 관리한다.

## 상세 문서

- [`docs/sessions/2026-07-21-summary.md`](docs/sessions/2026-07-21-summary.md) — 2026-07-21 작업 요약 (버그 수정, 배포 장애 대응, 최종 평가)
- [`docs/SENTITRACK_AI_ENHANCEMENT_LOG.md`](docs/SENTITRACK_AI_ENHANCEMENT_LOG.md) — AI 고도화 전 과정 누적 기록 (진단 → 실험 → 운영 반영)
- [`CHANGELOG.md`](CHANGELOG.md) — 날짜별 코드 변경 이력
- [`DEPLOYMENT_FIXES.md`](DEPLOYMENT_FIXES.md) — 배포/보안 점검 체크리스트
