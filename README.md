# ShortsStudio (`acs`)

『Gemini Omni로 구축하는 자율 Shorts 스튜디오』의 실습 코드 저장소다.
러닝 예제 〈모모의 월요 회의〉 한 편을 끝까지 만들고(1·2부), 그 제작 라인을 울타리 안에서 에이전트가 운영하게 한다(3~5부).

- 기술 기준일: 2026-11-17. 모델 사양과 가격은 `configs/models.yaml` 에 확인 상태와 함께 적는다.
- 원고 폴더: `C:\Book2\자율Shorts스튜디오`
- 기존 원고 코드: `C:\AI\autonomous-content-studio` (3~5부의 원천. `docs/chapter_map.md` 참고)

## 공정

```
대본 → 캐릭터 → 장면 생성 → 오디오 → 조립 → 업로드
        └ 비용 가드 · 동물 윤리 사전 · 실행 기록이 매 단계를 감싼다 ┘
```

## 시작하기 (Windows PowerShell)

```powershell
cd C:\AI\ShortsStudio
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env        # GEMINI_API_KEY 를 넣는다
pytest                        # API 없이 도는 단위 테스트
python scripts\compile_scenes.py          # 세 장면을 영어 프롬프트로 컴파일 (비용 없음)
python scripts\first_render.py --dry-run  # 첫 호출의 요청 확인 (비용 없음)
python scripts\first_render.py            # 15초 한 장면 생성 (720p 기준 추정 $1.05)
```

## 구조

| 경로 | 내용 | 장 |
|---|---|---|
| `configs/models.yaml` | 기술 스택, 사양, 단가, 확인 상태 | 1·2장, 부록 A |
| `configs/production_spec.yaml` | 15초 × 3, 42~48초, 60초 상한, 제외 지시 | 3·6장 |
| `configs/ethics_lexicon.yaml` | 동물 윤리 표현 사전(한·영) | 6.4절 |
| `configs/budget_policy.yaml` | 실행·편당 예산 상한 | 4.3·8.5절 |
| `acs/production/scene_spec.py` | 장면 사양 스키마 | 6.2절 |
| `acs/production/scene_compiler.py` | 장면 사양 → 영어 프롬프트 | 6.3절 |
| `acs/production/omni_client.py` | Interactions API 호출(생성·편집) | 2·9장 |
| `acs/production/run_record.py` | api_run.json 실행 기록 | 2.5절 |
| `acs/guards/cost_guard.py` | 추정 비용과 예산 가드 | 4·8장 |
| `acs/policy/policy_loader.py` | 정책 로더와 policy_hash | 14장 |
| `examples/momo_monday_meeting/` | story_bible, character_bible, 장면 사양 3개 | 3·5장 |
| `experiments/` | 선행 검증 실험 목록과 기록 | 부록 A |
| `docs/chapter_map.md` | 장 ↔ 코드 ↔ 기존 원고 대응표 | 부록 D |

## 지금 상태

- 실행해 확인한 것: 단위 테스트 29개, `compile_scenes.py`, `first_render.py --dry-run`.
- 아직 실행하지 않은 것: 실제 API 호출. `omni_client.py` 는 공식 문서의 호출 형태를 따랐지만
  `duration` 문자열 형식과 텍스트 입력 항목의 키는 실험 E00에서 확정해야 한다.
- 3~5부 모듈은 아직 없다. 빈 골격을 미리 두지 않고 해당 장을 쓸 때 기존 원고 코드에서 옮긴다.

## 원칙

- 정책은 코드 밖(`configs/*.yaml`)에 둔다. 어떤 정책으로 실행했는지는 `policy_hash` 로 남긴다.
- 확인되지 않은 단가·사양은 값으로 쓰지 않는다. 단가를 모르는 호출은 비용 가드가 막는다.
- 예산 상한, 금지선, 사람 승인 지점 없이 도는 경로를 만들지 않는다.
