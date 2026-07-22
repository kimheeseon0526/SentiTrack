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

### 작업명
절 단위 KoELECTRA 하이브리드 MIXED 탐지 실험

### 작업 목적
- 현재 전체 문장 KoELECTRA 이진 분류 baseline과 절 단위 하이브리드 분석을 같은 synthetic seed dataset으로 비교한다.
- 규칙은 감정을 직접 판단하지 않고 대비 표현과 절 경계만 찾으며, 절별 `POSITIVE`/`NEGATIVE` 판단은 기존 KoELECTRA 모델에 맡긴다.
- 이번 단계에서는 `MIXED` 탐지만 실험하고 `NEUTRAL` 해결은 범위에서 제외한다.

### 작업 전 baseline
- 평가 데이터셋: `python-inference/evaluation/sentiment_eval_reviews.jsonl`.
- 데이터 수: `POSITIVE=10`, `NEGATIVE=10`, `MIXED=10`, `NEUTRAL=10`, 총 40건.
- baseline binary supported accuracy: `1.0`.
- baseline `MIXED` 강제 분류 분포: `POSITIVE=3`, `NEGATIVE=7`.
- baseline `NEUTRAL` 강제 분류 분포: `POSITIVE=5`, `NEGATIVE=5`.
- 대표 문장 `향은 너무 좋지만 지속력이 별로예요.`는 baseline에서 `NEGATIVE`, confidence `0.9720079898834229`였다.

### 절 단위 하이브리드 분석 이론
- 원문 전체를 먼저 baseline으로 예측한다.
- 대비 표현을 탐지하고 절 단위로 분리한다.
- 분리된 각 절을 동일 KoELECTRA predictor로 예측한다.
- 절별 label이 모두 같으면 해당 label을 사용하고, `POSITIVE`와 `NEGATIVE`가 모두 있으며 양쪽 confidence가 기준 이상이면 실험 label을 `MIXED`로 둔다.
- 조건이 부족하면 baseline label로 fallback한다.

### 절 분리 정책
- 독립형 대비 표현: `하지만`, `그러나`, `그런데`, `근데`, `다만`, `반면`, `반면에`.
- 연결 어미: `지만`, `는데`, `은데`, `ㄴ데`.
- 대비 표현은 MIXED 판정 조건이 아니라 절 분리 후보로만 사용했다.
- 너무 짧거나 의미 없는 절이 나오면 baseline fallback을 사용한다.

### confidence fallback 정책
- confidence threshold: `0.7`.
- 절 label이 `POSITIVE`와 `NEGATIVE`로 갈리더라도 양쪽 confidence가 모두 `0.7` 이상일 때만 `MIXED`로 확정한다.
- 한쪽 confidence가 낮으면 `LOW_CONFIDENCE_MIXED_CANDIDATE`로 기록하고 baseline label을 유지한다.
- predictor 오류, 대비 구조 없음, 잘못된 절 분리는 baseline label을 유지한다.

### 생성 및 수정 파일
- `python-inference/experiments/__init__.py`
- `python-inference/experiments/clause_sentiment.py`
- `python-inference/scripts/evaluate_clause_sentiment.py`
- `python-inference/tests/test_clause_sentiment.py`
- `python-inference/evaluation/clause_experiment_report.json`
- `docs/SENTITRACK_AI_ENHANCEMENT_LOG.md`

### 실행한 명령
```bash
git status --short --untracked-files=all
python -m pytest python-inference\tests
python python-inference\scripts\evaluate_clause_sentiment.py
python python-inference\scripts\evaluate_clause_sentiment.py --output python-inference\evaluation\clause_experiment_report.json
```

### 테스트 결과
- `python -m pytest python-inference\tests`: 39 passed, 18 warnings.
- 경고: MLflow/Pydantic deprecated validator warnings와 Pydantic `model_version` protected namespace warning이 표시됐다.

### baseline과 experiment 비교
- baseline exact match count: `20`.
- experimental exact match count: `22`.
- improvement count: `2`.
- regression count: `0`.
- clause split count: `9`.
- fallback count: `34`.
- confidence 때문에 MIXED를 보류한 문장 수: `3`.
- `NEUTRAL`은 `NOT_TARGETED_IN_THIS_EXPERIMENT`로 별도 집계했다.

### MIXED recall/precision/F1
- mixed precision: `1.0`.
- mixed recall including policy review: `0.2`.
- mixed recall excluding policy review: `0.2222222222222222`.
- mixed F1 including policy review: `0.33333333333333337`.
- mixed F1 excluding policy review: `0.3636363636363636`.
- mixed_contrast recall 임시 기준 `0.75`는 충족하지 못했다.

### POSITIVE/NEGATIVE regression
- POSITIVE/NEGATIVE accuracy: `1.0`.
- POSITIVE retention rate: `1.0`.
- NEGATIVE retention rate: `1.0`.
- POSITIVE/NEGATIVE regression: 0건.

### false MIXED 사례
- false MIXED count: `0`.
- false MIXED 문장: 없음.

### 개선된 사례
- `eval-028`: `용량은 넉넉하지만 향이 너무 빨리 날아가요.` baseline `NEGATIVE`, experiment `MIXED`.
- `eval-030`: `선물 받은 사람은 좋아했지만 저는 향이 강하게 느껴졌어요.` baseline `POSITIVE`, experiment `MIXED`.

### 악화된 사례
- regression count: `0`.
- 악화된 문장: 없음.

### 라벨 정책 검토가 필요한 데이터
- `eval-029`: `향 자체는 무난한데 가격이 조금 부담돼요.`
- aspects가 `NEUTRAL + NEGATIVE`인데 overall label이 `MIXED`라 `LABEL_POLICY_REVIEW_REQUIRED`로 표시했다.
- 자동 수정하지 않았다.

### 대표 문장 결과
- 문장: `향은 너무 좋지만 지속력이 별로예요.`
- baseline: `NEGATIVE`, confidence `0.9720079898834229`.
- 절 분리: `향은 너무 좋지만` / `지속력이 별로예요.`
- 절별 예측: 첫 절 `NEGATIVE` confidence `0.6021797060966492`, 두 번째 절 `NEGATIVE` confidence `0.9960739612579346`.
- 실험 label: `NEGATIVE`.
- 목표했던 `MIXED` 탐지에는 실패했다.

### 채택 또는 보류 판단
- 이번 clause hybrid 실험은 POSITIVE/NEGATIVE regression과 false MIXED는 억제했지만, 핵심 목표인 mixed_contrast recall과 대표 문장 MIXED 탐지 기준을 충족하지 못했다.
- 운영 반영은 보류한다.

### 남은 문제
- `지만`이 포함된 긍정 절을 KoELECTRA가 부정으로 보는 사례가 있다.
- 절을 보존하는 방식과 모델 입력에 맞게 문장성을 회복하는 방식 사이의 정책 결정이 필요하다.
- synthetic seed dataset은 여전히 `PENDING_MANUAL_REVIEW` 상태이므로 최종 성능으로 해석하면 안 된다.

### 다음 작업
- [해결됨] 절 분리 후 모델 입력을 어떻게 정규화할지 별도 실험한다. → 아래 "절 정규화 전략별 KoELECTRA MIXED 탐지 비교 실험" 단계에서 RAW/SIMPLE_DECLARATIVE/HANGUL_AWARE_DECLARATIVE 세 전략으로 실험 완료.
- [해결됨] 규칙 기반 감정 보정 없이도 긍정 절의 오분류를 줄일 수 있는지 평가한다. → 같은 실험에서 SIMPLE_DECLARATIVE 정규화로 POSITIVE/NEGATIVE regression 0건 유지하며 개선 확인.
- [부분 해결] 필요하면 aspect 기반 분석 또는 별도 mixed detector 실험을 설계한다. → aspect 분석은 별도 "LLM 기반 구조화 감정 및 aspect 분석" 단계로 진행. 별도 mixed detector(비-LLM)는 설계하지 않음, 미해결로 유지.

### 작업명
절 정규화 전략별 KoELECTRA MIXED 탐지 비교 실험

### 작업 목적
- 3단계에서 실패한 대표 문장 `향은 너무 좋지만 지속력이 별로예요.`의 원인이 불완전한 대비 절 입력인지 확인한다.
- 운영 감정 분석 로직을 변경하지 않고, offline 실험에서 절 입력 정규화 전략별 성능 차이를 비교한다.
- `RAW`, `SIMPLE_DECLARATIVE`, `HANGUL_AWARE_DECLARATIVE` 세 전략을 같은 synthetic seed dataset으로 비교한다.

### 작업 전 상태
- 3단계 clause hybrid 실험은 POSITIVE/NEGATIVE regression과 false MIXED는 0건이었지만 mixed recall이 `0.2`에 머물렀다.
- 대표 문장 첫 절 `향은 너무 좋지만`은 raw 절 입력에서 `NEGATIVE`, confidence `0.6021797060966492`로 예측됐다.
- 이번 작업도 `python-inference/main.py`, Gateway, Frontend, DB schema 등 운영 코드는 수정하지 않는 offline 실험이다.

### 정규화 전략
- `RAW`: 절을 그대로 KoELECTRA에 입력한다.
- `SIMPLE_DECLARATIVE`: `지만`, `았지만`, `었지만`, `였지만`, `는데`, `은데`, `인데` 등 대비 어미를 평서형 종결로 바꾼다.
- `HANGUL_AWARE_DECLARATIVE`: simple 규칙에 더해 종성 `ㄴ`이 붙은 형용사형 절을 원형에 가깝게 복원하는 함수를 포함한다. 예: `예쁜데 -> 예쁘다.`, `빠른데 -> 빠르다.`, `강한데 -> 강하다.`, `포근한데 -> 포근하다.`

### 생성 및 수정 파일
- `python-inference/experiments/clause_normalization.py`
- `python-inference/scripts/evaluate_clause_normalization.py`
- `python-inference/tests/test_clause_normalization.py`
- `python-inference/evaluation/clause_normalization_report.json`
- `docs/SENTITRACK_AI_ENHANCEMENT_LOG.md`

### 실행한 명령
```bash
python -m pytest python-inference\tests
python python-inference\scripts\evaluate_clause_normalization.py
python python-inference\scripts\evaluate_clause_normalization.py --output python-inference\evaluation\clause_normalization_report.json
```

### 테스트 결과
- 최초 `python -m pytest python-inference\tests`: 62 passed, 8 failed, 18 warnings.
- 실패 원인: 대표 문장이 없는 단위 테스트 데이터에서 strategy comparison이 `KeyError`를 냈고, 절별 predictor 예외가 baseline fallback으로 처리되지 않았다.
- 보완 후 `python -m pytest python-inference\tests`: 70 passed, 18 warnings.
- 경고: MLflow/Pydantic deprecated validator warnings와 Pydantic `model_version` protected namespace warning이 표시됐다.

### 전략별 결과
- `RAW`: POSITIVE/NEGATIVE accuracy `1.0`, mixed recall `0.2`, mixed precision `1.0`, mixed F1 `0.33333333333333337`, mixed_contrast recall `0.2222222222222222`, improvement `2`, regression `0`, false MIXED `0`.
- `SIMPLE_DECLARATIVE`: POSITIVE/NEGATIVE accuracy `1.0`, mixed recall `0.3`, mixed precision `1.0`, mixed F1 `0.4615384615384615`, mixed_contrast recall `0.3333333333333333`, improvement `3`, regression `0`, false MIXED `0`.
- `HANGUL_AWARE_DECLARATIVE`: POSITIVE/NEGATIVE accuracy `1.0`, mixed recall `0.3`, mixed precision `1.0`, mixed F1 `0.4615384615384615`, mixed_contrast recall `0.3333333333333333`, improvement `3`, regression `0`, false MIXED `0`.

