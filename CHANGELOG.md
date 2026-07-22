# CHANGELOG

---

## 2026-07-22

### 변경 사항 (LLM 캐시 conflict 분류 세분화 및 실제 로컬 캐시 재현성 재검증)

- `python-inference/experiments/llm_sentiment_client.py` — 중복 캐시 항목을 하나의 `conflicts`로 뭉치지 않고 `EXACT_DUPLICATE`(같은 input hash + 같은 의미 있는 응답 payload) / `RESPONSE_CONFLICT`(같은 input hash, 다른 payload — 실제 LLM 드리프트) / `KEY_COLLISION`(input hash 자체가 다름 — cache_key 해시 충돌)로 분류. payload 비교는 `overall_label` + `aspects`(name/sentiment/evidence, 순서 무관)만 canonical 비교하고 `confidence`/`short_reason`은 제외
- `python-inference/scripts/evaluate_llm_sentiment.py` — `cache_usage_payload()`에 `cache_duplicate_count`/`cache_response_conflict_count`/`cache_key_collision_count` 분리 필드 추가(`cache_conflict_count`/`cache_conflicts`는 response_conflict+key_collision만 포함, exact_duplicate는 집계에서 제외). `cache_conflicts` 각 항목은 `cache_key`/`input_hash`/`line_number`/`conflict_type`만 포함 — 리뷰 원문·LLM 응답 텍스트는 넣지 않음
- `python-inference/tests/test_llm_sentiment.py` — 세 분류 각각의 판정, `conflicts` 프로퍼티가 exact_duplicate를 제외하는지, 중복/충돌이 있어도 실제 네트워크 호출이 0건인지 검증하는 테스트 5개 추가 (155 → 160 passed)
- **실제 로컬 캐시(`llm_sentiment_cache.jsonl`, 84KB, 이번 작업에서 수정하지 않음)로 검증**: `evaluate_llm_cache_only.py`를 캐시 파일을 건드리지 않고 동일 설정으로 2회 실행 → 리포트가 바이트 단위로 완전히 동일(SHA256 일치), `actual_api_call_count`는 2회 모두 0. 실제 conflict 집계는 `cache_duplicate_count=8`, `cache_response_conflict_count=16`, `cache_key_collision_count=0`

### 이유

- 이전 커밋에서 구현한 `.conflicts`는 같은 cache_key에서 `raw_text`가 다르면 전부 "충돌"로만 집계해, 실제로는 문제 없는 완전 동일 재기록(중복)과 진짜 LLM 응답 드리프트(response conflict), 그리고 이론상의 cache_key 해시 충돌(key collision)을 구분하지 못했다. 세 원인은 대응 방법이 다르므로 분리 집계가 필요했음
- 성능 수치가 아니라 진단 정확도를 높이는 작업이며, 실제 로컬 캐시로 검증한 결과 재현성(2회 실행 결과 완전 동일, 외부 호출 0건)은 확인됐지만 그 과정에서 **부수적으로** 31/40건 cache-only 서브셋의 overall 정확도가 `0.9355(29/31, 수정 전 last-write-wins 기준)`에서 `0.9677(30/31, 수정 후 first-write-wins 기준)`으로 달라지는 것을 확인함
- **이 수치 변화는 모델·프롬프트·평가 데이터가 개선된 것이 아니다.** KoELECTRA/`/predict`는 건드리지 않았고 LLM 쪽도 모델·프롬프트(`sentiment-aspect-v1`)·데이터셋이 동일하다 — 모델·프롬프트·평가 데이터셋은 변경되지 않았으며, 중복 캐시 중 어느 과거 예측 응답을 평가 입력으로 사용하는지가 변경된 결과다. 여전히 40건 중 31건 기준의 부분 평가이며 전체 40건 실시간 평가가 아니고, 외부 API 호출은 0건이다
- `README.md`, `docs/SENTITRACK_AI_ENHANCEMENT_LOG.md`를 이 수치 변경 원인과 함께 갱신 (기존 `0.9355` 기록은 삭제하지 않고 "수정 전 last-write-wins 기준 과거 결과"로 남김)

## 2026-07-21

### 변경 사항 (LLM 평가 캐시 재현성 버그 수정)

