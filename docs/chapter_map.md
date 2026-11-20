# 장 ↔ 코드 ↔ 산출물 대응표

부록 D(기존 원고 코드와 개정판 코드 대응표)의 원천이다. 개정판 패키지는 `ass`, 기존 원고 패키지는 `acs`다. 모듈 이름은 그대로 옮긴다. “상태”가 `있음`인 것만 저장소에 있다.
나머지는 해당 장을 쓸 때 만든다. 빈 골격 파일을 미리 만들지 않는다.

| 장 | 모듈·파일 | 장의 산출물 | 기존 원고(`autonomous-content-studio`) | 상태 |
|---|---|---|---|---|
| 1 | `ass/workflow.py`, `ass/console.py`, `ass/console_model.py`, `ass/cli.py` (`ass map`, `ass stack`, `ass console`), `configs/workflow.yaml`, `configs/models.yaml` | docs/workflow_map.md, README.md | README, 1·2장의 자율화 레벨 | 있음 |
| 2 | `ass/doctor.py` (`ass doctor`), `ass/production/omni_client.py`, `run_record.py`, `ass/cli.py` (`ass render --prompt`), `scripts/ch02_first_call.py` | docs/setup.md, first_render.mp4, first_render.api_run.json | 없음(자리표시자) | 있음(미실행) |
| 3 | `examples/moalab_skincare/`, `configs/production_spec.yaml` 의 formats | series_bible.md, 장면 사양 3개 | `configs/production_spec.yaml` 의 templates | 있음(초안) |
| 4 | `ass/guards/cost_guard.py` | draft_45s.mp4, cost_ledger.csv, error_log.md | `acs/guards/cost_guard.py` | 일부 |
| 5 | `ass/production/product_bible.py` | product_bible.yaml, reference_manifest.json | `production_spec.yaml` 의 subject | 일부 |
| 6 | `ass/production/source_brief.py`, `scene_spec.py`, `scene_compiler.py`, `claims_guard.py` (대본 생성 `script_agent.py` 는 아직 없음) | source_brief, scene_spec.schema.json, scene_compiler.py, tests/ | `acs/production/spec.py`, `script_agent.py`, `veo_prompt_agent.py` | 있음(초안) |
| 7 | (실험 스크립트) | mode_experiment.csv, consistency_report.md | 없음 | 없음 |
| 8 | `ass/production/quality_score.py` | quality_score.py, quality_report.json, promotion_policy.yaml | `acs/production/quality_score.py`, `configs/quality_rubric.yaml` | 없음 |
| 9 | `ass/production/self_correct.py`, `ass/hitl/gate.py` | — | `acs/production/self_correct.py`, `acs/hitl/gate.py` | 없음 |
| 10 | `ass/production/omni_client.py` 확장 | — | 없음 | 없음 |
| 11 | `ass/production/tts_client.py`, Lyria, FFmpeg 믹싱 | — | 없음 | 없음 |
| 12 | `ass/production/edit_agent.py` | release_manifest | `acs/production/edit_agent.py` | 없음 |
| 13 | `ass/sensors/{base_sensor,trend_scout,competitor_watch,performance_sensor}.py`, `ass/memory/studio_memory.py` | — | 같은 이름 | 없음 |
| 14 | `ass/policy/policy_loader.py`, `ass/guards/odd_validator.py`, `ass/tools/` | decision_policy.yaml | `acs/policy/`, `acs/guards/`, `acs/tools/` | 일부(policy_hash) |
| 15 | `ass/planner/{portfolio_planner,explore_exploit}.py` | — | `acs/planner/` (`acs/decision/` 과 중복) | 없음 |
| 16 | `ass/logging/decision_log.py` | decision_log | `acs/logging/decision_log.py` | 없음 |
| 17 | `ass/publish/publish_router.py` | publish_policy.yaml | `acs/publish/` (`acs/distribution/` 과 중복) | 없음 |
| 18 | `ass/localization/{layer_model,localization_agent}.py` | layer_manifest | `acs/localization/` | 없음 |
| 19 | `ass/localization/language_portfolio_agent.py` | language_portfolio.yaml | `acs/localization/`, `acs/portfolio/` 에 중복 | 없음 |
| 20 | `ass/learning/{analytics_agent,policy_patch}.py` | — | `acs/learning/` | 없음 |
| 21 | `ass/guards/risk_tier.py`, `ass/hitl/gate.py` | risk_tier_policy.yaml | `acs/guards/`, `acs/governance/` 에 중복 | 없음 |
| 22 | `ass/ops/{dashboard,weekly_review}.py`, `ass/rollout/roadmap.py` | — | `acs/ops/`, `acs/dashboard/`, `acs/rollout/` | 없음 |

## 정해야 할 것
기존 저장소에는 같은 역할의 모듈이 두 곳에 있는 경우가 있다(`planner`/`decision`, `publish`/`distribution`,
`guards`/`governance`, `ops`/`dashboard`). 위 표는 README의 디렉터리 매핑에 적힌 쪽을 골랐다. 3부를 옮기기 전에 확정한다.