### 대표 문장 결과
- 문장: `향은 너무 좋지만 지속력이 별로예요.`
- baseline: `NEGATIVE`, confidence `0.9720079898834229`.
- `RAW`: 첫 절 `향은 너무 좋지만` -> `NEGATIVE`, confidence `0.6021797060966492`; 최종 `NEGATIVE`.
- `SIMPLE_DECLARATIVE`: 첫 절 `향은 너무 좋다.` -> `POSITIVE`, confidence `0.5735089182853699`; 두 번째 절 `지속력이 별로예요.` -> `NEGATIVE`, confidence `0.9960739612579346`; confidence threshold `0.7` 미달로 최종 `NEGATIVE`, fallback `LOW_CONFIDENCE_MIXED_CANDIDATE`.
- `HANGUL_AWARE_DECLARATIVE`: 대표 문장에서는 simple과 동일하게 최종 `NEGATIVE`, fallback `LOW_CONFIDENCE_MIXED_CANDIDATE`.
- 정규화는 첫 절의 label을 `NEGATIVE -> POSITIVE`로 바꾸는 데 성공했지만, confidence가 낮아 목표했던 `MIXED` 확정에는 실패했다.

### prediction flip 및 패턴 통계
- `SIMPLE_DECLARATIVE`, `HANGUL_AWARE_DECLARATIVE` 모두 prediction changed count `3`, `NEGATIVE -> POSITIVE` count `3`, `POSITIVE -> NEGATIVE` count `0`.
- flip 사례: `eval-021`의 `향은 너무 좋지만 -> 향은 너무 좋다.`, `eval-022`의 `배송은 빨랐지만 -> 배송은 빨랐다.`, `eval-030`의 `선물 받은 사람은 좋아했지만 -> 선물 받은 사람은 좋아했다.`
- `지만` 패턴은 7개 절에서 정규화됐고 MIXED 탐지 3건, improvement 3건, regression 0건이었다.
- `는데`, `은데` 패턴은 각각 1개 절에서 정규화됐지만 MIXED 개선은 없었다.
- unnatural normalization은 0건이었다.

### 개선 및 악화 사례
- `SIMPLE_DECLARATIVE`, `HANGUL_AWARE_DECLARATIVE` 개선 사례: `eval-023`, `eval-024`, `eval-028`.
- `RAW` 개선 사례: `eval-028`, `eval-030`.
- 모든 전략에서 POSITIVE/NEGATIVE regression은 0건이었다.
- 모든 전략에서 false MIXED는 0건이었다.

### 채택 또는 보류 판단
- 후보 선택 결과는 `SIMPLE_DECLARATIVE`, status `EXPERIMENTAL_BEST_BUT_BELOW_THRESHOLD`였다.
- 통과한 기준: POSITIVE/NEGATIVE accuracy >= `0.95`, regression <= `1`, false MIXED <= `1`.
- 통과하지 못한 기준: mixed_contrast recall >= `0.75`, 대표 문장 `MIXED` 탐지.
- 따라서 이번 정규화 전략은 운영 반영하지 않고 실험 결과로만 보류한다.

### 남은 문제
- 정규화는 일부 절의 label 방향을 바로잡았지만 confidence threshold를 넘기지 못하는 핵심 사례가 남았다.
- `HANGUL_AWARE_DECLARATIVE`는 현재 seed dataset에서 simple 대비 추가 이득을 만들지 못했다.
- `NEUTRAL`은 이번 실험 대상이 아니며 여전히 binary 모델의 지원 범위 밖이다.
- synthetic seed dataset은 `PENDING_MANUAL_REVIEW` 상태이므로 최종 성능으로 해석하면 안 된다.

### 다음 작업
- [해결됨] confidence threshold 정책을 고정할지, label flip 자체를 mixed candidate로 활용할지 별도 기준을 설계한다. → 260721 "clause_normalization을 /predict에 연결" 작업(커밋 `8b5e869`)에서 기존 0.7 threshold를 그대로 유지하며 `SIMPLE_DECLARATIVE`를 배선하는 쪽으로 결정. label flip 자체를 별도 candidate 신호로 쓰는 방식은 도입하지 않음.
- [부분 해결] aspect 단위 분석 또는 별도 mixed detector를 추가 실험한다. → aspect 분석은 "LLM 기반 구조화 감정 및 aspect 분석" 단계로 진행. 별도 mixed detector는 미설계로 남음.
- seed dataset을 사람이 검토한 뒤 gold dataset으로 승격할지 결정한다. (미해결)

### 작업명
LLM 기반 구조화 감정 및 aspect 분석 offline 실험 기반 구축

### 작업 목적
- 운영 감정 분석 로직을 변경하지 않고 LLM이 `POSITIVE`, `NEGATIVE`, `MIXED`, `NEUTRAL` 전체 감정 분류와 aspect 추출, aspect별 감정, evidence 추출을 수행할 수 있는 offline 평가 기반을 만든다.
- 같은 synthetic seed dataset에서 KoELECTRA baseline, 절 정규화 최고 실험, LLM structured experiment를 비교할 수 있는 report 구조를 준비한다.
- 이번 단계에서는 실제 외부 API 호출을 하지 않고 mock 검증과 dry-run까지만 수행한다.

### 이전 clause normalization 결과
- 최고 후보는 `SIMPLE_DECLARATIVE`였고 상태는 `EXPERIMENTAL_BEST_BUT_BELOW_THRESHOLD`였다.
- POSITIVE/NEGATIVE accuracy `1.0`, MIXED precision `1.0`, MIXED recall `0.3`, false MIXED `0`, regression `0`이었다.
- 대표 문장 `향은 너무 좋지만 지속력이 별로예요.`는 정규화 후 첫 절 label이 `POSITIVE`로 바뀌었지만 confidence threshold 미달로 최종 `MIXED` 확정에는 실패했다.

### LLM structured output 이론
- LLM은 전체 감정과 aspect 감정을 분리해 JSON으로 반환한다.
- evidence는 원문 리뷰에 실제 존재하는 부분 문자열만 허용한다.
- LLM confidence는 provider output 또는 자기평가 값일 수 있으므로 KoELECTRA score와 같은 의미로 직접 비교하지 않는다.

### prompt version
- `PROMPT_VERSION = "sentiment-aspect-v1"`.
- 향수 및 상품 리뷰 분석 역할, 네 가지 overall label 정의, aspect sentiment 정의, evidence 원문 substring 원칙, 추론 금지 원칙을 포함했다.
- few-shot 예시는 최소화했고 평가 데이터셋 전체를 prompt에 복사하지 않았다.

### schema
- `SCHEMA_VERSION = "llm-sentiment-schema-v1"`.
- `LLMSentimentResult`: `overall_label`, `aspects`, `confidence`, `short_reason`.
- `AspectSentiment`: `name`, `sentiment`, `evidence`.
- overall label은 `POSITIVE`, `NEGATIVE`, `MIXED`, `NEUTRAL`만 허용한다.
- aspect sentiment는 `POSITIVE`, `NEGATIVE`, `NEUTRAL`만 허용한다.
- 빈 aspect name, 원문에 없는 evidence, 중복 `name/sentiment/evidence`, confidence 범위 밖 값, 긴 `short_reason`은 validation error로 처리한다.
- markdown code block 안 JSON은 추출을 시도하되, 실패하면 정상 결과로 임의 보정하지 않는다.

### provider adapter
- 새 dependency를 추가하지 않고 Python 표준 라이브러리 `urllib` 기반 OpenAI-compatible chat completions adapter를 구현했다.
- 환경변수는 `SENTITRACK_LLM_API_KEY`, `SENTITRACK_LLM_MODEL`, `SENTITRACK_LLM_BASE_URL`만 사용한다.
- provider host만 출력하고 API key 값은 코드, 로그, report, 테스트에 기록하지 않는다.
- 오류 유형은 `CONFIGURATION_ERROR`, `TIMEOUT`, `RATE_LIMIT`, `PROVIDER_ERROR`, `INVALID_JSON`, `SCHEMA_VALIDATION_ERROR`, `EVIDENCE_VALIDATION_ERROR`로 분리했다.
- retry는 최대 2회 이하로 제한했다.

### cache 정책
- 기본 cache path는 `python-inference/evaluation/llm_sentiment_cache.jsonl`이다.
- cache key 구성 요소는 review text hash, model, prompt version, schema version이다.
- API key와 request header는 저장하지 않는다.
- `--use-cache` hit이면 provider를 다시 호출하지 않는다.
- `--refresh-cache`는 새 호출 결과를 cache에 append한다.
- `--use-cache`와 `--refresh-cache` 동시 지정은 오류로 처리한다.
- 실제 LLM 응답 cache는 비용과 응답 데이터 저장소 정책이 필요하므로 `.gitignore`에 추가했다.

### 비용 안전장치
- 기본 limit은 5로 설정했다.
- dry-run은 실제 API 호출을 수행하지 않고 expected API call count와 actual API call count를 분리해 출력한다.
- 전체 40건 호출은 사용자가 명시적으로 `--limit 40`을 지정할 때 수행하도록 안내한다.
- 환경변수가 없으면 실제 평가 모드에서 API 호출을 시도하지 않고 `missing_llm_configuration` 오류를 출력한다.

### 생성 및 수정 파일
- `.gitignore`
- `python-inference/experiments/llm_sentiment_schema.py`
- `python-inference/experiments/llm_sentiment_prompt.py`
- `python-inference/experiments/llm_sentiment_client.py`
- `python-inference/scripts/evaluate_llm_sentiment.py`
- `python-inference/tests/test_llm_sentiment.py`
- `python-inference/evaluation/llm_sentiment_experiment_report.json`
- `docs/SENTITRACK_AI_ENHANCEMENT_LOG.md`

### 실행한 명령
```bash
git status --short --untracked-files=all
python -m pytest python-inference\tests
python python-inference\scripts\evaluate_llm_sentiment.py --dry-run --limit 5
python -m pytest python-inference\tests
python python-inference\scripts\evaluate_llm_sentiment.py --dry-run --limit 5 --output python-inference\evaluation\llm_sentiment_experiment_report.json
```

### 테스트 결과
- 최초 전체 테스트: 92 passed, 1 failed, 18 warnings.
- 실패 원인: cache key의 `PROMPT_VERSION` 기본 인자가 함수 정의 시점 값으로 고정되어 prompt version 변경 시 cache miss가 발생하지 않았다.
- 수정 후 `python -m pytest python-inference\tests`: 93 passed, 18 warnings.
- 경고: MLflow/Pydantic deprecated validator warnings와 Pydantic `model_version` protected namespace warning이 표시됐다.

### dry-run 결과
- run mode: `DRY_RUN_ONLY`.
- dataset total: `40`.
- requested limit: `5`.
- expected API call count: `5`.
- actual API call count: `0`.
- output report: `python-inference/evaluation/llm_sentiment_experiment_report.json`.
- report metadata의 evaluated_count는 `0`이며 실제 성능 report로 표현하지 않았다.
- 현재 환경에서는 `SENTITRACK_LLM_API_KEY`, `SENTITRACK_LLM_MODEL`, `SENTITRACK_LLM_BASE_URL`이 설정되지 않은 것으로 표시됐다. 값은 노출하지 않았다.

### 실제 API 호출 여부
- 실제 외부 LLM API 호출은 수행하지 않았다.
- 성능 개선 여부도 판단하지 않았다.

