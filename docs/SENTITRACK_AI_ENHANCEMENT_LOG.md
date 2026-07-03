## 260703

### 작업명
KoELECTRA 감정 분석 파이프라인 진단

### 작업 목적
- 감정 분석 고도화 전 현재 KoELECTRA 기반 추론 구조와 데이터 흐름을 코드 기준으로 확인했다.
- 대표 복합 감정 문장이 단일 positive/negative 결과로 처리되는 원인을 구현 버그와 모델 구조 한계로 분리했다.

### 작업 전 상태
- Frontend는 Next.js App Router, Gateway는 Fastify, AI inference는 FastAPI, DB는 MySQL 8.0 구조다.
- inference 서버는 `jaehyeong/koelectra-base-v3-generalized-sentiment-analysis` 모델과 revision `370f325ce11aabd837b89bfb3ffdc26fde354689`를 사용한다.
- 운영 코드 변경 없이 진단만 수행해야 하며 mixed, neutral, 규칙, 사전, LLM, DB schema, UI 변경은 이번 단계 범위 밖이다.

### 분석 내용
- `python-inference/main.py`: `lifespan()`에서 Hugging Face `pipeline("sentiment-analysis")`를 앱 시작 시 1회 로딩하고, `/predict`에서 `sentiment_pipeline(request.text)[0]` 결과를 처리한다.
- `python-inference/main.py`: `normalize_label()`은 `"1"`, `"LABEL_1"`, `"POSITIVE"`를 `POSITIVE`로, `"0"`, `"LABEL_0"`, `"NEGATIVE"`를 `NEGATIVE`로 변환한다.
- `python-inference/main.py`: confidence는 pipeline 결과의 `result["score"]`를 `float`로 변환한 값이며, 추가 보정은 없다.
- `python-inference/main.py`: MLflow에는 `model_name`, `input_text` 앞 500자, `confidence_score`, `latency_ms`, `predicted_label`이 기록된다.
- `gateway/src/server.ts`: `POST /api/products/:id/reviews`가 inference `/predict`를 호출하고 `prediction.label`, `prediction.score`를 DB와 응답에 그대로 사용한다.
- `frontend/components/ReviewCard.tsx`: `confidenceScore < 0.7`일 때 낮은 신뢰도 안내를 표시한다. 경고 판단은 Python/Gateway가 아니라 Frontend에서 수행된다.
- `gateway/migrations/001_init.sql`: `sentitrack_reviews.sentiment_label`은 `VARCHAR(20) NOT NULL`, `confidence_score`는 `DECIMAL(5, 4) NOT NULL`이다. ENUM 제한은 없다.

### 변경 내용
- 운영 코드 변경 없음.
- `python-inference/scripts/diagnose_sentiment.py`를 추가했다. 동일 모델과 revision을 한 번만 로딩하고 대표 문장 8개에 대해 원본 label, score, 정규화 label, 진단용 FastAPI 응답 형태, 0.7 미만 warning 여부를 JSON으로 출력한다.
- `docs/SENTITRACK_AI_ENHANCEMENT_LOG.md`를 새로 생성했다.

### 실행한 명령
```bash
git status --short
python -c "import transformers, torch; print('transformers', transformers.__version__); print('torch', torch.__version__)"
python -c "import fastapi, pydantic; print('fastapi', fastapi.__version__); print('pydantic', pydantic.__version__)"
python -m pytest --version
python python-inference\scripts\diagnose_sentiment.py
python -m pytest python-inference\tests
docker ps --format "{{.Names}} {{.Status}}"
```

### 테스트 및 검증 결과
- `transformers 4.45.1`, `torch 2.4.1+cpu`, `fastapi 0.115.0`, `pydantic 2.9.2`, `pytest 8.3.3` 확인.
- `python -m pytest python-inference\tests`: 7 passed, 18 warnings.
- 모델 config 실행 결과: `id2label={"0":"0","1":"1"}`, `label2id={"0":0,"1":1}`.
- `향은 너무 좋지만 지속력이 별로예요.` 실행 결과: raw label `0`, score `0.9720079898834229`, normalized `NEGATIVE`, warning `false`.
- `향이 은은하고 오래가서 만족해요.` 실행 결과: raw label `1`, score `0.990756094455719`, normalized `POSITIVE`, warning `false`.
- `냄새가 독하고 머리가 아파요.` 실행 결과: raw label `0`, score `0.9921349287033081`, normalized `NEGATIVE`, warning `false`.
- `배송은 빨랐지만 포장이 아쉬워요.` 실행 결과: raw label `0`, score `0.7664543390274048`, normalized `NEGATIVE`, warning `false`.
- `그냥 무난한 향이에요.` 실행 결과: raw label `0`, score `0.8685434460639954`, normalized `NEGATIVE`, warning `false`.
- `향이 나쁘지 않아요.` 실행 결과: raw label `1`, score `0.8795996308326721`, normalized `POSITIVE`, warning `false`.
- `가격은 비싸지만 그만큼 만족스러워요.` 실행 결과: raw label `1`, score `0.9768013954162598`, normalized `POSITIVE`, warning `false`.
- `지속력은 별로지만 향 하나는 정말 최고예요.` 실행 결과: raw label `1`, score `0.692886471748352`, normalized `POSITIVE`, warning `true`.
- 진단 스크립트 실행 중 Pydantic `model_version` protected namespace warning이 표시됐다.
- 로컬 Docker에는 SentiTrack compose 서비스가 실행 중이지 않아 Gateway 실제 HTTP 왕복과 기존 DB 데이터 분포는 확인 불가.