- `python-inference/experiments/llm_sentiment_client.py` — `JsonlLLMCache.set()`에 `allow_overwrite: bool = False` 파라미터 추가(기존 키가 있으면 기본적으로 쓰기를 건너뛰고 `False` 반환, write-once 정책). `_ensure_loaded()`를 파일 내 중복 `cache_key`에 대해 마지막 줄이 아니라 **첫 번째 줄이 항상 이기도록** 변경하고, 서로 다른 `raw_text`를 가진 중복 항목을 `conflicts` 프로퍼티로 노출
- `python-inference/experiments/llm_sentiment_client.py` — `analyze_with_cache()`에 `refresh_cache=True`의 의미를 "이번 실행은 캐시를 읽지 않고 항상 라이브 호출한다"로 한정하고, 그 결과를 캐시에 쓸 때도 기존 키를 덮어쓰지 않도록 함(이전에는 무조건 덮어썼음)
- `python-inference/scripts/evaluate_llm_sentiment.py` — `cache_usage_payload()`가 리포트 metadata에 `cache_conflict_count`/`cache_conflicts`를 포함하도록 변경 — 캐시 파일에 과거 드리프트로 생긴 중복 항목이 있으면 이후 모든 리포트(`evaluate_llm_cache_only.py` 포함)에 자동으로 노출됨
- `python-inference/tests/test_llm_sentiment.py` — write-once 기본 동작, 명시적 `allow_overwrite`, 충돌 감지, 세션 간 재사용, `refresh_cache`가 기존 캐시를 덮어쓰지 않음을 검증하는 테스트 5개 추가 (150 → 155 passed)

### 이유

- `docs/SENTITRACK_AI_ENHANCEMENT_LOG.md`의 "기술 부채 1. LLM 캐시 재현성" 항목에서 확인된 근본 원인: `JsonlLLMCache`가 같은 `cache_key`를 나중에 쓴 값이 이전 값을 덮어쓰는 last-write-wins 구조라, 비결정적인 LLM 응답이 세션 간 재호출되면 과거 캐시가 조용히 교체되어 재현성이 깨졌음(대표 12건의 aspect F1이 0.9032→0.4667로 하락한 사례)
- 목표는 특정 성능 수치를 올리는 것이 아니라 "동일한 입력·평가 설정·캐시를 사용하면 항상 동일한 예측·평가 결과가 나오도록" 만드는 것이므로, 캐시를 write-once(최초 성공 응답을 영구 보존)로 바꾸고, 그래도 발생할 수 있는 이력상의 충돌은 숨기지 않고 리포트에 명시적으로 노출하는 방향으로 수정
- `--refresh-cache`는 "라이브 호출을 강제한다"는 원래 목적은 유지하되, 그 결과가 다른 평가(예: 12건 대표셋)가 참조하는 기존 캐시 항목을 의도치 않게 덮어쓰지 않도록 쓰기 동작만 분리

### 변경 사항 (README·AI 고도화 로그 문서 정리)

- `README.md` — 신규 생성. 프로젝트 개요, 주요 기능, 기술 스택/서비스 구조, 실행 방법, 운영 주소, AI 고도화 최종 확정 지표, 현재 한계, 상세 문서 링크
- `docs/SENTITRACK_AI_ENHANCEMENT_LOG.md` — 기존 날짜별 기록은 보존하고 다음만 추가:
  - 이후 단계에서 해소된 과거 "다음 작업"/"남은 문제" 항목에 `[해결됨]`/`[부분 해결]` 태그와 해결 커밋 참조 추가 (삭제 없음)
  - "수치 구분: 오프라인 실험값 vs 실제 프로덕션(`/predict`) 최종값" 절 추가 — 같은 수치(예: MIXED Recall 0.30)가 오프라인 실험 단계와 실제 배포 단계 양쪽에 등장해 혼동될 수 있는 부분을 표로 명시적 구분
  - 문서 최하단에 "기술 부채" 섹션 신설 — LLM 캐시 last-write-wins 재현성 문제, DB root/app 비밀번호 불일치, OpenRouter 40건 중 9건 미평가, 기존 운영 리뷰 재채점 미실시를 한 곳에 모아 추적
- `docs/sessions/2026-07-21-summary.md`는 이미 시간순 기록·커밋 번호를 포함하고 있어 변경 없음