### mock 검증 결과
- 정상 JSON parsing, code block JSON 추출, invalid JSON, 허용되지 않은 overall label, 잘못된 aspect sentiment, 빈 aspect name, 원문에 없는 evidence, 중복 aspect, confidence 범위 오류를 검증했다.
- provider timeout, rate limit, retry 최대 횟수, API key 미노출, cache hit/miss, prompt version 변경 시 cache miss를 검증했다.
- dry-run에서 실제 호출이 없고 limit이 적용되는지 검증했다.
- 일부 항목 실패 후 다음 항목을 계속 처리하는지 검증했다.
- overall metric, aspect pair metric, 대표 MIXED mock 결과, POSITIVE mock이 MIXED로 바뀌지 않는지 검증했다.
- 대표 MIXED mock은 `overall_label=MIXED`, `scent=POSITIVE`, `longevity=NEGATIVE`, evidence substring valid로 통과했다.

### 운영 반영 여부
- 운영 코드 변경 없음.
- `python-inference/main.py`, FastAPI `/predict`, `normalize_label()`, Gateway, DB schema, Frontend, Docker production 설정, GitHub Actions, 운영 MLflow 코드는 수정하지 않았다.
- 새 dependency를 추가하지 않았다.

### 완료하지 못한 항목
- 실제 provider 연결과 5건/40건 유료 API 호출은 수행하지 않았다.
- 실제 LLM 성능 metric은 아직 계산하지 않았다.
- provider별 structured output 고유 기능은 사용하지 않았다. 현재 adapter는 provider 종속성을 낮춘 OpenAI-compatible HTTP 방식이다.

### 남은 문제
- 실제 provider가 OpenAI-compatible `/chat/completions`를 지원하는지 확인해야 한다.
- provider별 token usage 필드 차이가 있으면 adapter 보완이 필요하다.
- synthetic seed dataset은 여전히 `PENDING_MANUAL_REVIEW` 상태이므로 실제 성능이나 최종 ground truth로 해석하면 안 된다.
- aspect alias 정책은 아직 도입하지 않았다. `scent`와 `fragrance` 같은 alias는 자동 동일 처리하지 않는다.

### 다음 작업
- 환경변수를 설정한 뒤 먼저 `--limit 5 --use-cache` 또는 `--limit 5 --refresh-cache`로 실제 소량 호출을 검증한다. (미해결 — API 키 부재로 계속 보류, 하단 "기술 부채" 참고)
- [부분 진행] 결과를 검토한 뒤 사용자가 승인하면 `--limit 40`으로 전체 synthetic seed dataset을 평가한다. → 260721 "목표 3 최종 평가"에서 실제 호출 없이 캐시 전용 31/40건만 검증. 나머지 9건은 API 키 부재로 여전히 미완.
- 실제 report의 LLM metrics, hallucinated evidence, missing/additional aspects를 baseline report와 비교한다. (미해결)

### 작업명
LLM Aspect taxonomy normalization offline 검증

### 작업 목적
- 기존 OpenRouter LLM 12건 평가 report의 raw prediction을 변경하지 않고 aspect 이름만 canonical taxonomy 기준으로 정규화해 metric 변화를 확인했다.
- `overall` aspect는 전체 감정인 `overall_label`과 중복되므로 aspect metric에서 제외하는 정책을 별도로 검증했다.
- `satisfaction`, `gift suitability`처럼 상품 속성으로 확정하기 어려운 이름은 자동 매핑하지 않고 `REVIEW_REQUIRED`로 남겼다.

### 작업 전 상태
- 입력 LLM report: `python-inference/evaluation/llm_sentiment_representative_report.json`.
- 입력 gold dataset: `python-inference/evaluation/sentiment_eval_representative_12.jsonl`.
- 기존 12건 LLM 결과는 overall exact match accuracy `1.0`, evidence substring validation rate `1.0`, hallucinated evidence count `0`이었다.
- 기존 raw aspect name F1과 name/sentiment pair F1은 모두 `0.65`였다.
- 대표 aspect 불일치는 `first scent`, `afternote`, `price-performance`, `satisfaction`, `health`, `overall` 처리 정책이었다.

### canonical taxonomy
- canonical aspect는 `scent`, `longevity`, `price`, `design`, `usability`, `packaging`, `delivery`, `volume`, `physical_reaction`, `other`로 정의했다.
- representative 12건 gold dataset에 실제 등장한 non-overall aspect는 `delivery`, `longevity`, `packaging`, `price`, `scent`, `usability`였다.
- `design`, `volume`, `physical_reaction`, `other`는 taxonomy 후보에는 포함되지만 representative 12건 gold에는 등장하지 않았다.
- `overall`은 canonical aspect taxonomy에서 제외했다.

### alias normalization 정책
- 소문자 변환과 앞뒤/중복 공백 정규화 후 exact alias match만 적용했다.
- `first scent -> scent`, `afternote -> scent`, `price-performance -> price`, `spray -> usability`을 검증했다.
- `health`, `headache`, `irritation`은 `physical_reaction` 후보로 정규화할 수 있게 했다.
- `satisfaction`, `gift suitability`는 자동 매핑하지 않고 `REVIEW_REQUIRED`로 남겼다.
- raw predicted aspect name, normalized aspect name, matched alias rule, normalization status를 모두 report에 남겼다.

### 생성 및 수정 파일
- `python-inference/experiments/aspect_taxonomy.py`
- `python-inference/scripts/evaluate_aspect_taxonomy.py`
- `python-inference/tests/test_aspect_taxonomy.py`
- `python-inference/evaluation/aspect_taxonomy_report.json`
- `docs/SENTITRACK_AI_ENHANCEMENT_LOG.md`

### 실행한 명령
```bash
python -m pytest python-inference\tests\test_aspect_taxonomy.py
python python-inference\scripts\evaluate_aspect_taxonomy.py --report python-inference\evaluation\llm_sentiment_representative_report.json --dataset python-inference\evaluation\sentiment_eval_representative_12.jsonl --output python-inference\evaluation\aspect_taxonomy_report.json
python -m pytest python-inference\tests
python -c "import json; r=json.load(open('python-inference/evaluation/aspect_taxonomy_report.json', encoding='utf-8')); print(json.dumps({'raw_f1': r['raw_metrics']['aspect_name_f1'], 'excluding_f1': r['metrics_excluding_overall']['aspect_name_f1'], 'normalized_f1': r['normalized_metrics']['aspect_name_f1'], 'raw_pair_f1': r['raw_metrics']['pair_f1'], 'normalized_pair_f1': r['normalized_metrics']['pair_f1'], 'deltas': r['metric_deltas'], 'remaining_missing': r['remaining_missing_aspects'], 'remaining_additional': r['remaining_additional_aspects'], 'newly_matched': r['newly_matched_by_normalization'], 'review_required': r['review_required_cases'], 'conflicts': r['conflicting_sentiment_cases'], 'api_calls': r['metadata']['api_calls_performed']}, ensure_ascii=False, indent=2))"
git status --short --untracked-files=all
git diff --stat
```

### 테스트 및 검증 결과
- `python -m pytest python-inference\tests\test_aspect_taxonomy.py`: 12 passed, 18 warnings.
- `python -m pytest python-inference\tests`: 105 passed, 18 warnings.
- 경고는 기존 MLflow/Pydantic deprecated validator warnings와 Pydantic `model_version` protected namespace warning이다.
- OpenRouter 또는 외부 LLM API 호출은 수행하지 않았다. `aspect_taxonomy_report.json` metadata의 `api_calls_performed`는 `0`이다.
- 운영 코드 변경 없음. `python-inference/main.py`, Gateway, Frontend, DB schema는 수정하지 않았다.
- 기존 overall 결과는 변경하지 않았다. report에 preserved overall metric으로 exact match accuracy `1.0`을 유지했다.
- evidence validation 결과도 변경하지 않았다. evidence substring validation rate `1.0`, hallucinated evidence count `0`을 유지했다.

### metric 결과
- raw aspect name F1: `0.65`.
- raw name/sentiment pair F1: `0.65`.
- overall 제외 aspect name F1: `0.7500000000000001`.
- overall 제외 pair F1: `0.7500000000000001`.
- taxonomy normalization 적용 aspect name F1: `0.9032258064516129`.
- taxonomy normalization 적용 pair F1: `0.9032258064516129`.
- normalized aspect name F1 delta vs raw: `+0.25322580645161286`.
- normalized pair F1 delta vs raw: `+0.25322580645161286`.

### normalization으로 개선된 항목
- `eval-002`: `first scent`, `afternote`가 `scent`로 정규화되어 gold `scent`와 매칭됐다.
- `eval-003`: `price-performance`가 `price`로 정규화되어 gold `price`와 매칭됐다.

### 남은 불일치
- remaining missing aspect: `eval-013`의 `usability`.
- remaining additional aspects: `eval-011`의 `physical_reaction`, `eval-023`의 `satisfaction`.
- `eval-011`의 `health -> physical_reaction`은 alias 정규화됐지만 representative 12건 gold taxonomy에는 `physical_reaction`이 없어 additional로 남았다.
- `eval-023`의 `satisfaction`은 `REVIEW_REQUIRED`로 남겼다.
- conflicting normalized sentiment case는 0건이었다.
- sentiment mismatch case와 name-only mismatch case도 0건이었다.

### 의사결정
- 이번 단계는 taxonomy 정규화 효과 검증이며 모델 성능 합격 판정 단계가 아니다.
- alias를 성능 개선 목적으로 무분별하게 추가하지 않았다.
- gold dataset과 LLM raw prediction은 변경하지 않았다.
- 동일 canonical name과 sentiment로 중복되는 normalized pair는 metric 계산에서 하나로 취급하고, raw prediction list는 보존했다.
- 동일 canonical name에 서로 다른 sentiment가 들어오는 경우는 자동 병합하지 않고 `CONFLICTING_NORMALIZED_SENTIMENT`로 기록하도록 테스트했다.

### 다음 작업
- `physical_reaction`을 실제 운영 taxonomy로 채택할지, 또는 health/headache 계열을 별도 review bucket으로 둘지 결정해야 한다.
- `satisfaction`을 overall 평가 표현으로 유지할지, 별도 aspect로 허용할지 수작업 정책 검토가 필요하다.
- `eval-013`처럼 LLM이 놓친 `usability` missing case를 prompt 개선 또는 aspect recall 보강 대상으로 검토한다.
### 작업명: LLM Structured Sentiment v2 taxonomy-constrained offline experiment

### 작업 목적
- 기존 LLM structured sentiment 실험에서 자유 형식 aspect 이름이 생성되던 문제를 줄이기 위해 prompt와 Pydantic schema에 canonical taxonomy를 직접 적용했다.
- 운영 inference, FastAPI `/predict`, Gateway, DB, Frontend, Docker/GitHub Actions에는 반영하지 않고 offline 평가 코드만 수정했다.

### 기존 기준
- V1 raw aspect name F1: `0.6500`.
- V1 raw pair F1: `0.6500`.
- V1 + taxonomy post-processing normalized aspect name F1: `0.9032`.
- V1 + taxonomy post-processing normalized pair F1: `0.9032`.

