# SentiTrack Sentiment Label Policy

이 문서는 SentiTrack AI 감정 분석 고도화 평가용 리뷰 데이터셋에 라벨을 붙이기 위한 기준이다. 현재 운영 KoELECTRA 모델이나 API 응답 구조를 변경하지 않는다.

## 목적

- 현재 KoELECTRA baseline 성능을 일관된 기준으로 측정한다.
- `POSITIVE`, `NEGATIVE`, `MIXED`, `NEUTRAL` 라벨의 의미를 명확히 한다.
- 향후 mixed, neutral, 속성별 감정 분석을 설계할 때 비교 가능한 기준선을 남긴다.

## 평가 데이터셋 파일

SentiTrack baseline 평가는 다음 JSONL 파일을 기본 데이터셋으로 사용한다.

```text
python-inference/evaluation/sentiment_eval_reviews.jsonl
```

## 평가 데이터셋 스키마

각 JSONL row는 다음 필드를 반드시 포함한다.

- `id`: 중복 없는 평가 샘플 id
- `text`: 리뷰 본문
- `overall_label`: `POSITIVE`, `NEGATIVE`, `MIXED`, `NEUTRAL` 중 하나
- `aspects`: 분석용 속성 감정 목록
- `category`: 평가 샘플 유형
- `note`: 라벨링 근거 또는 참고 메모
- `review_status`: 모든 seed 데이터는 `PENDING_MANUAL_REVIEW`
- `source`: 모든 seed 데이터는 `SYNTHETIC`

현재 평가 데이터셋은 수작업 검토 전 seed 데이터다. 따라서 baseline report에는 다음 disclaimer를 포함한다.

```text
This dataset is pending manual review and must not be treated as final ground truth.
```

## 라벨 목록

### POSITIVE

리뷰 전체의 주된 평가가 긍정일 때 사용한다.

판정 기준:
- 구매, 사용, 추천, 재구매, 만족, 좋은 향, 좋은 지속력 등 긍정 의도가 핵심이다.
- 사소한 단점이 있더라도 결론이 명확히 긍정이면 `POSITIVE`로 본다.

예:
- `향이 은은하고 오래가서 만족해요.`
- `가격대비 품질이 좋아서 재구매하고 싶어요.`

### NEGATIVE

리뷰 전체의 주된 평가가 부정일 때 사용한다.

판정 기준:
- 불만족, 환불, 비추천, 불쾌한 향, 짧은 지속력, 두통, 실망 등 부정 의도가 핵심이다.
- 사소한 장점이 있더라도 결론이 명확히 부정이면 `NEGATIVE`로 본다.

예:
- `냄새가 독하고 머리가 아파요.`
- `향은 괜찮지만 너무 빨리 사라져서 다시 안 살 것 같아요.`

### MIXED

리뷰 안에 서로 다른 속성 또는 관점에 대한 긍정과 부정이 함께 있고, 둘 중 하나로 단순화하면 의미 손실이 큰 경우 사용한다.

판정 기준:
- 대비 접속사나 병렬 평가가 있고 긍정/부정 근거가 모두 중요하다.
- 향, 지속력, 가격, 배송, 포장, 디자인, 만족도처럼 서로 다른 속성이 상반되게 평가된다.
- 전체 결론이 한쪽으로 명확히 기울면 `POSITIVE` 또는 `NEGATIVE`를 우선한다.

예:
- `향은 너무 좋지만 지속력이 별로예요.`
- `배송은 빨랐지만 포장이 아쉬워요.`
- `가격은 비싸지만 그만큼 만족스러워요.`

### NEUTRAL

리뷰가 명확한 긍정 또는 부정을 표현하지 않고 중립적 관찰, 보통 수준, 정보 전달에 가까울 때 사용한다.

판정 기준:
- `무난하다`, `보통이다`, `아직 모르겠다`, `사용 전이다`처럼 강한 평가가 없다.
- 상품 정보나 사용 상황만 전달하고 평가 감정이 약하다.
- 긍정/부정 단어가 있어도 결론이 평가 보류라면 `NEUTRAL`로 본다.

예:
- `그냥 무난한 향이에요.`
- `아직 한 번만 써봐서 잘 모르겠어요.`

## 속성 라벨

평가 데이터에는 필요할 때 `aspects`를 함께 기록한다. `aspects`는 운영 응답 구조가 아니라 분석용 메타데이터다.

권장 속성:
- `scent`: 향 자체
- `longevity`: 지속력
- `price`: 가격
- `delivery`: 배송
- `packaging`: 포장
- `design`: 병/패키지 디자인
- `usability`: 사용감, 분사, 휴대성
- `overall`: 전반적 만족도

각 속성 감정은 `POSITIVE`, `NEGATIVE`, `NEUTRAL` 중 하나로 기록한다. 한 리뷰의 속성 감정이 상반되면 overall label은 보통 `MIXED` 후보가 된다.

## 평가 시 주의사항

- 현재 KoELECTRA baseline은 `POSITIVE` 또는 `NEGATIVE`만 반환한다.
- `MIXED`와 `NEUTRAL`은 baseline이 출력할 수 없는 expected label이므로 `UNSUPPORTED_EXPECTED_LABEL`로 분리한다.
- `MIXED`와 `NEUTRAL` prediction의 `is_correct`는 `null`로 기록한다.
- `four_class_diagnostic_metrics`는 unsupported expected label까지 포함한 진단용 지표다.
- `binary_supported_metrics`는 gold label이 `POSITIVE` 또는 `NEGATIVE`인 샘플만 사용한 현재 모델 지원 범위 평가다.
- confidence는 모델이 선택한 라벨의 score이며 의미상 정답 확률로 해석하지 않는다.

## 현재 확정된 판단

- 모델 config 기준 `0 -> NEGATIVE`, `1 -> POSITIVE`이며 현재 `normalize_label()`과 일치한다.
- 라벨 매핑 오류는 현재까지 확인되지 않았다.
- 현재 핵심 한계는 서비스와 모델 출력이 단일 binary label에 묶여 있다는 점이다.
