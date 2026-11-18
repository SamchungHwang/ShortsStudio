# ASS — Autonomous Shorts Studio

『Gemini Omni로 구축하는 자율 Shorts 스튜디오』에서 22장에 걸쳐 만드는 시스템이다.

> ASS는 소재 요약 하나를 받아, 예산과 표현 규칙의 울타리 안에서 45초 Shorts 한 편과 그 근거 기록을 내놓고,
> 매주 무엇을 어떤 형식으로 만들지를 스스로 계획해 사람의 승인을 받는다.

- 만드는 것: 제품 설명, 제품 비교, 정보 전달 세 형식의 Shorts (15초 × 3 장면)
- 러닝 예제: 가상의 스킨케어 브랜드 모아랩. 내 제품으로 바꾸는 방법은 `examples/moalab_skincare/series_bible.md`
- 기술 기준일: 2026-11-17. 모델 사양과 가격은 `configs/models.yaml` 에 확인 상태와 함께 적는다
- 시스템 정의서와 원고: `C:\Book2\자율Shorts스튜디오` (`ASS_시스템_정의서.docx`)
- 기존 원고 코드: `C:\AI\autonomous-content-studio` (패키지 `acs`. 3~5부의 원천, `docs/chapter_map.md` 참고)

## 구성

```
            ┌──────────── 가드: 비용 · 표현 · 사실 근거 · 사람 승인 ────────────┐
 5부  학습   │ 성과 → 정책 패치 제안, 주간 리뷰                                   │
 4부  배포   │ 발행 계획, 언어별 버전                                             │
 3부  판단   │ 주간 계획(소재 × 형식 × 편수), 판단 로그                            │
 3부  인지   │ 트렌드, 성과, 본인 소재 목록                                       │
 1·2부 제작  │ 소재 → 대본 → 장면 사양 → 생성 → 채점 → 편집 → 오디오 → 조립 → 업로드 │
            └──────────────────────────────────────────────────────────────────┘
```

## 시작하기 (Windows PowerShell)

```powershell
cd C:\AI\ShortsStudio
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"       # ass 명령이 설치된다
copy .env.example .env        # GEMINI_API_KEY 를 넣는다
pytest                        # API 없이 도는 단위 테스트
ass compile                   # 세 장면을 프롬프트와 내레이션 대본으로 컴파일 (비용 없음)
ass render --dry-run          # 첫 호출의 요청 확인 (비용 없음)
ass render --scene 1          # 15초 한 장면 생성 (720p 기준 추정 $1.05)
```

설치하지 않고 실행하려면 `python -m ass compile` 또는 `python scripts\compile_scenes.py` 를 쓴다.

## 명령

부를 마칠 때마다 명령이 늘어난다. 3부에서 이 명령들이 에이전트의 도구가 된다.

| 명령 | 하는 일 | 장 | 상태 |
|---|---|---|---|
| `ass compile` | 장면 사양 → 프롬프트·내레이션 대본. 형식·길이·가드 검사 | 6 | 있음 |
| `ass render` | 장면을 Omni로 생성하고 실행 기록을 남김 | 2·4 | 있음 (실제 호출은 아직 안 해 봄) |
| `ass assemble` | 장면을 이어 붙이고 자막과 오디오를 얹음 | 4·12 | 없음 |
| `ass brief` | 아이디어, 블로그 글, 영상 대본을 소재 요약으로 정리 | 6 | 스키마만 있음 |
| `ass script` | 소재 요약에서 대본과 장면 사양 초안을 만듦 | 6 | 없음 |
| `ass sheet` | 제품 사진에서 레퍼런스 시트를 만듦 | 5 | 없음 |
| `ass score` | 초안을 채점하고 통과·편집·사람 검토를 판정 | 8 | 없음 |
| `ass edit` | 대화형 편집과 재초안 폴백 | 9 | 없음 |
| `ass voice`, `ass music` | 내레이션(TTS)과 BGM(Lyria) 생성 | 11 | 없음 |
| `ass publish` | 발행 기록을 만들고 승인 뒤 업로드 | 12·17 | 없음 |
| `ass sense` | 센서를 돌려 studio_memory 를 갱신 | 13 | 없음 |
| `ass plan` | 주간 제작 계획을 제안 | 15 | 없음 |
| `ass log` | 판단 로그를 조회 | 16 | 없음 |
| `ass localize` | 언어별 내레이션·자막 버전을 만듦 | 18 | 없음 |
| `ass learn` | 성과를 분석해 정책 패치를 제안 | 20 | 없음 |
| `ass approve` | 승인 대기 목록을 보고 승인·반려 | 9·21 | 없음 |
| `ass review` | 주간 리뷰 보고서와 대시보드 | 22 | 없음 |

없는 명령은 `ass --help` 에 나오지 않는다. 빈 골격을 미리 두지 않고 해당 장에서 추가한다.