### v2 taxonomy constraint 설계
- Canonical taxonomy: `scent`, `longevity`, `price`, `design`, `usability`, `packaging`, `delivery`, `volume`, `physical_reaction`, `other`.
- Prompt version: `sentiment-aspect-v2-taxonomy`.
- Schema version: `llm-sentiment-schema-v2-taxonomy`.
- `overall`은 aspect name으로 금지하고 전체 감정은 `overall_label`에만 기록한다.
- `first scent`, `afternote`, `price-performance`, `spray`, `health` 같은 alias는 prompt에 안내하되 strict schema에서는 canonical name만 허용한다.
- provider가 `json_schema` response_format을 거부하면 JSON-only prompt 방식으로 fallback하고 report에 `provider_fallback_used`를 기록한다.
- fallback normalization은 raw name을 보존하며, alias match는 `FALLBACK_NORMALIZED`, unknown/overall 계열은 `REVIEW_REQUIRED`로 기록한다. unknown을 임의로 `other`로 바꾸지 않는다.

### 생성 및 수정 파일
- `python-inference/experiments/aspect_taxonomy.py`: v2 fallback taxonomy validation helper 추가.
- `python-inference/experiments/llm_sentiment_prompt.py`: v2 taxonomy-constrained prompt로 교체.
- `python-inference/experiments/llm_sentiment_schema.py`: canonical aspect schema validation 및 JSON schema helper 추가.
- `python-inference/experiments/llm_sentiment_client.py`: structured output request, unsupported response_format fallback, provider flags 기록 추가.
- `python-inference/scripts/evaluate_llm_sentiment.py`: v2 report fields, raw/normalized metrics, strategy comparison, default v2 output 추가.
- `python-inference/tests/test_llm_sentiment_taxonomy_v2.py`: mock 기반 v2 taxonomy/schema/provider/cache/metric tests 추가.
- `python-inference/evaluation/llm_sentiment_taxonomy_v2_report.json`: 대표 12건 dry-run report 생성.
- `docs/SENTITRACK_AI_ENHANCEMENT_LOG.md`: 본 누적 기록 추가.

### 실행 명령
```bash
git status --short --untracked-files=all
python -m pytest python-inference\tests
python python-inference\scripts\evaluate_llm_sentiment.py --dataset python-inference\evaluation\sentiment_eval_representative_12.jsonl --limit 12 --dry-run
git status --short --untracked-files=all
git diff --stat
```

### 테스트 결과
- 최초 전체 pytest: `114 passed, 4 failed, 18 warnings`.
- 실패 원인: 기존 v1 mock call 객체에 새 provider diagnostic 속성이 없어 `prediction_payload()`가 AttributeError를 발생시켰다.
- 수정 후 전체 pytest: `118 passed, 18 warnings`.
- mock taxonomy validation: canonical 허용, alias strict schema 거부, `overall` 거부, `other`/empty aspects 허용, evidence substring validation, duplicate validation, conflicting sentiment 허용, fallback normalization, unknown review-required, structured output unsupported fallback, cache key version 반영, taxonomy metric 계산을 확인했다.

### dry-run 결과
- 명령: `python python-inference\scripts\evaluate_llm_sentiment.py --dataset python-inference\evaluation\sentiment_eval_representative_12.jsonl --limit 12 --dry-run`.
- run mode: `DRY_RUN_ONLY`.
- dataset total: `12`.
- expected API call count: `12`.
- actual API call count: `0`.
- output: `python-inference/evaluation/llm_sentiment_taxonomy_v2_report.json`.
- configuration missing: `SENTITRACK_LLM_API_KEY`, `SENTITRACK_LLM_MODEL`, `SENTITRACK_LLM_BASE_URL`.
- dry-run report의 `sample_schema_validation.ok`: `true`.

### 실제 API 호출 여부
- 실제 OpenRouter 또는 외부 LLM API 호출은 수행하지 않았다.
- v2 성능 개선은 실제 12건 provider 실행 전에는 주장하지 않는다.

### 운영 반영 여부
- 운영 코드 변경 없음.
- `python-inference/main.py`, FastAPI `/predict`, `normalize_label()`, Gateway, DB schema, Frontend, ReviewCard, Docker production 설정, GitHub Actions, 기존 KoELECTRA 운영 모델, production response schema는 수정하지 않았다.

### 완료하지 못한 항목 및 warning
- 실제 provider 12건 실행과 실제 v2 raw F1 측정은 수행하지 않았다.
- dry-run에서는 환경변수 미설정으로 configuration missing이 report에 기록됐다.
- pytest/dry-run 중 기존 MLflow/Pydantic deprecation warnings 및 `PredictResponse.model_version` protected namespace warning이 표시됐다.

### 다음 작업
- 사용자가 환경변수를 설정한 뒤 대표 12건을 실제 실행해 `llm_sentiment_taxonomy_v2_report.json`의 V2 raw canonical F1, pair F1, taxonomy violation count, fallback count를 검토한다.
- provider별 structured output 지원 차이가 실제로 확인되면 adapter fallback 정책을 provider host/model별로 더 세분화한다.

### 작업명: LLM 평가 resume / offset / partial-save 실행 안정화

### 작업 목적
- OpenRouter 무료 모델 rate limit으로 40건 전체 평가가 중간 실패하더라도, 이미 성공한 prediction을 재사용하고 실패 row만 나중에 재시도할 수 있게 했다.
- 운영 inference, FastAPI `/predict`, Gateway, Frontend, DB schema, Docker production 설정, GitHub Actions, MLflow 운영 코드는 변경하지 않았다.

### 40건 전체 평가 실패 원인
- 최근 v1 full40 실행 결과는 `dataset_total=40`, `actual_api_call_count=40`, `successful_predictions=3`, `failed_predictions=37`이었다.
- 실패 유형은 `RATE_LIMIT=36`, `PROVIDER_ERROR=1`로, 무료 provider 호출 제한 누적이 핵심 원인이었다.
- 이 결과 파일은 전체 성능 평가로 사용하기 어렵고, chunk 단위 재실행과 성공 결과 재사용이 필요하다.

### 추가 CLI 옵션
- `--offset`: dataset 원본 index 기준 시작 위치. 예: `--offset 10 --limit 10`은 11번째부터 10건 선택.
- `--resume`: 기존 output report의 성공 prediction(`error is null`)을 재사용하고 실패 prediction만 재시도.
- `--save-partial` / `--no-save-partial`: 기본 true. 처리 중간 결과를 output report에 저장.
- `--stop-on-rate-limit` / `--no-stop-on-rate-limit`: 기본 true. `RATE_LIMIT` 발생 시 이후 호출 중단.
- `--progress` / `--no-progress`: 기본 true. row별 진행 상황 출력.

### resume 병합 규칙
- 기존 output report가 없으면 일반 실행처럼 동작한다.
- 기존 prediction은 `id` 기준으로 로드한다.
- 이번 실행 범위 밖의 기존 prediction은 최종 output에 유지한다.
- 이번 실행 범위 안의 기존 성공 prediction은 재사용한다.
- 이번 실행 범위 안의 기존 실패 prediction은 재시도한다.
- 새 성공은 기존 실패를 대체하고, 새 실패는 최신 error 정보로 갱신한다.
- 최종 predictions는 dataset 원본 순서로 정렬한다.

### cache 재사용 규칙
- cache key는 review text hash, model, prompt version, schema version을 포함한다.
- `--use-cache`에서 cache hit 성공 결과는 API 호출 없이 prediction에 `cache_hit=true`로 기록한다.
- cache hit는 successful prediction으로 계산한다.
- 실패 결과는 cache에 저장하지 않는다.
- `--refresh-cache`는 cache만 무시하고 새 호출을 시도한다. `--resume`의 기존 성공 prediction 재사용이 우선한다.

### rate limit / partial save / progress 규칙
- `RATE_LIMIT`와 `--stop-on-rate-limit=true`가 만나면 즉시 중단하고 partial report를 저장한다.
- metadata에 `stopped_early`, `stop_reason`, `stopped_at_id`, `partial_saved`를 기록한다.
- `PROVIDER_ERROR`, `TIMEOUT`, `INVALID_JSON`, `SCHEMA_VALIDATION_ERROR` 등은 해당 row 실패로 기록하고 다음 row로 진행한다.
- progress 출력 예: `[3/40] eval-003 success overall=POSITIVE latency=12ms cache_hit=false`.
- progress와 report에는 API key, Authorization header, 전체 HTTP header를 기록하지 않는다.

### 생성 및 수정 파일
- `python-inference/scripts/evaluate_llm_sentiment.py`: offset/resume/progress/partial save/stop-on-rate-limit 실행 경로 추가.
- `python-inference/tests/test_llm_sentiment_resume.py`: mock adapter/cache 기반 resume 및 partial-save 테스트 추가.
- `docs/SENTITRACK_AI_ENHANCEMENT_LOG.md`: 이번 작업 기록 추가.

### 테스트 결과
- 명령: `python -m pytest python-inference/tests`
- 결과: `143 passed, 18 warnings`.
- warning은 기존 MLflow/Pydantic deprecation 및 `PredictResponse.model_version` protected namespace warning이다.

### dry-run 결과
- 명령: `python python-inference/scripts/evaluate_llm_sentiment.py --dataset python-inference/evaluation/sentiment_eval_reviews.jsonl --limit 40 --prompt-version sentiment-aspect-v1 --resume --use-cache --dry-run`
- run mode: `DRY_RUN_ONLY`.
- dataset total: `40`.
- offset: `0`.
- requested limit: `40`.
- selected count: `40`.
- expected API call count: `40`.
- actual API call count: `0`.
- reusable success count: `0`.
- retry candidate count: `40`.
- output: `not written`.
- missing configuration: `SENTITRACK_LLM_API_KEY`, `SENTITRACK_LLM_MODEL`, `SENTITRACK_LLM_BASE_URL`.

### 실제 API 호출 여부
- 실제 OpenRouter 또는 외부 LLM API 호출은 수행하지 않았다.
- dry-run과 mock adapter 테스트만 수행했다.

### 다음 작업
- 사용자가 실제 provider 환경변수를 설정한 뒤 5~10건 chunk로 실행한다.
- `RATE_LIMIT`이 발생하면 같은 output path에 대해 `--resume --use-cache`로 재실행한다.
- 여러 chunk가 누적된 뒤 full40 report의 successful/failed count와 normalized aspect metrics를 다시 검토한다.

## 260721

### 작업명
대조/혼합 문장이 POSITIVE로 오분류되는 운영 버그 수정 (clause split + MIXED를 `/predict`에 실제 반영)

### 작업 목적
- "부정 리뷰가 긍정으로 표시되는 오류" 제보 건을 조사 → 원인 확정 → 수정 → 검증까지 진행한다.
- 앞선 실험 단계(3~6단계)에서는 clause split/normalization/LLM 실험을 offline report로만 남기고 운영 코드(`main.py`, Gateway, Frontend)는 건드리지 않았는데, 이번 단계에서는 그 실험 결과 중 `clause_sentiment.py`를 실제 `/predict`에 연결해 운영 버그를 고친다.
- 기존 리뷰 데이터 재분석/재채점, `NEUTRAL` 도입, DB root/app 비밀번호 분리는 범위에서 제외한다.

### 작업 전 상태 — 운영 DB 점검 (읽기 전용, OCI 운영 서버)
- 지정된 LIKE 패턴(별로/실망/아쉬/안좋/최악/하지만/그런데/지만/좋은데)으로 조회 시 0건 — 운영 DB의 리뷰가 총 2건뿐이었기 때문.
- 전체 2건을 직접 확인: id=2 `"제일 좋아하는 꽃향인데 조금 인공적인거 같아요ㅠㅠㅠ"`가 `POSITIVE 0.6702`로 저장되어 있고, 대조 어미 "인데"로 이어지는 전형적인 혼합 문장이었음. id=1은 정상.
- 대표 사례가 1건뿐이라 사용자 승인을 받아 이 사례 + 합성 대조 문장 4건(향은 정말 좋은데 지속력이 별로예요 / 디자인은 예쁘지만 향이 너무 약해요 / 포장은 마음에 드는데 배송이 너무 느렸어요 / 가격은 비싸지만 향은 정말 좋아요)으로 재현 범위를 넓혔다.

