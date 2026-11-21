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

## 시작하기 (Windows, Anaconda Prompt)

ASS는 전용 Anaconda 환경 `ass` 안에서 돌린다.

```bat
conda create -n ass python=3.13 -y
conda activate ass
cd C:\AI\ShortsStudio
pip install -e ".[dev]"       :: ass 명령이 설치된다
copy .env.example .env        :: GEMINI_API_KEY 를 넣는다 (2장)
ass doctor                    :: 환경 점검. 빠진 것을 알려 준다
pytest                        :: API 없이 도는 단위 테스트
ass map --write               :: 여섯 단계 공정 지도와 명령의 상태 (비용 없음)
ass stack                     :: 기술 스택과 확인 상태 (비용 없음)
ass console                   :: 콘솔(화면)을 연다. ASS_console.bat 을 두 번 눌러도 된다
ass compile                   :: 세 장면을 프롬프트와 내레이션 대본으로 컴파일 (비용 없음)
ass render --dry-run          :: 첫 호출의 요청 확인 (비용 없음)
ass render --scene 1          :: 15초 한 장면 생성 (720p 기준 추정 $1.05)
```

새 창을 열 때마다 `conda activate ass` 를 먼저 한다. 프롬프트 앞이 `(ass)` 인지 확인한다.
환경을 처음부터 다시 만들려면 `conda remove -n ass --all` 뒤에 위 순서를 반복한다.

## 콘솔

`ass console` 은 여섯 단계를 화면에서 실행하는 창이다. 편과 장면, 단계와 명령을 고르고 [실행]을 누른다.

- 콘솔은 `python -m ass <명령>` 을 대신 실행하고 출력을 보여 줄 뿐이다. 새 기능은 없다.
  콘솔에서 되는 일은 모두 명령줄에서도 되고, 가드와 예산 상한과 실행 기록도 똑같이 적용된다.
- 아직 없는 명령은 고를 수는 있지만 실행되지 않고, 어느 장에서 만드는지 알려 준다.
- “호출하지 않고 요청만 확인”이 기본으로 켜져 있다. 끄고 실행하면 추정 비용을 보여 주고 확인을 받는다.
  추정 비용이 실행 예산을 넘으면 묻지 않고 거절한다.
- 탭: 읽고 쓰는 파일, 프롬프트·내레이션 미리보기, 산출물 목록, 기술 스택, 실행 로그.
- “읽고 쓰는 파일” 탭은 고른 명령이 어떤 파일을 읽고 어디에 쓰는지를 실행 전에 보여 준다. 두 번 누르면 그 파일이 열린다.
- [작업] 메뉴: 환경 점검(`ass doctor`), 조립에 쓸 영상 고르기(`ass assemble --pick`), 비용 장부와 오류 기록 만들기(`ass cost`), 실제 청구액 적기(`ass cost --billed`). 4장의 일은 모두 콘솔에서 할 수 있다.
- 글자 크기: [보기] → 글자 크게/작게/기본 크기, 또는 Ctrl + / Ctrl - / Ctrl 0. 기본은 12이고 고른 크기는 `.ass_console.json`에 남아 다음에도 그대로 열린다.
  실행하면 로그 첫머리에도 읽는 파일 목록이 찍힌다.
- tkinter 가 들어 있는 Python 이 필요하다. `conda create` 로 만든 `ass` 환경에는 들어 있다.
- `ASS_console.bat` 은 `ass` 환경을 켠 다음 콘솔을 실행한다.
- 3부에서 에이전트는 콘솔이 아니라 명령을 부른다. 콘솔은 사람을 위한 것이다.

## 명령

부를 마칠 때마다 명령이 늘어난다. 3부에서 이 명령들이 에이전트의 도구가 된다.