### 이유

- 목표 4(문서화)에 따라 포트폴리오 열람자가 README만 보고 프로젝트를 파악하고, 세부 근거는 상세 문서로 찾아갈 수 있도록 정리
- AI 고도화 로그가 여러 실험 단계에 걸쳐 누적되며 같은 지표가 반복 등장해 어떤 값이 최종적으로 운영에 반영된 값인지 구분하기 어려워졌던 문제를 해결
- 미해결 항목이 날짜별 기록 곳곳에 흩어져 있어 다음 작업자가 놓치기 쉬웠던 것을 한 곳에서 추적 가능하게 함

### 변경 사항 (배포 파이프라인 동시 실행 방지)

- `.github/workflows/deploy.yml` — `concurrency: { group: deploy-production, cancel-in-progress: false }` 추가

### 이유

- 오늘 짧은 간격으로 연달아 push된 두 워크플로가 동시 실행 제어 없이 같은 OCI 서버에 SSH 배포를 동시에 실행하면서 서버 load average가 9.56까지 상승했고, 이후 오래된 쪽을 취소하는 과정에서 containerd에 dangling lease가 남아 남은 배포의 `docker compose pull`이 25분 넘게 완전히 멈추는 문제가 있었음
- `cancel-in-progress: false`로 설정해 먼저 실행 중인 배포를 강제 중단시키지 않고, 뒤에 트리거된 워크플로는 대기열에서 순차 실행되도록 해서 애초에 두 배포가 동시에 같은 서버를 건드리는 상황 자체를 막음

### 변경 사항 (clause_normalization을 /predict에 연결)

- `python-inference/experiments/clause_sentiment.py` — `analyze_clause_sentiment()`에 `clause_normalizer` 선택적 인자 추가 (기본값 `None`이면 기존 동작과 동일), 절 예측 직전에만 적용
- `python-inference/main.py` — `clause_normalization.py`의 `normalize_clause`/`SIMPLE_DECLARATIVE`를 연결하는 `_normalize_clause_text()` wrapper 추가, `/predict`가 정규화된 절 텍스트로 예측하도록 변경
- `python-inference/tests/test_clause_sentiment.py`, `test_main.py` — 신규 정규화 배선 동작 검증 테스트 3개 추가

### 이유

- 목표 3 최종 평가에서 확인된 갭(프로덕션 MIXED Recall 0.20 vs 오프라인 실험 최고치 0.30)을 해소하기 위해, 이미 검증된 `clause_normalization.py`(SIMPLE_DECLARATIVE)를 배선만 함
- 재측정 결과 MIXED Recall 0.20 → **0.30**으로 개선 확인 (오프라인 실험 수치와 정확히 일치), POSITIVE/NEGATIVE 정확도 1.0 유지(회귀 없음), false MIXED 0건(신규 오탐 없음)
- 전체 테스트 150개(기존 147 + 신규 3) 통과

### 변경 사항 (목표 3: KoELECTRA·Normalization·LLM 최종 평가)

- `python-inference/scripts/evaluate_predict_endpoint.py` — 신규 생성. 실제 `/predict` 엔드포인트를 40건 데이터셋에 호출해 재측정하는 스크립트
- `python-inference/scripts/evaluate_llm_cache_only.py` — 신규 생성. LLM 캐시에 존재하는 항목만 검증하고 미시도 항목은 네트워크 호출 없이 건너뛰는 스크립트 (`OpenAICompatibleAdapter`의 `opener`를 로컬 스텁으로 교체)
- `python-inference/evaluation/predict_endpoint_full40_report.json`, `llm_sentiment_v1_reverify_report.json`, `aspect_taxonomy_reverify_report.json`, `llm_sentiment_v1_cacheonly_full40_report.json` — 신규 생성. 재측정 결과 산출물
- `docs/SENTITRACK_AI_ENHANCEMENT_LOG.md` — 재측정 수치, 기존 기록과의 비교, 원인 분석, 포트폴리오 인용 문단 기록

### 이유