### 원인 진단 — 케이스 B(모델 오분류) 확정, 케이스 A(model_version 불일치)는 배제
- **케이스 A 배제 근거**: `python-inference/main.py`는 초기 커밋(2026-06-22, `52a713f`) 이후 수정 이력이 없어 `MODEL_NAME`/`MODEL_REVISION`이 리뷰 생성 시점(2026-06-30)부터 지금까지 동일. `gateway/src/server.ts`도 `/predict` 응답의 `model_version`을 캐싱 없이 그대로 저장만 한다. id=2 원문을 현재 파이프라인에 그대로 넣어 재현한 결과 `POSITIVE 0.6702`로 저장값과 완전히 일치 — 캐싱/버전 기록 버그가 아님.
- **케이스 B 확정**: KoELECTRA 이진 분류기가 문장 전체를 하나의 라벨로 압축하면서 대조 문장의 결론절(부정)을 무시하고 도입부(긍정) 쪽으로 판단.
- 추가로, 이미 구현돼 있던 `experiments/clause_sentiment.py`를 실제 연결하는 과정에서 `ENDING_CONNECTORS`에 `"인데"`가 빠져 있는 걸 발견 — id=2가 "인데" 뒤에서 clause split 자체가 안 돼 대조 감지가 안 됐던 것. `experiments/clause_normalization.py`의 `SIMPLE_SUFFIX_RULES`에는 이미 `("인데", "이다.")` 규칙이 있어 정규화 쪽은 "인데"를 대조 어미로 인지하고 있었는데, split 쪽 목록에만 반영이 안 돼 있었던 두 모듈 간 불일치였음.

### 변경한 파일과 이유
| 파일 | 변경 | 이유 |
|---|---|---|
| `python-inference/experiments/clause_sentiment.py` | `ENDING_CONNECTORS`에 `"인데"` 추가 | "인데"로 끝나는 대조절이 clause split 대상에서 누락되어 있었음 |
| `python-inference/main.py` | `/predict`에서 `sentiment_pipeline(text)` 단일 호출 대신 `analyze_clause_sentiment(text, _predict_clause)` 사용. `label`이 `experimental_label`(POSITIVE/NEGATIVE/MIXED)이 되도록 변경, MLflow에 `contrast_detected` 태그 추가 | 대조 문장을 clause 단위로 재분류해 두 절 confidence가 모두 0.7 이상으로 갈릴 때만 `MIXED` 반환 (false-MIXED 방지 로직은 기존 실험 모듈 그대로 재사용) |
| `python-inference/Dockerfile` | `COPY experiments ./experiments` 추가 | `main.py`가 `experiments.clause_sentiment`를 import하게 됐는데, 기존 Dockerfile은 `main.py`만 이미지에 복사해 실제 배포 시 `ModuleNotFoundError`로 컨테이너가 죽었을 것 — 배포 전에 발견해 같이 수정 |
| `frontend/lib/types.ts` | `sentimentLabel` 타입에 `"MIXED"` 추가 | 새 라벨 값을 타입 시스템에 반영 |
| `frontend/app/globals.css` | `--color-mixed-*` 변수, `.ac-badge-mixed` 클래스 추가 | MIXED 전용 배지 색상 (기존 각진 무테두리 디자인 원칙 유지) |
| `frontend/components/ReviewCard.tsx`, `ArchiveCard.tsx` | `isPositive` 불리언 삼항 연산 → `sentimentLabel` 기반 색상/배지 매핑 테이블로 교체 | 기존 구조는 `isPositive ? "POSITIVE" : "NEGATIVE"`라 MIXED가 들어오면 화면에 "NEGATIVE"로 잘못 표시됐을 것 |
| `frontend/app/me/page.tsx` | `negativeCount = reviews.length - positiveCount` → `NEGATIVE` 직접 필터링 + `mixedCount` 통계 박스 추가, 리뷰 카드 배경색도 매핑 테이블 기반으로 변경 | 기존 계산식은 MIXED 리뷰를 전부 "아쉬운 리뷰" 수치에 합산해버리는, 지금 고치는 것과 같은 클래스의 버그였음 |
| `python-inference/scripts/reproduce_prod_mismatch.py`, `verify_prod_mismatch_fix.py` (신규) | 운영 사례 재현 및 수정 전/후 비교 스크립트 | 재현 결과를 파일로 남겨 검증 근거로 사용 |

DB 스키마(`sentitrack_reviews.sentiment_label VARCHAR(20)`)는 ENUM이 아니라 `"MIXED"` 저장에 ALTER 불필요 — 실행하지 않음. gateway도 라벨을 그대로 통과시키는 구조라 변경 없음.

### 실행한 명령
```bash
python python-inference/scripts/reproduce_prod_mismatch.py
python -m pytest python-inference/tests -q
python python-inference/scripts/verify_prod_mismatch_fix.py
cd gateway && npm run build
cd frontend && npm run build
```

### 재현 테스트 결과 (수정 전 / 후 비교)
같은 모델/revision(`jaehyeong/koelectra-base-v3-generalized-sentiment-analysis`, `370f325c...`)을 로컬에 로드해 재현.

| 사례 | 문장 | 수정 전 | 수정 후 |
|---|---|---|---|
| prod-2 (운영 id=2) | 제일 좋아하는 꽃향인데 조금 인공적인거 같아요ㅠㅠㅠ | POSITIVE 0.6702 | **MIXED** 0.6702 |
| synthetic-1 | 향은 정말 좋은데 지속력이 별로예요. | NEGATIVE 0.9768 | NEGATIVE 0.9768 (회귀 없음) |
| synthetic-2 | 디자인은 예쁘지만 향이 너무 약해요. | NEGATIVE 0.9731 | NEGATIVE 0.9731 (회귀 없음) |
| synthetic-3 | 포장은 마음에 드는데 배송이 너무 느렸어요. | NEGATIVE 0.8921 | NEGATIVE 0.8921 (회귀 없음) |
| synthetic-4 | 가격은 비싸지만 향은 정말 좋아요. | POSITIVE 0.9049 | POSITIVE 0.9049 (회귀 없음) |

원본 데이터: `python-inference/evaluation/prod_mismatch_reproduction.json`(수정 전), `prod_mismatch_fix_verification.json`(수정 후).

추가 검증:
- `python-inference/tests` 전체 147개 테스트 통과 (`ENDING_CONNECTORS` 변경 후 재실행, 기존 `test_clause_sentiment.py` 포함 회귀 없음)
- `gateway`: `npm run build`(`tsc`) 성공
- `frontend`: `npm run build`(`next build`, TypeScript 체크 포함) 성공

### 남은 문제
- **MIXED confidence_score는 baseline(원문장 전체) 확신도를 재사용**하며, clause별 확신도나 MIXED 판정 자체의 확신도가 아님. 추후 최종 평가(3단계) 때 재설계 검토 필요.
- 운영 DB의 id=2는 여전히 `POSITIVE`로 남아 있음 — 기존 리뷰 재평가는 이번 범위에서 제외했으므로 신규 리뷰부터만 정확히 기록됨.
- confidence threshold(0.7) 미만인 대조 문장은 여전히 이진 라벨로 남음 (synthetic-1/2/3처럼 한쪽 절 confidence가 낮으면 안전하게 baseline으로 폴백 — false-MIXED 방지가 의도된 동작이지만 일부 진짜 혼합 문장은 여전히 놓칠 수 있음).
- `ENDING_CONNECTORS`는 하드코딩 목록: "인데"는 추가했지만 "치고", "라도", 어미 없는 문맥적 대조 등은 여전히 미탐지.
- 대조 표현이 감지되면 `/predict` 1회 호출이 최대 3회 모델 추론(전체 문장 + 절 2개)으로 늘어남 — 별도 성능/레이턴시 테스트는 하지 않음.
- 운영 데이터가 2건뿐이라 실제 트래픽에서의 커버리지는 사실상 검증되지 않은 상태 — 리뷰가 더 쌓이면 재점검 필요.
- `ProductReviewSection`의 필터는 "전체보기/긍정적 향기/아쉬운 향기" 3개뿐이며 MIXED 전용 필터 탭은 추가하지 않음 (전체보기에서는 정상 노출, 범위 최소화를 위해 신규 필터 UI는 넣지 않음).

### 다음 작업
- 이번 커밋이 배포된 뒤 신규 리뷰에서 실제로 MIXED가 정상 기록/표시되는지 운영 환경에서 모니터링한다.
- 기존 리뷰(id=2 포함) 재분석 여부와 방식(배치 재채점 스크립트 등)을 별도로 결정한다.
- root/app DB 비밀번호 분리는 별도 작업으로 진행한다.

### 작업명
목표 3 최종 평가 — KoELECTRA·Normalization·LLM 수치 재검증 (실제 `/predict` 기준)

### 작업 목적
- 앞서 기록된 오프라인 실험 수치(clause 실험, normalization 실험, LLM taxonomy 실험)를 실제 운영 코드(`main.py`의 `/predict`, 오늘 수정된 clause split + MIXED 로직)와 실제 저장된 LLM 캐시로 다시 검증해, 포트폴리오에 인용할 최종 수치를 확정한다.
- 새 기능/모델 추가 없이 기존 구현의 정확성 검증에만 집중한다.

### 1단계 — KoELECTRA + clause split 재측정 (실제 `/predict`, 40건)
- 데이터셋: `python-inference/evaluation/sentiment_eval_reviews.jsonl` (POSITIVE10/NEGATIVE10/MIXED10/NEUTRAL10). 기존 기록 참조 파일: `evaluation/clause_normalization_report.json`.
- 신규 스크립트 `python-inference/scripts/evaluate_predict_endpoint.py`로 실제 `/predict` 엔드포인트(오늘 수정된 clause split + MIXED 로직)를 40건 전체에 호출해 재측정.

| 지표 | 기존 기록 RAW(offline) | 기존 기록 SIMPLE_DECLARATIVE(offline) | 이번 재측정 (실제 /predict) |
|---|---|---|---|
| MIXED Recall | 0.20 | 0.30 | **0.20** |
| MIXED Precision | 1.0 | 1.0 | 1.0 |
| MIXED F1 | 0.333 | 0.4615 | 0.333 |
| POSITIVE/NEGATIVE Accuracy | 1.0 | 1.0 | 1.0 |
| 4-class exact match (전체 40건) | 22/40=0.55 | 23/40=0.575 | 22/40=0.55 |

Confusion Matrix (실제 `/predict`, gold×predicted): POSITIVE 10/10, NEGATIVE 10/10, MIXED→{POSITIVE 2, NEGATIVE 6, MIXED 2}, NEUTRAL→{POSITIVE 5, NEGATIVE 5}(모델이 NEUTRAL을 출력하지 않으므로 설계상 0). MIXED 정답 2건(eval-028, eval-030)은 과거 "RAW"(정규화 미적용) 실험과 완전히 동일.

**차이 원인**: `main.py`의 `/predict`는 `experiments/clause_sentiment.py`(절 분리)만 연결했고, MIXED Recall을 0.20→0.30으로 올렸던 `clause_normalization.py`(절 텍스트 정규화, 예: "좋지만"→"좋다.")는 실제 엔드포인트에 배선되지 않았다. 즉 0.30은 오프라인 실험에서만 확인된 수치이고, 프로덕션의 정직한 현재 수치는 **0.20**이다. 오늘 추가한 `ENDING_CONNECTORS`의 "인데"는 이 40건 데이터셋에 해당 어미 사례가 없어 영향 없음. 산출물: `evaluation/predict_endpoint_full40_report.json`.