### 확인된 문제
- 구현 버그: 실행된 모델 config 기준 `0 -> NEGATIVE`, `1 -> POSITIVE` 매핑은 현재 `normalize_label()`과 일치한다. Gateway에서 label을 다른 값으로 바꾸는 코드는 확인되지 않았다. Frontend는 `POSITIVE`가 아니면 표시상 `NEGATIVE`로 취급한다.
- 모델 구조의 한계: 현재 API와 DB/UI 타입은 사실상 positive/negative 단일 라벨 흐름이다. mixed와 neutral 결과를 표현하지 못하며, 복합 문장도 하나의 라벨과 하나의 score로 압축된다.
- 추가 확인 필요: 실제 운영 컨테이너 cache/revision과 로컬 실행 일치 여부, 운영 DB에 저장된 sentiment 값 분포, 운영 Gateway를 통한 실제 HTTP 응답은 이번 로컬 환경에서 확인 불가.

### 의사결정
- 이번 단계에서는 mixed/neutral 구현, 규칙 기반 보정, LLM, 모델 교체, DB schema 변경, UI 변경을 모두 보류했다.
- 원인 판단은 코드와 로컬 실행 결과로 확인 가능한 범위까지만 기록했다.

### 남은 작업
- 운영 컨테이너에서 동일 revision과 동일 결과가 나오는지 확인해야 한다.
- 기존 DB의 `sentiment_label` 실제 값 분포를 확인해야 한다.
- mixed/neutral 또는 aspect 기반 감정 결과를 도입하려면 API, DB, Frontend 타입과 표시 정책 변경 범위를 별도 설계해야 한다.

### 다음 작업
- 다음 고도화 단계에서는 `MIXED`, `NEUTRAL`, 또는 aspect 기반 결과 중 어떤 목표를 먼저 지원할지 결정한다.
- 결정 후 migration, API 응답 구조, Frontend 표시, 테스트 전략을 함께 설계한다.

### 작업명
KoELECTRA baseline 평가 기준선 구축

### 작업 목적
- 운영 감정 분석 로직을 변경하지 않고 현재 KoELECTRA 모델의 성능을 객관적으로 측정할 기준을 만든다.
- `POSITIVE`, `NEGATIVE`, `MIXED`, `NEUTRAL` 라벨 정책과 평가 데이터셋을 분리해 향후 개선 전후 비교가 가능하게 한다.
- 현재 binary 모델이 mixed/neutral 샘플에서 어떤 한계를 보이는지 수치로 기록한다.

### 작업 전 상태
- 1단계 진단 결과, 모델 config와 `normalize_label()`은 `0 -> NEGATIVE`, `1 -> POSITIVE`로 일치했다.
- confidence는 Hugging Face pipeline의 선택 label score이며 의미상 정답 확률로 단정하지 않는다.
- 현재 운영 API와 UI는 사실상 `POSITIVE`/`NEGATIVE` 단일 라벨만 표현한다.
- 작업 시작 전 `git status --short` 결과는 1단계 산출물인 `docs/`, `python-inference/scripts/`가 untracked인 상태였다.

### 분석 내용
- `docs/SENTITRACK_SENTIMENT_LABEL_POLICY.md`: 평가용 라벨 정책을 작성했다. `POSITIVE`, `NEGATIVE`, `MIXED`, `NEUTRAL`의 판정 기준과 aspect 메타데이터 기준을 정의했다.
- `python-inference/evaluation/sentiment_eval_reviews.jsonl`: 40개 평가 샘플을 생성했다. 라벨 분포는 `POSITIVE=10`, `NEGATIVE=10`, `MIXED=10`, `NEUTRAL=10`이다.
- `python-inference/scripts/evaluate_sentiment_baseline.py`: 현재 `main.MODEL_NAME`, `main.MODEL_REVISION`, `main.normalize_label()`을 재사용해 baseline을 평가한다.
- `python-inference/tests/test_evaluate_sentiment_baseline.py`: 실제 모델을 로딩하지 않고 데이터셋 검증과 metric 계산을 fake predictor로 검증한다.