- 오늘 오전 오분류 버그 수정으로 `/predict`가 clause split + MIXED 로직을 실제로 쓰게 됐으므로, 기존에 오프라인 실험 스크립트로만 측정했던 KoELECTRA/normalization 수치를 실제 엔드포인트 기준으로 재확정할 필요가 있었음
- 재측정 결과 MIXED Recall이 기존 기록(0.30, SIMPLE_DECLARATIVE 실험)이 아니라 0.20(RAW 실험과 동일)으로 나왔음 — `/predict`에는 절 텍스트 정규화 단계가 배선되지 않았기 때문. 프로덕션의 정직한 현재 수치로 기록
- LLM(OpenRouter) 12건/40건 재평가 과정에서 공유 캐시 파일(`llm_sentiment_cache.jsonl`)이 세션 간 last-write-wins로 덮어써져 aspect 이름 수준 재현성이 낮다는 문제를 발견 — taxonomy 정규화 코드 자체의 결함이 아니라 캐시 재사용의 재현성 한계임을 확인해 기록
- 이 환경에 LLM API 자격 증명이 전혀 없어(모든 스코프에서 미설정 확인) 실제 API 호출 없이 캐시만으로 안전하게 최대한의 실측치를 뽑아내는 방식(`evaluate_llm_cache_only.py`)을 새로 만들어 사용 — 가짜 자격증명으로 OpenRouter에 무의미한 요청을 보내지 않기 위함

### 변경 사항

- `.github/workflows/deploy.yml` — "Deploy to OCI via SSH" 스텝의 `docker image prune -f` 다음에 `gateway/migrations/*.sql`을 파일명 순서대로 순회하며 `sentitrack-db` 컨테이너에 적용하는 반복문 추가
- 위 반복문의 DB 접속 계정을 root가 아닌 `secrets.DB_USER`/`secrets.DB_PASSWORD`(앱 계정)로 사용

### 이유

- `gateway/migrations/002_add_users.sql`, `003_add_scent_category.sql`이 `docker-entrypoint-initdb.d`로 마운트되어 있는데, 이 방식은 MySQL 데이터 볼륨이 "처음" 생성될 때만 실행되어, 이미 존재하는 볼륨에는 신규 마이그레이션 파일이 자동 반영되지 않는 구조적 문제가 있었음
- 실제 운영 서버(OCI 운영 서버) 점검 결과 `sentitrack_reviews.user_id`, `sentitrack_products.scent_category` 컬럼은 이미 반영되어 있었으나(볼륨이 002/003 추가 이후 재생성됨), 향후 동일한 문제가 재발하지 않도록 배포 파이프라인에서 매 배포마다 마이그레이션을 직접 적용하도록 재발 방지 로직을 추가함
- 002, 003 SQL은 `IF NOT EXISTS`/stored procedure 가드로 이미 idempotent하게 작성되어 있어 매 배포마다 재실행해도 안전함
- root 계정 사용 시 인증 실패 확인: 운영 DB의 `MYSQL_ROOT_PASSWORD`는 볼륨 최초 생성 시에만 적용되는데, 이후 `.env`의 `DB_PASSWORD` 시크릿이 로테이션되면서 root 비밀번호와 어긋난 상태였음. 앱 계정(`sentitrack_user`)은 `sentitrack` 스키마에 대해 `ALL PRIVILEGES`를 보유하고 있고 마이그레이션 파일들도 스키마 범위 내 DDL만 사용해 앱 계정으로도 충분히 실행 가능하여, root 대신 앱 계정을 사용하도록 변경
- `python-inference/experiments/clause_sentiment.py` — `ENDING_CONNECTORS`에 `"인데"` 추가
- `python-inference/main.py` — `/predict`가 `analyze_clause_sentiment`를 통해 대조 문장을 clause 단위로 재분류하고 `POSITIVE`/`NEGATIVE`/`MIXED`를 반환하도록 변경, MLflow에 `contrast_detected` 태그 추가
- `python-inference/Dockerfile` — `COPY experiments ./experiments` 추가
- `frontend/lib/types.ts` — `sentimentLabel`에 `"MIXED"` 추가
- `frontend/app/globals.css` — `--color-mixed-*` 변수 및 `.ac-badge-mixed` 클래스 추가
- `frontend/components/ReviewCard.tsx`, `ArchiveCard.tsx` — `isPositive` 불리언 삼항 연산을 `sentimentLabel` 기반 매핑 테이블로 교체
- `frontend/app/me/page.tsx` — `negativeCount` 계산식을 `NEGATIVE` 직접 필터링으로 수정, `mixedCount` 통계 박스 추가
- `python-inference/scripts/reproduce_prod_mismatch.py`, `verify_prod_mismatch_fix.py` — 신규 생성 (운영 오분류 사례 재현/검증 스크립트)
- `docs/SENTITRACK_AI_ENHANCEMENT_LOG.md` — 원인 진단, 변경 내역, 재현 테스트 결과, 남은 문제 기록