### 2단계 — LLM v1 + taxonomy 12건 재확인
- 이 환경에는 `SENTITRACK_LLM_API_KEY`/`MODEL`/`BASE_URL`이 프로세스/사용자/머신 어떤 범위에도 설정되어 있지 않음(레포 `.env`에도 없음) — 확인 결과 실제 API 호출 자체가 불가능한 상태.
- 12건 텍스트가 `model=openrouter/free, prompt_version=sentiment-aspect-v1, schema_version=llm-sentiment-schema-v1` 조합으로 전부(12/12) 이미 캐시에 존재함을 확인 → `evaluate_llm_sentiment.py --use-cache`로 실제 네트워크 호출 0건인 재실행 수행 (`evaluation/llm_sentiment_v1_reverify_report.json`).
- 결과: `exact_match_accuracy = 0.9167`(11/12, 기존 1.0). `eval-033` 1건만 gold(NEUTRAL)와 불일치(POSITIVE로 예측).
- 원인 조사: `eval-033`의 캐시 원문을 기존 리포트와 비교한 결과, 기존 리포트는 `cache_hit:false`(최초 실제 호출)였고 현재 캐시는 다른 세션에서 같은 텍스트로 다시 호출된 **비결정적 응답으로 덮어써진 상태**였음. `experiments/llm_sentiment_client.py`의 `JsonlLLMCache`는 append-only JSONL을 순서대로 읽어 같은 cache_key를 **나중 값이 덮어쓰는(last-write-wins)** 구조라, 이후 세션(예: 40건 시도)에서 겹치는 텍스트를 재호출하면 조용히 과거 캐시가 교체됨.
- 영향 범위를 더 넓게 확인하니 12건 중 8건의 `predicted_aspects`가 원본 리포트와 다른 내용(예: `scent`→`smell`, `health`→`headache`, 영어↔한글 aspect명 혼재)으로 바뀌어 있었음 — overall_label은 대부분 안 바뀌었지만 aspect 이름 자체가 달라짐.
- `evaluate_aspect_taxonomy.py`로 재계산한 taxonomy 정규화 aspect F1: **0.4667** (raw 0.2051) — 기존 기록 0.9032/raw 0.65와 크게 다름. **이는 taxonomy 정규화 코드의 결함이 아니라 캐시 재사용의 재현성 한계다.** 산출물: `evaluation/aspect_taxonomy_reverify_report.json`.
- 판단: overall 정확도(0.9167)와 기존 aspect F1(0.9032, 단일 세션 실측치)은 여전히 유효한 기록으로 유지하되, "캐시 기반 재현은 aspect 이름 수준에서 신뢰할 수 없다"는 사실을 새로운 제약사항으로 기록한다.

### 3단계 — OpenRouter 40건 전체 평가 시도
- 2단계에서 확인한 것과 동일한 이유로 실제 API 호출이 불가능함. 가짜 자격증명으로 `--resume`을 강행하면 캐시에 없는 9건에 대해 OpenRouter로 인증 실패 요청을 실제로 보내게 되어(무의미하고 사용자 지시 위반) 시도하지 않았다.
- 대신 신규 스크립트 `python-inference/scripts/evaluate_llm_cache_only.py`를 작성해 실행 — 기존 `evaluate_llm_sentiment.py`의 검증 로직(`evaluate_llm_records`)을 그대로 재사용하되, `OpenAICompatibleAdapter`의 `opener`를 로컬 스텁으로 교체해 **모든 네트워크 시도를 원천 차단**(캐시 히트는 실제로 스키마 검증까지 수행, 캐시 미스는 `NO_LIVE_CALL_SKIPPED`로 기록하고 시도조차 하지 않음).
- 40건 중 31건이 캐시에 존재(`model/prompt_version/schema_version` 동일 키 기준), 9건은 미시도. 실제 네트워크 호출 0건.

| 지표 | 값 (평가된 31/40건 기준) |
|---|---|
| Overall 정확도 | 0.9355 (29/31) |
| MIXED Precision/Recall/F1 | **1.0 / 1.0 / 1.0** (10/10 캐시 존재, 전부 정답) |
| NEGATIVE Precision/Recall/F1 | 1.0 / 1.0 / 1.0 (9/10 캐시) |
| POSITIVE Precision/Recall/F1 | 0.8 / 1.0 / 0.889 (8/10 캐시) |
| NEUTRAL Precision/Recall/F1 | 1.0 / 0.5 / 0.667 (4/10 캐시) |
| Aspect name F1 (raw / normalized) | 0.095 / 0.615 |

산출물: `evaluation/llm_sentiment_v1_cacheonly_full40_report.json`. 남은 9건(POSITIVE 2, NEGATIVE 1, NEUTRAL 6)은 실제 API 키가 있어야 완성 가능 — 무리한 재시도 없이 여기서 중단.

> **[2026-07-22 갱신] 이 `0.9355(29/31)`는 캐시 선택 정책이 last-write-wins(같은 cache_key에 나중에 쓴 값이 이전 값을 덮어씀)였던 당시의 결과다.** 이후 캐시를 write-once/first-write-wins로 고친 뒤 같은 31/40건 cache-only 평가를 다시 실행하면 `0.9677(30/31)`이 나온다. 모델·프롬프트·평가 데이터셋은 변경되지 않았으며, 중복 캐시 중 어느 과거 예측 응답을 평가 입력으로 사용하는지가 변경된 결과다 — LLM 성능 개선이 아니다. 상세: 하단 "LLM 캐시 write-once 수정 이후 cache-only 재검증" 섹션.

### 실행한 명령
```bash
python -m pytest python-inference/tests -q
python python-inference/scripts/evaluate_predict_endpoint.py
python python-inference/scripts/evaluate_llm_sentiment.py --dataset evaluation/sentiment_eval_representative_12.jsonl --limit 12 --prompt-version sentiment-aspect-v1 --use-cache --output evaluation/llm_sentiment_v1_reverify_report.json
python python-inference/scripts/evaluate_aspect_taxonomy.py --report evaluation/llm_sentiment_v1_reverify_report.json --dataset evaluation/sentiment_eval_representative_12.jsonl --output evaluation/aspect_taxonomy_reverify_report.json
python python-inference/scripts/evaluate_llm_cache_only.py --dataset evaluation/sentiment_eval_reviews.jsonl --output evaluation/llm_sentiment_v1_cacheonly_full40_report.json --prompt-version sentiment-aspect-v1
```
(2·3단계 모두 `SENTITRACK_LLM_API_KEY`는 캐시 전용 실행에만 필요한 미사용 placeholder 값으로, 실제 네트워크 호출에는 쓰이지 않았음 — 캐시 미스는 전량 로컬에서 스킵 처리됨.)

### 테스트 및 검증 결과
- `python -m pytest python-inference/tests`: 147 passed, 18 warnings (운영 코드 변경 없음 — 이번 단계는 신규 평가 스크립트만 추가).
- 모든 재측정에서 실제 OpenRouter API 호출은 0건.

### 수치 구분: 오프라인 실험값 vs 실제 프로덕션(`/predict`) 최종값

같은 "MIXED Recall 0.30" 같은 숫자가 이 로그 안에서 오프라인 실험 단계와 실제 운영 반영 단계 양쪽에 등장해 혼동될 수 있어, 어느 수치가 "실험실에서만 확인된 값"이고 어느 수치가 "실제 배포된 코드로 재현되는 값"인지 아래에 명시적으로 구분한다.

| 구분 | 수치 산출 방식 | MIXED Recall | 상태 |
|---|---|---|---|
| 오프라인 실험 — RAW (절 분리만, 정규화 없음) | `evaluate_clause_normalization.py`, offline 스크립트 | 0.20 | 실험값 (운영 미반영 상태에서 측정) |
| 오프라인 실험 — SIMPLE_DECLARATIVE (절 텍스트 정규화 적용) | 〃 | 0.30 | 실험값 (offline, 이 시점엔 `/predict`에 미배선) |
| 프로덕션 `/predict` — clause split만 배선 (커밋 `f4e0a09`) | `evaluate_predict_endpoint.py`, 실제 엔드포인트 호출 | 0.20 | **최종 프로덕션값 (오전, 정규화 배선 전)** |
| 프로덕션 `/predict` — clause split + normalization 배선 (커밋 `8b5e869`) | 〃 | 0.30 | **최종 프로덕션값 (오후, 현재 배포 상태)** |

LLM 쪽은 `0.9032`(aspect 정규화 F1)와 `0.9355`(overall 정확도)가 같은 대상을 가리키는 두 버전의 수치처럼 보일 수 있으나, **지표·데이터셋·평가 방식이 모두 다른 별개의 두 측정치**다.

| 항목 | `0.9032` | `0.9355` |
|---|---|---|
| 지표 이름 | Aspect(속성) **이름** 정규화 F1 — 예측된 aspect 이름을 canonical taxonomy로 정규화한 뒤 gold aspect 이름과 비교 | **Overall 정확도** — POSITIVE/NEGATIVE/MIXED/NEUTRAL 4-class 라벨 exact match |
| 평가 대상 | `sentiment_eval_representative_12.jsonl` (대표 12건) | `sentiment_eval_reviews.jsonl` 40건 중 캐시에 있던 31건 |
| 평가 방식 | 실시간 API 평가 (실제 OpenRouter 호출 1회, 단일 세션) | 캐시 평가 (네트워크 호출 0건, `evaluate_llm_cache_only.py`) |
| 근거 문서/커밋 | "LLM Aspect taxonomy normalization offline 검증" 단계, `aspect_taxonomy_report.json` (커밋 이전 offline 실험, git 히스토리상 `12bf6fd`에 포함) | "목표 3 최종 평가" 3단계, `llm_sentiment_v1_cacheonly_full40_report.json` (커밋 `6bdb4f4`) |
| 재현성 | **재현 안 됨** — 같은 12건을 캐시로 재검증하자 `0.4667`로 하락 (2단계 참고) | 캐시 선택 정책에 의존적이었다 — 아래 참고 |
| 결론 | 단일 세션 실측치로서 역사적 기록 가치만 있음. 포트폴리오 확정 수치로 인용하지 않음 | 31/40건 한정이라는 것을 항상 병기하면 인용 가능. **단, "0.9355"라는 숫자 자체는 아래에서 갱신됨** |

`0.9355`도 자세히 보면 하나의 확정값이 아니라 **캐시 선택 정책에 의존하는 값**이었다는 것이 이후(2026-07-22) 확인됐다.

| 구분 | 수치 산출 방식 | 상태 |
|---|---|---|
| LLM aspect 정규화 F1 0.9032 (대표 12건) | 최초 실제 API 호출 1회, 단일 세션 내 측정 | 실험값 — 단일 세션 실측치, 세션 간 캐시 재사용으로는 재현 불가 확인(재검증 시 0.4667까지 하락). **README에는 사용하지 않음.** |
| LLM overall 정확도 **0.9355 (29/31)** | 캐시에 있는 항목만 네트워크 호출 0건으로 재검증 | **수정 전 — last-write-wins 기준 과거 결과.** 캐시가 같은 cache_key를 나중에 쓴 값으로 덮어쓰는 정책이었을 때 읽힌 값 (2026-07-21). |
| LLM overall 정확도 **0.9677 (30/31)** | 캐시에 있는 항목만 네트워크 호출 0건으로 재검증(동일 31/40건, 동일 모델/프롬프트) | **수정 후 — first-write-wins 기준 재현 가능한 cache-only 결과 (2026-07-22).** 캐시를 write-once로 고친 뒤 같은 데이터셋으로 재실행한 값 — 현재 인용 가능한 최종값. MIXED P/R/F1은 두 버전 모두 1.0/1.0/1.0로 동일했다. 40건 전체 결과가 아니며 외부 API 호출은 0건이다. 상세: 하단 "LLM 캐시 write-once 수정 이후 cache-only 재검증" 섹션.