### 변경 내용
- 운영 코드 변경 없음.
- 감정 라벨 정책 문서를 추가했다.
- 평가용 JSONL 데이터셋을 추가했다.
- KoELECTRA baseline 평가 스크립트를 추가했다.
- 평가 로직 단위 테스트를 추가했다.
- 실제 baseline 평가 결과를 `python-inference/evaluation/baseline_report.json`에 저장했다.

### 실행한 명령
```bash
git status --short
python -m pytest python-inference\tests
python python-inference\scripts\evaluate_sentiment_baseline.py --output python-inference\evaluation\baseline_report.json
```

### 테스트 및 검증 결과
- `python -m pytest python-inference\tests`: 10 passed, 18 warnings.
- baseline dataset total: 40.
- label distribution: `POSITIVE=10`, `NEGATIVE=10`, `MIXED=10`, `NEUTRAL=10`.
- full 4-label accuracy: `0.5`.
- full 4-label macro F1: `0.3348214285714286`.
- low confidence count: `9`, low confidence rate: `0.225`.
- binary-only subset total: 20.
- binary-only accuracy: `1.0`.
- confusion matrix 요약: `POSITIVE` gold 10개는 모두 `POSITIVE`, `NEGATIVE` gold 10개는 모두 `NEGATIVE`; `MIXED` gold 10개는 `POSITIVE` 3개와 `NEGATIVE` 7개로만 예측; `NEUTRAL` gold 10개는 `POSITIVE` 5개와 `NEGATIVE` 5개로만 예측했다.
- baseline 실행 중 Pydantic `model_version` protected namespace warning이 다시 표시됐다.

### 확인된 문제
- 구현 버그: 이번 평가에서도 label mapping 오류는 확인되지 않았다.
- 모델 구조의 한계: baseline은 `MIXED`와 `NEUTRAL`을 한 번도 예측하지 못한다. 이는 현재 모델/API 구조가 binary label만 반환하기 때문에 예상되는 한계다.
- 추가 확인 필요: 40개 수작업 평가셋은 기준선 구축용 소규모 데이터다. 실제 운영 리뷰 분포와 일치하는지는 확인 불가다.

### 의사결정
- 이번 단계에서는 운영 inference, Gateway, Frontend, DB schema를 수정하지 않았다.
- `MIXED`와 `NEUTRAL` 샘플은 full-label 평가에서 오답으로 계산하고, 별도로 `POSITIVE`/`NEGATIVE` gold 샘플만 binary-only metric으로 분리했다.
- confidence 0.7 기준은 성능 보장 기준이 아니라 기존 UI warning 기준과 비교하기 위한 보조 지표로만 사용했다.

### 남은 작업
- 평가 데이터셋을 실제 운영 리뷰 분포에 맞게 확장해야 한다.
- `MIXED`와 `NEUTRAL`을 지원할 방식이 규칙, 모델 교체, cascade, aspect 분석 중 무엇인지 결정해야 한다.
- 다음 단계에서 개선 후보별 offline evaluation 방식을 정해야 한다.

### 다음 작업
- 3단계에서는 운영 로직 변경 전에 `MIXED`/`NEUTRAL` 지원 전략을 설계하고, baseline report와 비교할 개선 목표 metric을 정한다.

### 작업명
KoELECTRA baseline 평가 스크립트 보완

### 작업 목적
- 2단계 baseline 평가 결과에서 누락된 데이터셋 스키마 검증, unsupported label 상태 분리, confidence 통계, high-confidence 사례 추적을 보완한다.
- 콘솔 출력은 사람이 읽을 수 있는 요약으로 바꾸고, 전체 prediction report는 `--output` 지정 시 JSON 파일로 저장한다.

### 작업 전 상태
- 평가 스크립트 초안 이름이 요청 실행 명령의 `evaluate_sentiment_baseline.py`와 달랐다.
- 기본 데이터셋은 `python-inference/evaluation/sentiment_eval_reviews.jsonl`이었다.
- dataset row에 `category`, `review_status`, `source` 필드 검증이 없었다.
- `MIXED`와 `NEUTRAL` 결과가 일반 오답과 충분히 분리되지 않았다.

### 분석 내용
- 실제 프로젝트에 존재하는 데이터셋 파일은 `sentiment_eval_reviews.jsonl`이었다.
- 평가 파일명은 `sentiment_eval_reviews.jsonl`로 유지하고, 실행 스크립트명은 요청 명령에 맞춰 `evaluate_sentiment_baseline.py`로 통일했다.
- 현재 모델이 출력 가능한 label은 `POSITIVE`, `NEGATIVE`뿐이므로 `MIXED`, `NEUTRAL`은 `UNSUPPORTED_EXPECTED_LABEL`로 별도 기록하는 것이 더 정확하다.

