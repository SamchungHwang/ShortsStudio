# ASS 공정 지도

`ass map --write` 가 `configs/workflow.yaml`(버전 2026-11-18)에서 만든 파일이다. 손으로 고치지 않는다.

```
소재  →  대본  →  제품 레퍼런스  →  장면 생성  →  오디오  →  조립·업로드
```

| 단계 | 답하는 질문 | 입력 | 출력 | 명령 | 모델 | 가드 | 장 |
|---|---|---|---|---|---|---|---|
| 1. 소재 | 무엇에 대해 말할 것인가 | 아이디어 한 줄, 본인 블로그 글, 본인 영상의 대본 | source_brief | `ass brief` (있음) | Gemini 3.8 Flash | 본인 소유 확인 | 3, 6 |
| 2. 대본 | 15초 세 장면에 무엇을 보여 주고 무엇을 말할 것인가 | source_brief, product_bible | scene_spec, 영어 프롬프트, 내레이션 대본 | `ass script` (있음)<br>`ass compile` (있음) | Gemini 3.8 Flash | 제품 표현 가드, 사실 근거 검사, 형식·길이 정책 | 3, 6 |
| 3. 제품 레퍼런스 | 제품이 장면마다 같은 모습으로 나오게 하려면 | 제품 사진, product_bible | 레퍼런스 시트, reference_manifest | `ass sheet` (있음) | Nano Banana 2.1 | 비용 가드 | 5, 7 |
| 4. 장면 생성 | 초안을 싸게 뽑고, 채점하고, 고쳐 쓴다 | 영어 프롬프트, 레퍼런스 시트 | 장면 영상, api_run, quality_report | `ass render` (있음)<br>`ass score` (없음)<br>`ass edit` (없음) | Gemini Omni Flash 1.2 | 비용 가드, 타사 제품 장면 승인, 편집 횟수 상한 | 2, 4, 7~10 |
| 5. 오디오 | 내레이션과 배경 음악 | 내레이션 대본 | 내레이션 음성, BGM | `ass voice` (없음)<br>`ass music` (없음) | Gemini TTS, Lyria 3.5 | 비용 가드, 음악 출처 통제 | 11 |
| 6. 조립·업로드 | 한 편으로 묶어 내보낸다 | 장면 영상, 내레이션 음성, BGM, 자막 문구 | 완성 영상, 자막 파일, release_manifest | `ass assemble` (있음)<br>`ass approve` (없음)<br>`ass publish` (없음) | — | 사람 승인, AI 공시 판단, 원본성 로그 | 4, 12, 17 |

명령 12개 중 6개가 있다.