### 포트폴리오 인용 가능 확정 수치 (요약, 2026-07-21 작성 — 원문 보존)
KoELECTRA 단일 문장 분류는 대조/혼합 리뷰에서 MIXED를 20%만 잡아내지만(정밀도는 100%), clause split을 적용해도 절 텍스트 정규화가 프로덕션에 배선되지 않아 실제 운영 수치는 오프라인 실험 최고치(30%)에 못 미치는 20%에 머문다(POSITIVE/NEGATIVE 정확도는 100% 유지, 회귀 없음). 반면 구조화 출력 LLM(OpenRouter 무료 모델, prompt v1)은 캐시로 실제 검증 가능했던 40건 중 31건에서 MIXED를 100% 정밀도/재현율로 판별했고 전체 라벨 정확도 93.6%를 기록해, 대조 문장 판별에서 KoELECTRA 대비 뚜렷한 우위를 실측으로 확인했다. Aspect 수준 추출은 단일 세션 12건 기준 정규화 F1 0.9032(원본 리포트)까지 검증됐으나, 무료 LLM의 비결정성과 캐시의 last-write-wins 특성으로 세션 간 캐시 재사용만으로는 이 수치를 안정적으로 재현할 수 없다는 한계도 함께 확인됐다.

> **[2026-07-22 갱신]** 위 문단의 "전체 라벨 정확도 93.6%"는 당시 캐시가 last-write-wins였을 때의 값이다. 캐시를 write-once로 고친 뒤 동일 31/40건을 재평가하면 **96.77%(30/31)**가 나온다. 모델·프롬프트·데이터셋 변경이 아니라 캐시 재현성 수정에 따른 평가 기준 변경이며, MIXED Precision/Recall/F1(1.0/1.0/1.0)은 그대로 유지된다. 최신 수치와 산출 과정은 아래 "LLM 캐시 write-once 수정 이후 cache-only 재검증" 섹션을 확정 기준으로 본다.

### 남은 문제
- (기술부채 — 하단 "기술 부채" 섹션 참고) LLM 캐시(`llm_sentiment_cache.jsonl`)가 세션 간 last-write-wins로 덮어써져 aspect 이름 수준 재현성이 낮음 — 회귀 테스트용으로 쓰려면 캐시 항목에 타임스탬프/버전을 남기고 최초 성공 응답을 보존하는 정책이 필요함 (이번 범위에서는 구현하지 않음).
- (기술부채 — 하단 "기술 부채" 섹션 참고) OpenRouter 40건 중 9건은 여전히 미평가 상태 (POSITIVE 2 / NEGATIVE 1 / NEUTRAL 6). 실제 API 키가 확보되면 `--resume --use-cache`로 나머지만 이어서 호출 가능.
- [해결됨] KoELECTRA MIXED Recall을 0.30 수준으로 올리려면 `clause_normalization.py`의 정규화 단계를 `/predict`에 추가로 배선해야 하는데, 이번 작업(새 기능 추가 금지)에서는 하지 않았다 — 별도 작업으로 남겨둠. → 같은 날 후속 작업(커밋 `8b5e869`)에서 배선 완료, MIXED Recall 0.20 → 0.30 확인.

### 다음 작업
- 실제 LLM API 자격 증명을 확보하면 40건 중 나머지 9건을 `--resume --use-cache`로 완료하고, aspect F1은 반드시 단일 연속 세션에서 새로 측정해 캐시 오염 없는 수치로 확정한다. (미해결)
- [해결됨] KoELECTRA MIXED Recall을 0.30으로 끌어올리려면 clause normalization을 `/predict`에 연결할지 여부를 별도 작업으로 결정한다. → 같은 날 후속 작업으로 연결 완료 (아래 참고).
- LLM 캐시 재현성 문제(last-write-wins)를 회귀 테스트 인프라 관점에서 어떻게 다룰지 결정한다 (예: run별 캐시 파일 분리, 캐시 항목 불변화 등). (미해결 — 기술부채로 이동)

### 작업명
clause_normalization을 `/predict`에 연결 — KoELECTRA MIXED Recall 0.20 → 0.30

### 작업 목적
- 앞선 최종 평가에서 확인된 갭(프로덕션 MIXED Recall 0.20 vs 오프라인 실험 최고치 0.30)을 해소한다.
- 새 기능/모델 추가 없이, 이미 오프라인 실험으로 검증된 `clause_normalization.py`(SIMPLE_DECLARATIVE)를 기존 clause split 파이프라인에 배선만 한다.

### 구현
- `experiments/clause_sentiment.py`: `analyze_clause_sentiment()`에 `clause_normalizer: Callable[[str], str] | None = None` 선택적 인자 추가. 절 단위 예측 직전에만 적용하고 baseline(전체 문장) 예측에는 적용하지 않음 — 기본값 `None`이면 기존 동작과 100% 동일. `clauses[i]`에 `normalized_text` 필드 추가(정규화 미적용 시 `None`).
- `main.py`: `experiments/clause_normalization.py`에서 `normalize_clause`, `SIMPLE_DECLARATIVE` import, `_normalize_clause_text()` wrapper 추가, `analyze_clause_sentiment(request.text, _predict_clause, clause_normalizer=_normalize_clause_text)`로 전달.
- `Dockerfile` 변경 없음 (오늘 오전 버그 수정 때 이미 `experiments/` 전체를 이미지에 복사하도록 고쳐둔 상태라 정규화 모듈도 자동 포함됨).
- 새 pip 의존성 없음.

### 테스트
- `tests/test_clause_sentiment.py`: `clause_normalizer`가 절에만 적용되고 baseline에는 적용되지 않는지, 정규화로 절 label이 바뀌어 MIXED가 확정되는지, `clause_normalizer` 미지정 시 `normalized_text`가 `None`으로 기존 동작을 유지하는지 검증하는 테스트 2개 추가.
- `tests/test_main.py`: `main._normalize_clause_text()` wrapper 단위 테스트 1개 추가.
- 전체 재실행: **150 passed** (기존 147 + 신규 3, 회귀 없음).

### 재측정 결과 (실제 `/predict`, 40건, 연결 전/후 비교)
| 지표 | 연결 전 | 연결 후 |
|---|---|---|
| MIXED Recall | 0.20 | **0.30** |
| MIXED Precision | 1.0 | 1.0 |
| POSITIVE/NEGATIVE 정확도 | 1.0 | **1.0** (회귀 없음) |
| False MIXED | 0 | **0** (신규 오탐 없음) |
| 4-class exact match (40건) | 22/40=0.55 | 23/40=0.575 |

MIXED 골드 10건 중 eval-023, eval-024, eval-028이 새로 정확히 MIXED로 판별됐다 (기존 오프라인 SIMPLE_DECLARATIVE 실험의 개선 사례와 정확히 일치). eval-030은 연결 전 MIXED로 맞았다가 연결 후 POSITIVE로 바뀌어 오답이 됐는데, 이는 새로운 문제가 아니라 기존 오프라인 실험에서도 동일하게 나타났던 트레이드오프(순증 +1건, 0.20→0.30과 정확히 부합)다. "인데" 접속 처리를 오늘 오전 추가했음에도 이 40건 데이터셋에는 해당 어미 사례가 없어 이번에도 영향 없음. 산출물: `evaluation/predict_endpoint_full40_report.json`(갱신).

### 남은 문제
- eval-030 같은 개별 트레이드오프 케이스가 존재 — 정규화가 항상 순이익만 주는 것은 아니며, 이번엔 순증이 더 컸을 뿐이다.
- `HANGUL_AWARE_DECLARATIVE`(더 공격적인 정규화 전략)는 이번에 연결하지 않았다 — 오프라인 실험에서 `SIMPLE_DECLARATIVE`와 동일한 성능이었어서 더 단순한 쪽을 선택.
- MIXED confidence_score는 여전히 baseline(원문 전체) 확신도를 그대로 씀 — 이번 변경과 무관하게 기존 제약 유지.

### 다음 작업
- 운영 배포 후 실제 트래픽에서 정규화가 정상 동작하는지 모니터링한다 (MLflow `contrast_detected` 태그로 절 분리 발생 빈도 확인 가능).
- eval-030류 트레이드오프가 실제 서비스에서 체감될 정도인지는 리뷰가 더 쌓인 뒤 재평가한다.

### 작업명
배포 파이프라인 동시 실행 경합 재발 방지 — `deploy.yml`에 `concurrency` 그룹 추가

### 원인
- `6bdb4f4`, `8b5e869`가 6분 간격으로 연달아 push되면서 `deploy.yml`에 동시 실행 제어가 없어 **두 워크플로가 같은 OCI 서버에 SSH 배포를 동시에 실행**함.
- 두 프로세스가 동일한 Docker 이미지를 동시에 pull하며 서버 load average가 9.56까지 상승. 이후 오래된 쪽 워크플로를 취소하자, 진행 중이던 이미지 레이어 추출 작업이 중간에 끊기면서 containerd에 **dangling lease**(정리되지 않은 임시 리소스)가 남았고, 남아있던 다른 pull이 같은 레이어를 기다리며 완전히 멈춤(hang) — CPU 사용률 0%로 25분 이상 무응답.
- (실제로는 별도 조치 없이 얼마 후 자연 해소되어 배포가 정상 완료됐으나, 근본 원인인 "동시 배포 경합"은 남아있어 재발 가능.)

### 조치
- `.github/workflows/deploy.yml` 상단에 `concurrency: { group: deploy-production, cancel-in-progress: false }` 추가.
- `cancel-in-progress: false`로 설정한 이유: 먼저 실행 중인 배포를 강제 취소하면 오늘처럼 중간에 끊긴 작업이 dangling 리소스를 남길 수 있음 — 대신 뒤에 트리거된 워크플로를 **대기열에 넣어 순차 실행**되도록 해서, 애초에 두 배포가 동시에 같은 서버를 건드리는 상황 자체를 막음.

### 검증
- `python -c "import yaml; yaml.safe_load(...)"`로 YAML 문법 파싱 확인, `concurrency` 블록 정상 인식.
- 실제 배포는 트리거하지 않고 diff만 검토 후 반영.

## 260722

### 작업명
LLM 캐시 write-once 수정 이후 cache-only 재검증

### 작업 목적
- 260721 후속 작업("LLM 캐시 재현성 문제 진단·수정")에서 `JsonlLLMCache`를 last-write-wins에서 write-once/first-write-wins로 고친 뒤, 실제 로컬 캐시(`python-inference/evaluation/llm_sentiment_cache.jsonl`)로 재현성과 실제 conflict 분포를 검증한다.
- 특정 성능 수치를 올리려는 목적이 아니다 — 캐시 정책 변경이 기존에 기록된 `0.9355(29/31)`에 실제로 어떤 영향을 주는지 정직하게 확인하고 기록한다.