### 변경 내용
- 평가 스크립트를 `python-inference/scripts/evaluate_sentiment_baseline.py`로 통일했다.
- `python-inference/evaluation/sentiment_eval_reviews.jsonl`의 모든 row에 `category`, `review_status`, `source`를 추가했다.
- 모든 seed row의 `review_status`를 `PENDING_MANUAL_REVIEW`, `source`를 `SYNTHETIC`으로 통일했다.
- `id`, `text`, `overall_label`, `aspects`, `category`, `note`, `review_status`, `source` 필수 검증과 중복 id 검출을 추가했다.
- prediction에 `result_status`, `is_high_confidence_mismatch`, `is_high_confidence_unsupported`를 추가했다.
- `four_class_diagnostic_metrics`와 `binary_supported_metrics`를 분리했다. 하위 호환용으로 `binary_only_metrics`도 같은 값을 유지했다.
- report metadata와 disclaimer를 추가했다.
- `docs/SENTITRACK_SENTIMENT_LABEL_POLICY.md`에 기본 데이터셋 파일명과 스키마, 지표 의미 구분을 반영했다.
- `python-inference/tests/test_evaluate_sentiment_baseline.py`를 새 리포트 구조에 맞춰 확장했다.

### 실행한 명령
```bash
git status --short
python -m pytest python-inference\tests
python python-inference\scripts\evaluate_sentiment_baseline.py
python python-inference\scripts\evaluate_sentiment_baseline.py --output python-inference\evaluation\baseline_report.json
```

### 테스트 및 검증 결과
- `python -m pytest python-inference\tests`: 16 passed, 18 warnings.
- 경고: MLflow/Pydantic deprecated validator warnings와 Pydantic `model_version` protected namespace warning이 표시됐다.
- `python python-inference\scripts\evaluate_sentiment_baseline.py`: 성공, 콘솔에 요약만 출력.
- `python python-inference\scripts\evaluate_sentiment_baseline.py --output python-inference\evaluation\baseline_report.json`: 성공, 전체 JSON report 저장.
- baseline dataset total: 40.
- label distribution: `POSITIVE=10`, `NEGATIVE=10`, `MIXED=10`, `NEUTRAL=10`.
- binary supported accuracy: `1.0`.
- binary supported macro F1: `1.0`.
- four-class diagnostic exact match rate: `0.5`.
- low confidence count: `9`, low confidence rate: `0.225`.

### 확인된 문제
- 구현 버그: `POSITIVE`/`NEGATIVE` 지원 범위에서는 이번 seed dataset 기준 mismatch가 0건이었다.
- 모델 구조의 한계: `MIXED` 10건과 `NEUTRAL` 10건은 모두 `UNSUPPORTED_EXPECTED_LABEL`로 분리됐다.
- high-confidence mismatch: 0건.
- high-confidence unsupported: 11건.
- unsupported label 분포: `MIXED -> POSITIVE 3, NEGATIVE 7`, `NEUTRAL -> POSITIVE 5, NEGATIVE 5`.
- 평균 confidence: overall `0.8752836957573891`, gold `POSITIVE 0.9796366035938263`, gold `NEGATIVE 0.9945662915706635`, gold `MIXED 0.7983918488025665`, gold `NEUTRAL 0.7285400390625`.
- predicted label별 평균 confidence: `POSITIVE 0.8927861849466959`, `NEGATIVE 0.8609634773297743`.
- mismatch 평균 confidence: `0.0` 정책값. 이번 평가에서 mismatch가 0건이기 때문이다.
- unsupported expected label 평균 confidence: `0.7634659439325333`.

### 의사결정
- 기본 데이터셋 파일명은 기존 실제 파일인 `sentiment_eval_reviews.jsonl`로 통일했다.
- 수작업 검토 전 synthetic seed임을 report metadata disclaimer에 명시했다.
- `MIXED`/`NEUTRAL`의 `is_correct`는 false가 아니라 `null`로 기록한다.
- 0건 평균 confidence는 `0.0`으로 통일했다.

### 남은 작업
- `PENDING_MANUAL_REVIEW` seed dataset을 사람이 검토해 최종 gold dataset으로 승격할지 결정해야 한다.
- 운영 데이터와 seed dataset의 분포 차이는 아직 확인되지 않았다.
- high-confidence unsupported 사례는 모델 개선 또는 보완 로직의 우선 검토 대상이다.

### 다음 작업
- `MIXED`/`NEUTRAL`을 지원하는 개선 후보를 설계하고, 같은 `baseline_report.json` 구조로 개선 전후 metric을 비교한다.