### 이유 (감성 오분류 수정)

- "부정 리뷰가 긍정으로 표시되는 오류" 제보로 운영 DB(OCI)를 읽기 전용 점검한 결과, 리뷰 id=2 "제일 좋아하는 꽃향인데 조금 인공적인거 같아요ㅠㅠㅠ"가 `POSITIVE 0.6702`로 저장돼 있었음
- model_version/캐싱 불일치(케이스 A)는 재현 결과 저장값과 완전히 일치해 배제. KoELECTRA 이진 분류기가 대조/혼합 문장을 하나의 라벨로 압축하는 구조적 한계(케이스 B)로 확정
- 이미 구현돼 있던 `experiments/clause_sentiment.py`(clause split)를 실제 `/predict`에 연결하는 과정에서 `ENDING_CONNECTORS`에 "인데"가 빠져 있어 해당 사례가 clause split조차 안 되던 것을 추가로 발견해 같이 수정
- Dockerfile이 `main.py`만 복사하고 `experiments/`는 복사하지 않아, `main.py`의 신규 import가 배포 시 `ModuleNotFoundError`로 컨테이너를 죽였을 것을 배포 전에 발견해 같이 수정
- frontend의 `isPositive ? "POSITIVE" : "NEGATIVE"` 및 `negativeCount = total - positiveCount` 패턴은 POSITIVE가 아닌 모든 값(신규 MIXED 포함)을 NEGATIVE로 잘못 표시/집계하는 구조라 같이 수정
- 수정 전/후 재현 스크립트로 대상 사례(POSITIVE → MIXED)와 4개 합성 사례(회귀 없음)를 비교 검증, `python-inference` 147개 테스트 및 gateway/frontend 빌드 통과 확인

---

## 2026-06-30

### 변경 사항

- `docker-compose.prod.yml` — gateway의 `depends_on.inference` 조건을 `service_healthy` → `service_started`로 변경

### 이유

- inference(Python ML 서버)는 KoELECTRA 모델 로딩에 시간이 걸려 헬스체크를 통과하지 못하면 gateway가 아예 기동되지 않는 문제가 있었음
- `/api/products`(향수 목록), `/api/auth/*`(로그인/회원가입) 등은 inference와 무관한데도 gateway 미기동으로 전부 실패함
- gateway 코드는 이미 inference 미응답 시 502를 반환하도록 처리되어 있으므로, gateway를 먼저 띄우고 inference가 준비되면 리뷰 분석 기능이 활성화되는 방식으로 변경

---

## 2026-06-22

### 변경 사항