### 검증 방법
- 기존 로컬 캐시 파일을 수정/덮어쓰지 않고 읽기 전용으로 사용. 실행 전/후 SHA256 동일함을 확인: `cdd5e72de33e04516e20991142d4507ff2f711d9177f3b3c6ff69f6489cb1439`.
- `python-inference/scripts/evaluate_llm_cache_only.py`(모든 네트워크 시도를 차단하는 stub opener 사용, 캐시 미스는 `NO_LIVE_CALL_SKIPPED`로만 기록)를 결과물 경로만 다르게 하여 **동일 설정으로 2회씩** 실행.

### 결과 1 — 기본 설정(prompt_version=`sentiment-aspect-v2-taxonomy`, 스크립트 기본값)
- 40건 중 캐시 존재 12건, `actual_api_call_count`: 0 / 0 (2회 모두), `exact_match_accuracy`: 0.9167 / 0.9167.
- 2회 실행 리포트 파일이 **바이트 단위로 완전히 동일**(SHA256 `ca8030748e50c76ef07c490d6c7b33cf3a94141e72dfecdb586d66dc2d06bf85`, 양쪽 동일) — selected id 순서(`eval-001`~`eval-040`), predictions, normalized_aspects, metric 입출력 모두 포함.

### 결과 2 — `--prompt-version sentiment-aspect-v1` (기존 `0.9355` 기록과 동일 조건)
- 40건 중 캐시 존재 **31건** (기존 기록과 동일 — 남은 9건은 여전히 미평가, POSITIVE 2/NEGATIVE 1/NEUTRAL 6), `actual_api_call_count`: 0 / 0 (2회 모두).
- `exact_match_accuracy`: **0.967741935483871 (30/31)** / 동일 — 2회 실행이 완전히 일치(SHA256 `944f452d75b8e233e2b7784b7ddebd1be8b773596c3658321c191bb4f7c3043a`, 양쪽 동일).
- 리포트 metadata에 timestamp/created_at 등 비결정적 필드가 없어(키 목록 직접 확인) 전체 파일 SHA256 자체가 곧 "비결정적 메타데이터 제외 결과 hash"다.

### 실제 conflict 집계 (로컬 캐시 파일 전체 기준, 두 설정 모두 동일 — conflict 판정은 특정 실행이 아니라 캐시 파일 자체의 속성)
| 항목 | 값 |
|---|---|
| `cache_duplicate_count` (EXACT_DUPLICATE) | 8 |
| `cache_response_conflict_count` (RESPONSE_CONFLICT) | 16 |
| `cache_key_collision_count` (KEY_COLLISION) | **0** |
| `cache_conflict_count` (response_conflict + key_collision) | 16 |

- `KEY_COLLISION`이 0건인 것은 실제 관찰값이다 — SHA256 해시 충돌이 이론상 사실상 불가능하다는 점과 부합한다.
- `cache_conflicts`에 남긴 항목은 `cache_key`, `input_hash`, `line_number`, `conflict_type`뿐이며 리뷰 원문이나 LLM 응답 텍스트는 포함하지 않는다(직접 확인).

### `0.9355(29/31)` → `0.9677(30/31)`의 정확한 의미
- **모델 성능 개선이 아니다.** KoELECTRA/`​/predict`는 이번 작업에서 전혀 건드리지 않았고, LLM 쪽도 모델·프롬프트(`sentiment-aspect-v1`)·평가 데이터셋(`sentiment_eval_reviews.jsonl` 40건 중 동일한 31건)이 전부 동일하다.
- 모델·프롬프트·평가 데이터셋은 변경되지 않았으며, **중복 캐시 중 어느 과거 예측 응답을 평가 입력으로 사용하는지가 변경된 결과다**. 수정 전(last-write-wins)에는 파일의 마지막 줄(세션 간 재호출로 드리프트된 응답일 수 있음)을 읽었고, 수정 후(first-write-wins)에는 항상 최초 응답을 읽는다.
- 이번 로컬 캐시에는 16건의 RESPONSE_CONFLICT(같은 입력에 대해 서로 다른 응답이 기록된 사례)가 실제로 존재했고, 그중 31건 서브셋에 걸린 것들이 이번 정확도 변화(29/31 → 30/31, 1건 차이)의 직접 원인이다.
- MIXED Precision/Recall/F1은 두 설정 모두 `1.0/1.0/1.0`으로 변하지 않았다 — 변화는 overall 4-class 정확도의 특정 1건에 한정된다.
- 여전히 **31/40건 cache-only 부분 평가**이며 40건 전체 실시간 평가가 아니고, 이번 재검증에서도 실제 외부 API 호출은 **0건**이었다.

### 남은 한계
- 과거 schema로 기록된 캐시 항목처럼 `cache_key_parts`(input hash)가 없는 레코드가 있으면 `KEY_COLLISION` 판정이 불가능해 의미 있는 payload 비교로만 fallback한다 — 이번 로컬 캐시의 모든 conflict 항목에는 `input_hash`가 존재해 해당 fallback 경로가 실제로 발생하지는 않았지만, 코드 경로 자체는 남아있다.
- 캐시에 없는 9건은 이번에도 API 키가 없어 평가하지 못했다(변화 없음).
- 이미 드리프트된 캐시 파일의 과거(마지막에 쓰인) 값 자체를 삭제/정리하지는 않았다 — write-once 정책은 "앞으로" 새로운 드리프트가 쌓이는 것만 막는다.

### 다음 작업
- README/로그에 인용된 LLM 수치는 이제 `0.9677(30/31)`을 기준으로 삼는다.
- 실제 API 키가 확보되면 남은 9건을 마무리하고, 이번에 관찰된 16건의 RESPONSE_CONFLICT 각각이 실제로 어떤 두 응답 사이의 차이였는지(예: aspect 이름/문구 차이 vs overall_label 자체가 다른 심각한 드리프트)는 별도로 분류해 볼 가치가 있다.

## 기술 부채 (미해결 사항 누적)

이 로그 전체에 날짜별로 흩어져 있는 미해결 항목을 한 곳에 모아 추적한다. 항목이 해결되면 해결 날짜와 커밋을 남기고 상태를 "해결됨"으로 바꾸되, 항목 자체는 삭제하지 않는다.

### 1. LLM 캐시 재현성 (last-write-wins)
- 상태: **[해결됨 — 코드 레벨, 실제 로컬 캐시로 재현성 검증 완료]** (260721 후속 작업 "LLM 캐시 재현성 문제 진단·수정" → 260722 "LLM 캐시 write-once 수정 이후 cache-only 재검증")
- 문제: `python-inference/experiments/llm_sentiment_client.py`의 `JsonlLLMCache`는 append-only JSONL을 순서대로 읽어 같은 cache_key를 나중에 쓴 값이 이전 값을 덮어쓴다. 세션 간 같은 텍스트가 비결정적으로 재호출되면 과거 캐시가 조용히 교체된다.
- 발견: 260721, "목표 3 최종 평가" 2단계. overall 정확도는 1.0→0.9167로 소폭 하락했지만, aspect 이름 정규화 F1은 0.9032→0.4667까지 크게 하락하는 것을 확인.
- 수정 내용: `JsonlLLMCache.set()`을 기본 write-once로 변경, `_ensure_loaded()`가 중복 키를 마지막 줄이 아니라 **첫 번째 줄**로 항상 고정. 중복은 `EXACT_DUPLICATE`(같은 input hash + 같은 의미 payload) / `RESPONSE_CONFLICT`(같은 input hash, 다른 payload) / `KEY_COLLISION`(input hash 자체가 다름)으로 분류해 리포트 metadata에 `cache_duplicate_count`/`cache_response_conflict_count`/`cache_key_collision_count`/`cache_conflict_count`/`cache_conflicts`로 노출(리뷰 원문·raw_text 없이 `cache_key`/`input_hash`/`line_number`/`conflict_type`만). `analyze_with_cache()`의 `refresh_cache=True`는 "이번 실행은 항상 라이브 호출"이라는 의미만 유지, 캐시 쓰기는 여전히 write-once. 테스트 10개 추가(150 → 160 passed).
- **실제 로컬 캐시(`llm_sentiment_cache.jsonl`, gitignore 대상)로 검증한 결과** (2026-07-22): `cache_duplicate_count=8`, `cache_response_conflict_count=16`, `cache_key_collision_count=0`, `cache_conflict_count=16`. 동일 cache-only 평가를 캐시 파일을 수정하지 않고 2회 실행한 결과가 **바이트 단위로 완전히 동일**했고(`actual_api_call_count=0` 양쪽 모두), 이 수정으로 인해 31/40건 cache-only 서브셋의 overall 정확도가 `0.9355(29/31, 수정 전 last-write-wins 기준)` → `0.9677(30/31, 수정 후 first-write-wins 기준)`으로 바뀌었다. **모델·프롬프트·평가 데이터셋은 변경되지 않았으며, 중복 캐시 중 어느 과거 예측 응답을 평가 입력으로 사용하는지가 변경된 결과다.** 상세: "260722 — LLM 캐시 write-once 수정 이후 cache-only 재검증" 섹션.
- 남은 제약: (1) 과거 schema로 기록되어 `cache_key_parts`(input hash)가 없는 레코드가 있으면 `KEY_COLLISION` 판정이 불가능해 의미 있는 payload 비교로만 fallback한다 — 이번 로컬 캐시에는 해당 사례가 없어 이 fallback 경로가 실제로 실행되지는 않았다. (2) 이미 드리프트된 캐시 파일의 과거(마지막에 쓰인) 값 자체를 자동으로 정리/복구하지는 않는다 — write-once 정책은 앞으로의 신규 드리프트만 막는다.

### 2. DB 계정 정합성 (root/app 비밀번호 불일치)
- 상태: **미해결**
- 문제: 운영 DB(OCI)의 MySQL root 비밀번호가 `.env`의 `DB_PASSWORD`와 일치하지 않는다. `MYSQL_ROOT_PASSWORD`가 볼륨 최초 생성 시에만 적용되는데, 이후 시크릿이 로테이션되며 어긋났다.
- 발견: 2026-06-30 전후 마이그레이션 상태 점검 중.
- 영향: 앱 계정(`sentitrack_user`)은 `sentitrack` 스키마에 `ALL PRIVILEGES`를 보유해 마이그레이션 실행에는 지장 없음 — 배포 파이프라인은 이미 앱 계정으로 우회 설정됨(커밋 `f94254d`). 다만 root 계정이 필요한 수동 운영 작업은 별도로 비밀번호를 확인해야 한다.
- 필요한 조치: `MYSQL_ROOT_PASSWORD`와 앱용 비밀번호를 별도 secret으로 분리 (`DEPLOYMENT_FIXES.md`의 "MySQL root password와 앱 유저 password가 같은 `${DB_PASSWORD}`" 항목과 동일 이슈 — 그쪽 체크리스트에서 함께 추적).

### 3. OpenRouter 40건 중 9건 미평가
- 상태: **미해결**
- 문제: 이 환경에 `SENTITRACK_LLM_API_KEY`/`SENTITRACK_LLM_MODEL`/`SENTITRACK_LLM_BASE_URL`이 설정되어 있지 않아, 캐시에 없는 9건(POSITIVE 2 / NEGATIVE 1 / NEUTRAL 6)을 평가하지 못했다.
- 필요한 조치: 실제 API 키 확보 후 `--resume --use-cache`로 나머지 9건 이어서 호출.

### 4. 기존 운영 리뷰 재채점 미실시
- 상태: **미해결**
- 문제: 오분류 버그 수정(커밋 `f4e0a09`) 이전에 저장된 운영 리뷰(id=2)는 재분석하지 않아 여전히 `POSITIVE`로 남아있다. 신규 리뷰부터만 MIXED가 정확히 기록된다.
- 필요한 조치: 배치 재채점 스크립트 설계 및 실행 여부 결정.
