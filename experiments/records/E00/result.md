# E00 호출 형태 확정 — 기록

## 1차 실행 (2026-11-19 10:53 KST)

- 환경: Windows, Anaconda 환경 `ass`, Python 3.13, google-genai (버전 미기록 — `pip show google-genai` 로 확인해 적는다)
- 명령: `python scripts/ch02_first_call.py`
- 요청: `client = genai.Client()` (API 버전 미지정), `client.interactions.create(model="gemini-omni-1.2-flash", input=..., response_format={"type": "video", "aspect_ratio": "9:16", "resolution": "720p", "duration": "5s"})`
- 결과: **실패**. 영상 없음.

```
google.genai._interactions_errors.NotFoundError: Error code: 404 - {'error': {'message':
"Model 'gemini-omni-1.2-flash' not found. If this model or capability is only available in v1beta,
set the API version to 'v1beta' (see https://ai.google.dev/gemini-api/docs/api-versions). Please verify
the model name against the supported list: https://ai.google.dev/gemini-api/docs/models", 'code': 'not_found'}}
```

### 해석
- 오류 메시지가 직접 v1beta 를 가리킨다.
- 공식 API 버전 문서는 "SDK 의 기본은 v1beta 이고 모든 모델이 v1 과 v1beta 양쪽에 있다"고 적지만, 실제 동작은 달랐다.
- 2차 자료(개발자 글, 다른 프로젝트의 수정 기록)는 google-genai 3.x 의 Interactions 호출이 버전을 정하지 않으면 v1 으로 나가고,
  v1 에는 Omni 모델이 없다고 적는다. 공식 문서로는 확인하지 못했다.
- 공식 모델 목록 페이지에는 2026-11-19 현재 `gemini-omni-1.1-flash` 만 있고 1.2 는 없다. 문서가 늦은 것인지 확인이 필요하다.

### 조치
- 클라이언트를 `genai.Client(http_options={"api_version": "v1beta"})` 로 만든다 (`omni_client.make_client`, `scripts/ch02_first_call.py`).
- `configs/models.yaml` 에 `video.api_version: v1beta` 를 적었다.

### 청구
- 실패한 호출이다. 청구 여부는 AI Studio 사용량 화면에서 확인해 적는다: (미확인)

## 2차 실행 (2026-11-19 11:30 KST)

- 환경: 같은 환경. **google-genai 3.6.1** (list_omni_models.py 가 출력)
- 명령 1: `python scripts/list_omni_models.py` (비용 없음)

```
google-genai 3.6.1
[v1] 모델 29개, omni 1개: models/gemini-omni-flash-preview
[v1beta] 모델 65개, omni 3개: models/gemini-omni-1.1-flash, models/gemini-omni-1.2-flash, models/gemini-omni-flash-preview
```

- 명령 2: `python scripts/ch02_first_call.py` (클라이언트를 v1beta 로 고친 판)
- 결과: **실패**. 영상 없음. 이번에는 모델을 찾았고 결제 단계에서 막혔다.

```
google.genai._interactions_errors.APIStatusError: Error code: 402 - [{'error': {'code': 402, 'message':
'Your prepayment credits are depleted. Please go to AI Studio at https://ai.studio/projects to manage your
project and billing. Learn more at https://ai.google.dev/gemini-api/docs/billing#prepay. ',
'status': 'RESOURCE_EXHAUSTED'}}]
```

### 확인된 것
- 모델 ID `gemini-omni-1.2-flash` 는 있다. v1beta 에만 있다. 1차 실행의 404 는 API 버전 때문이었다.
- v1 에는 `gemini-omni-flash-preview` 만 보인다(공식 모델 페이지는 이 ID 를 종료된 것으로 적는다).
- 공식 모델 목록 페이지에 1.2 가 없는 것은 문서가 늦은 것이다.
- 이 계정은 선불(Prepay) 방식이고 잔액이 0 이다. 선불 크레딧이 없으면 402 가 난다. 공식 결제 문서의 설명과 같다.
- SDK 3.6.1 은 이 402 응답의 본문을 해석하지 못해 예외가 세 겹으로 나온다(본문이 목록 형태로 온다). 마지막 줄의 메시지를 읽으면 된다.

### 아직 모르는 것
- `duration` 설정값이 받아들여지는가. 요청이 결제 검사에서 멈췄으므로 판단할 수 없다.
- 영상의 실제 길이, 걸린 시간, 파일 크기, 실제 청구액.

### 조치
- AI Studio 의 Billing 화면에서 선불 크레딧을 충전한다(공식 문서: 최소 $5). 결제는 계정 주인이 직접 한다.
- `ass render` 가 402 와 404 에 한 줄 조치를 붙여 주도록 고쳤다(`omni_client.explain_error`).

## 3차 실행 — 할 일 (충전 뒤)

1. `python scripts/ch02_first_call.py` — 5초 (추정 $0.35)
2. 성공하면 `ass render --prompt "..." --duration 15 --name first_render` — 15초 (추정 $1.05)

확인할 것: `duration` 이 받아들여지는가, 실제 길이가 5초인가, 걸린 시간과 파일 크기, AI Studio 에 찍힌 실제 청구액.
