# SentiTrack

글로벌 쇼핑몰 실시간 리뷰 감성 모니터

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| 프론트엔드 | Next.js (App Router, TypeScript) |
| 게이트웨이 | Node.js (TypeScript, Fastify) |
| 추론 서버 | Python (FastAPI) + HuggingFace + MLflow |
| 인프라 | Docker Compose |

## 디자인 원칙

- `border-radius` 전혀 사용 금지 — 모든 UI 요소는 완전히 각진(Square) 스타일
- 테두리(border) 없이 배경색 대비만으로 구역 구분
- 모던하고 날카로운 미니멀 UI

## 배포 구조

기존 EC2 인스턴스의 `nginx-proxy` + `acme-companion` + `shared-net` 구조 재사용.

- **외부 노출**: Next.js → `sentitrack.levelupseon.com`
- **내부망 전용**: Node.js 게이트웨이, Python 추론 서버 (외부 도메인 없음)

## 코드 스타일

- 주석보다 코드 자체로 이해 가능하게 작성
- 수정 시 완성된 파일을 통째로 제공하는 방식 선호

## CHANGELOG 자동 기록 규칙

코드를 수정하는 작업(파일 생성, 수정, 삭제)을 마칠 때마다, 무엇을 어떤 파일에서 왜 바꿨는지 `CHANGELOG.md`에 오늘 날짜로 자동 기록한다. 같은 날짜 항목이 이미 있으면 그 아래에 이어서 추가한다. 사용자가 별도로 요청하지 않아도 매 작업 종료 시 항상 수행한다.