- `frontend/lib/fragranceProfile.ts` — 신규 생성. origin별 Top/Middle/Base 노트, Longevity/Sillage(1-5) 정적 매핑 데이터
- `frontend/lib/scentColor.ts` — `getScentColor`/`getCardColor` 제거 후 `getScentGradient` 단일 함수로 교체, origin별 135° 2색 CSS 그라데이션 값 반환
- `frontend/next.config.ts` — `images.remotePatterns`에 `images.unsplash.com`, `plus.unsplash.com` 추가
- `frontend/app/globals.css` — `.fp-*`(향 프로필), `.ind-*`(인디케이터 바), `.rc-*`(리뷰 카드), `.about-*`(어바웃 페이지), `.fp-note-badge*` CSS 클래스 추가; `.pc-swatch`에 `position: relative; overflow: hidden` 추가
- `frontend/components/Gnb.tsx` — ABOUT 메뉴 href `"#"` → `"/about"` 수정
- `frontend/components/ProductCard.tsx` — `getScentGradient` 기반 그라데이션 스와치 적용, `isHovered` 상태로 hover 시 `translateY(-2px)` + 그림자 전환 추가
- `frontend/components/ReviewCard.tsx` — `borderLeft` 복원, `marginBottom: 10px`, `boxShadow` 추가; `Number()` 명시 캐스팅으로 mysql2 DECIMAL 문자열 반환 버그 방어
- `frontend/components/ReviewForm.tsx` — 버튼 hover 상태(`isButtonHovered`) 추가, hover 시 `--color-text-primary` 전환; 글자 수 카운터 유지
- `frontend/app/page.tsx` — 히어로 섹션 제거, 인라인 스타일 기반 심플 헤더 + 그리드 레이아웃으로 교체
- `frontend/app/products/[id]/page.tsx` — Server Component + 2컬럼 그리드(4:5 비율 그라데이션 + 상품 헤더) 레이아웃으로 재설계; `useParams()` 기반 Client Component 시도 후 Server Component로 확정 (params Promise 바인딩 충돌 해결)
- `frontend/app/about/page.tsx` — 신규 생성. 브랜드 철학 정적 페이지
- `python-inference/main.py` — 모델 교체(`distilbert` → `jaehyeong/koelectra-base-v3-generalized-sentiment-analysis`), `normalize_label()` 추가로 `"0"`/`"1"`/`"LABEL_0"`/`"LABEL_1"` → `"NEGATIVE"`/`"POSITIVE"` 매핑 방어
- `python-inference/requirements.txt` — `sentencepiece==0.2.0` 추가 (KoELECTRA 토크나이저 의존성)
- `python-inference/tests/test_main.py` — 모델명 단언문 업데이트, `normalize_label` 단위 테스트 추가
- `gateway/src/server.ts` — `toReviewDto`에서 `confidence_score`, `latency_ms`를 `Number()`로 명시 변환 (mysql2 DECIMAL 문자열 반환 버그 수정)
- `python-inference/main.py` — `MODEL_REVISION = "370f325ce11aabd837b89bfb3ffdc26fde354689"` 추가, `pipeline()` 호출 시 `revision=MODEL_REVISION` 파라미터 전달
- `gateway/src/email.ts` — 발신 주소 기본값 `onboarding@resend.dev` → `onboarding@levelupseon.com`
- `gateway/.env` — `RESEND_FROM_ADDRESS` 값 동일하게 변경
- `gateway/src/server.ts` — `GET /api/reviews` 인라인 매핑에 `Number()` 캐스팅 추가 (`confidenceScore`, `latencyMs`)
- `frontend/lib/types.ts` — `userId` 필드 추가, `MyReview` 인터페이스 신규, `AuthUser` 인터페이스 신규
- `frontend/lib/AuthContext.tsx` — 신규 생성. `AuthProvider` + `useAuth` 훅 (localStorage 기반 JWT 관리)
- `frontend/app/layout.tsx` — `AuthProvider`로 children 감싸도록 수정
- `frontend/app/api/auth/signup/request/route.ts` — 신규 생성. Next.js API Route (gateway 프록시)
- `frontend/app/api/auth/signup/verify/route.ts` — 신규 생성. Next.js API Route (gateway 프록시)
- `frontend/app/api/auth/login/route.ts` — 신규 생성. Next.js API Route (gateway 프록시)
- `frontend/app/api/me/reviews/route.ts` — 신규 생성. Next.js API Route (Authorization 헤더 포워딩)
- `frontend/app/signup/page.tsx` — 신규 생성. 이메일 인증 2단계 회원가입 페이지
- `frontend/app/login/page.tsx` — 신규 생성. 로그인 페이지
- `frontend/app/me/page.tsx` — 신규 생성. My Archive 페이지 (내 리뷰 목록 + 선호 향 통계)
- `frontend/components/ReviewForm.tsx` — 미로그인 시 로그인 유도 UI, JWT Authorization 헤더 전송
- `frontend/app/archive/page.tsx` — `ArchiveReview` 로컬 타입 추가 (productName 포함)
- `frontend/components/ArchiveCard.tsx` — `ArchiveReview` 타입으로 수정
- `frontend/app/api/products/[id]/reviews/route.ts` — `Authorization` 헤더 gateway 포워딩 추가 (누락으로 인한 401 버그 수정)
- `frontend/components/HeroSection.tsx` — 신규 생성. Client Component. 히어로 섹션 (eyebrow, 타이틀, 설명, 4단계 플로우, 향수 둘러보기/MY ARCHIVE 버튼)
- `frontend/app/page.tsx` — HeroSection 추가, 상품 목록에 id="products" 앵커 추가 (스크롤 대상)
- `.github/workflows/deploy.yml` — 신규 생성. main 브랜치 push 시 EC2 SSH 자동 배포 (appleboy/ssh-action, git pull → docker compose prod up)
- `docker-compose.prod.yml` — 운영용 재작성. nginx-proxy, letsencrypt, restart:always, shared-net(external), JWT/Resend secrets 환경변수 주입, db 서비스 + 볼륨 포함
- `gateway/migrations/003_add_scent_category.sql` — `sentitrack_products`에 `scent_category` 컬럼 추가 및 10개 상품 카테고리 값 설정
- `gateway/src/server.ts` — `/api/me/reviews` 쿼리에 `p.scent_category` 추가, 응답에 `scentCategory` 필드 포함
- `frontend/lib/types.ts` — `MyReview`에 `scentCategory: string` 추가
- `frontend/app/me/page.tsx` — 선호하는 향 / 싫어하는 향 분리 표시, `scentCategory` 기반 집계, 빈 상태 "아직 기록이 없어요" 처리 — `sentitrack_products`에 `scent_category` 컬럼 추가 및 10개 상품 카테고리 값 설정
- `frontend/app/archive/` — 전체 공개 아카이브 페이지 삭제 (My Archive로 대체)
- `frontend/components/Gnb.tsx` — Client Component로 전환, `useAuth` 연동. 미로그인 시 로그인/회원가입, 로그인 시 MY ARCHIVE/로그아웃 표시 (EDITIONS, ABOUT 메뉴 제거)
- `gateway/migrations/002_add_users.sql` — `sentitrack_users`, `sentitrack_email_verifications` 테이블 생성; `sentitrack_reviews`에 `user_id` 컬럼 및 FK 추가
- `gateway/package.json` — `bcryptjs`, `jsonwebtoken`, `resend` 의존성 추가; `@types/bcryptjs`, `@types/jsonwebtoken` devDependencies 추가
- `gateway/src/jwt.ts` — 신규 생성. `signToken` / `verifyToken` (30일 만료 JWT 유틸)
- `gateway/src/email.ts` — 신규 생성. Resend API 기반 이메일 인증 코드 발송 유틸
- `gateway/src/authRoutes.ts` — 신규 생성. `POST /api/auth/signup/request`, `POST /api/auth/signup/verify`, `POST /api/auth/login` 엔드포인트
- `gateway/.env` — 신규 생성. 로컬 개발용 환경변수 (JWT_SECRET, RESEND_API_KEY, RESEND_FROM_ADDRESS)
- `docker-compose.yml` — gateway 서비스에 `env_file: ./gateway/.env` 추가
- `.gitignore` — 프로젝트 루트에 신규 생성. `.env`, `node_modules`, `dist`, `.next` 등 제외
- `gateway/src/server.ts` — `registerAuthRoutes` 등록, `getAuthenticatedUserId` 헬퍼 추가, 리뷰 작성에 JWT 인증 필수화 (`user_id` INSERT 포함), `GET /api/me/reviews` 엔드포인트 추가

### 이유

- **향수 브랜드 디자인 고도화**: 단색 스와치 → 그라데이션, 카드 hover 인터랙션, 2컬럼 상세 레이아웃으로 니치 향수 브랜드 감성 강화
- **한국어 감성 분석 지원**: 영어 전용 DistilBERT에서 한국어 최적화 KoELECTRA 모델로 교체하여 한국어 리뷰 정확도 개선
- **런타임 에러 수정**:
  - mysql2 DECIMAL 타입이 문자열로 반환되어 `.toFixed()` 호출 시 발생하던 "is not a function" 에러 수정
  - `reviews.map()` 호출 시 `undefined` 에러 방어 (`?? []` 처리)
  - Next.js App Router에서 `React.use(params)` 사용 시 발생하는 "Response bindings is not a function" 에러 해결 (Server Component `await params` 방식으로 확정)
- **About 페이지 및 GNB 완성**: 브랜드 소개 페이지 추가 및 GNB 링크 연결