## 저장소

| 경로 | 내용 | 장 |
|---|---|---|
| `ass/cli.py` | `ass` 명령 진입점 | 2·6 |
| `ass/production/source_brief.py` | 소재 입력 형식(아이디어, 본인 블로그, 본인 영상 대본) | 6.2절 |
| `ass/production/product_bible.py` | 제품 외형과 말해도 되는 사실 | 5.1절 |
| `ass/production/scene_spec.py` | 장면 사양 스키마(화면, 내레이션, 자막, 근거) | 6.3절 |
| `ass/production/scene_compiler.py` | 장면 사양 → 영어 프롬프트 + 내레이션 대본 | 6.4절 |
| `ass/production/claims_guard.py` | 제품 표현 가드 | 6.5절 |
| `ass/production/omni_client.py` | Interactions API 호출(생성·편집) | 2·9장 |
| `ass/production/run_record.py` | api_run.json 실행 기록 | 2.5절 |
| `ass/guards/cost_guard.py` | 추정 비용과 예산 가드 | 4·8장 |
| `ass/policy/policy_loader.py` | 정책 로더와 policy_hash | 14장 |
| `configs/models.yaml` | 기술 스택, 사양, 단가, 확인 상태 | 1·2장, 부록 A |
| `configs/production_spec.yaml` | 세 형식의 장면 뼈대, 길이, 내레이션 모드, 자막 길이 | 3·6장 |
| `configs/claims_lexicon.yaml` | 제품 표현 가드 사전(한·영). 초기 가정값 | 6.5절 |
| `configs/budget_policy.yaml` | 실행·편당 예산 상한 | 4.3·8.5절 |
| `examples/moalab_skincare/` | series_bible, product_bible, source_brief, 제품 설명 편 장면 사양 3개 | 3·5·6장 |
| `experiments/` | 선행 검증 실험 목록과 기록 | 부록 A |
| `docs/chapter_map.md` | 장 ↔ 코드 ↔ 기존 원고 대응표 | 부록 D |
| `outputs/` | `compiled/`(컴파일 결과), `renders/`(영상과 실행 기록) | — |

## 부별 완성 기준

| 부 | 되어야 하는 것 |
|---|---|
| 1부 | 명령 두세 개로 제품 설명 편 세 장면을 생성해 45초 초안 하나로 이어 붙인다. 실행 기록과 비용 장부가 남는다 |
| 2부 | 소재 요약에서 세 형식의 발행 가능한 완성본이 나온다. 타사 제품 장면은 승인 없이는 생성되지 않는다. 승인 뒤 비공개 업로드 |
| 3부 | `ass plan` 이 한 주의 제작 계획을 예산 안에서 제안하고, 판단의 이유와 policy_hash 가 남는다 |
| 4부 | 발행 계획이 나오고, 한국어 외 한 개 언어 버전이 같은 마스터에서 만들어진다 |
| 5부 | 성과에서 정책 패치 제안이 나온다. 강화는 자동, 완화는 승인 대기. 주간 리뷰 보고서가 생성된다 |

지금은 1부 기준의 절반까지 왔다. 다음 일은 첫 실제 호출(실험 E00)과 `ass assemble` 이다.

## 지금 상태

- 실행해 확인한 것: 단위 테스트 42개, `ass compile`, `ass render --dry-run`.
- 아직 실행하지 않은 것: 실제 API 호출. `omni_client.py` 는 공식 문서의 호출 형태를 따랐지만
  `duration` 문자열 형식과 텍스트 입력 항목의 키는 실험 E00에서 확정해야 한다.
- 내레이션 모드는 `tts` 로 가정했다. 실험 E13 뒤에 확정한다.
- `claims_lexicon.yaml` 은 초기 가정값이다. 통과했다고 광고 표현이 적법하다는 뜻이 아니다.

## 원칙

- 정책은 코드 밖(`configs/*.yaml`)에 둔다. 어떤 정책으로 실행했는지는 `policy_hash` 로 남긴다.
- 확인되지 않은 단가·사양은 값으로 쓰지 않는다. 단가를 모르는 호출은 비용 가드가 막는다.
- 제품 사실은 `product_bible` 에서만 가져오고, 구간마다 근거를 연결한다.
- 타사 제품이 나오는 장면과 효능·비교 표현은 사람이 승인한다. 영상 공개도 사람이 승인한다.
- 예산 상한, 금지선, 사람 승인 지점 없이 도는 경로를 만들지 않는다.

## 이름에 대하여

패키지와 명령의 이름은 `ass` 다. FFmpeg 자막 형식인 `.ass`(Advanced SubStation Alpha)와 이름이 같으므로,
12장에서 자막 파일을 다룰 때는 “ASS 자막 파일”이 아니라 “.ass 자막 파일”로 구분해 쓴다.