| 명령 | 하는 일 | 장 | 상태 |
|---|---|---|---|
| `ass console` | 콘솔(화면). 아래 명령을 화면에서 실행 | 1 | 있음 (작성 환경에 tkinter 가 없어 실제 창은 아직 확인 못 함) |
| `ass doctor` | 환경 점검(Python, 환경 이름, 패키지, API 키, FFmpeg). `--write` 로 `docs/setup.md` 저장 | 2 | 있음 |
| `ass map` | 여섯 단계 공정 지도와 명령의 상태. `--write` 로 `docs/workflow_map.md` 저장 | 1 | 있음 |
| `ass stack` | 기술 스택을 확인된 것과 확인되지 않은 것으로 나눠 표시 | 1 | 있음 |
| `ass compile` | 장면 사양 → 프롬프트·내레이션 대본·장면 설계표(storyboard.md). 형식·길이·가드 검사와 문법 주의 | 3·6 | 있음 |
| `ass render` | 장면을 Omni로 생성하고 실행 기록을 남김. `--prompt` 로 장면 사양 없이도 생성. `--duration`, `--resolution`, `--aspect`, `--delivery`, `--name` | 2·4 | 있음 (실제 호출은 아직 안 해 봄) |
| `ass assemble` | 장면 영상을 이어 붙여 초안 한 편(`draft_45s.mp4`)과 자막 파일(.srt), 조립 기록을 만듦. 비용 없음. `--pick 장면=RUN_ID`, `--dry-run`. 전환, 자막 입히기, 오디오는 10~12장에서 추가 | 4·12 | 있음 (합성 영상으로 확인. 실제 Omni 결과로는 아직 안 해 봄) |
| `ass cost` | 실행 기록을 모아 비용 장부(`cost_ledger.csv`)와 오류 기록(`error_log.md`)을 만듦. `--billed 금액` 으로 실제 청구액을 적음 | 4 | 있음 |
| `ass brief` | 아이디어, 블로그 글, 영상 대본을 소재 요약으로 정리 | 6 | 스키마만 있음 |
| `ass script` | 소재 요약에서 대본과 장면 사양 초안을 만듦 | 6 | 없음 |
| `ass bible` | 제품 바이블 점검. 외형 서술, 사실의 출처, 써도 되는 표현과 쓰지 않는 표현, 레퍼런스 상태를 봄. 비용 없음 | 5 | 있음 |
| `ass sheet` | 제품 레퍼런스 시트 후보를 만듦(Nano Banana 2.1, 1K 한 장 $0.0336). 본인 사진이 있으면 사진을 보고, 없으면 외형 서술로 기준 방향을 먼저 만듦. `--select v001 --by 이름` 으로 사람이 고른 후보를 `reference_manifest.json` 에 기록. `--dry-run`, `--views`, `--approved-by` | 5·7 | 있음 (가짜 호출로 확인. 실제 호출은 아직 안 해 봄) |
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
| `ass/cli.py` | `ass` 명령 진입점 | 1·2·6 |
| `ass/workflow.py` | 공정 지도와 기술 스택 표시 | 1.1·1.2절 |
| `ass/doctor.py` | 환경 점검 | 2.3절 |
| `scripts/ch02_first_call.py` | SDK 만으로 하는 첫 호출 | 2.3절 |
| `ass/console.py`, `ass/console_model.py` | 콘솔의 화면과 판단 부분 | 1.2절 |
| `ASS_console.bat` | 콘솔을 여는 바로 가기 (Windows) | 1.2절 |
| `ass/production/source_brief.py` | 소재 입력 형식(아이디어, 본인 블로그, 본인 영상 대본) | 6.2절 |
| `ass/production/product_bible.py` | 제품 외형과 말해도 되는 사실 | 5.1절 |
| `ass/production/scene_spec.py` | 장면 사양 스키마(화면, 내레이션, 자막, 근거) | 6.3절 |
| `ass/production/scene_compiler.py` | 장면 사양 → 영어 프롬프트 + 내레이션 대본 | 6.4절 |
| `ass/production/claims_guard.py` | 제품 표현 가드 | 6.5절 |
| `ass/production/grammar.py` | 유용한 Shorts의 문법 검사, 장면 설계표 | 3.1·3.4절 |
| `ass/production/omni_client.py` | Interactions API 호출(생성·편집) | 2·9장 |
| `ass/production/run_record.py` | api_run.json 실행 기록 | 2.5절 |
| `ass/guards/cost_guard.py` | 추정 비용과 예산 가드 | 4·8장 |
| `ass/policy/policy_loader.py` | 정책 로더와 policy_hash | 14장 |
| `configs/models.yaml` | 기술 스택, 사양, 단가, 확인 상태 | 1·2장, 부록 A |
| `configs/workflow.yaml` | 한 편이 만들어지는 여섯 단계 | 1.2절 |
| `configs/production_spec.yaml` | 세 형식의 장면 뼈대, 길이, 내레이션 모드, 자막 길이 | 3·6장 |
| `configs/claims_lexicon.yaml` | 제품 표현 가드 사전(한·영). 초기 가정값 | 6.5절 |
| `configs/budget_policy.yaml` | 실행·편당 예산 상한 | 4.3·8.5절 |
| `examples/moalab_skincare/` | series_bible, product_bible, source_brief, 제품 설명 편 장면 사양 3개 | 3·5·6장 |
| `experiments/` | 선행 검증 실험 목록과 기록 | 부록 A |
| `docs/workflow_map.md` | `ass map --write` 가 만드는 공정 지도 | 1장 |
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

1부의 명령은 모두 생겼다. 남은 일은 실제 호출이다. 첫 호출(실험 E00)과 세 장면 생성을 마치면 4장의 실측값이 채워진다.

`ass render` 는 한도 초과(429)와 서버 오류(500, 503)를 만나면 기다렸다가 다시 시도한다. 규칙은 `configs/retry_policy.yaml` 에 있고,
다시 시도할 때마다 추정 비용을 실행 예산에서 한 번 더 뺀다. 응답이 끊긴 호출은 다시 시도하지 않는다(청구됐을 수 있다).

## 지금 상태

- 실행해 확인한 것: 단위 테스트 143개, `ass doctor`, `ass map`, `ass stack`, `ass compile`, `ass render --dry-run`,
  합성 영상 세 개로 `ass assemble` (FFmpeg 6.1.1, Linux), 합성 실행 기록으로 `ass cost`.
- 실패한 호출이 청구되는지는 확인하지 못했다(실험 E04). 비용 장부는 성공한 호출과 실패한 시도를 따로 더한다.
- `retry_policy.yaml` 의 횟수와 대기 시간, `assemble_recipe.yaml` 의 인코딩 값은 초기 가정값이다.
- 아직 실행하지 않은 것: 콘솔의 실제 창(가짜 tkinter 로 흐름만 테스트했다), 실제 API 호출. `omni_client.py` 는 공식 문서의 호출 형태를 따랐지만
  길이를 정하는 설정값은 공식 가이드(1.1 기준)에 없다. 2차 자료의 `duration: "15s"` 를 쓰고 있으며 실험 E00에서 확정해야 한다.
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
