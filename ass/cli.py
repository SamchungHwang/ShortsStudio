"""ass — ASS(Autonomous Shorts Studio)의 명령줄 진입점.

지금 있는 명령은 map, stack, compile, render, assemble, cost, bible, sheet 와 화면으로 같은 일을 하는 console 이다. 나머지 명령은 해당 장에서 추가한다
(전체 목록과 상태는 `ass map`, README, 시스템 정의서 6절).

    ass doctor                       # 환경 점검. 첫 호출 전에 빠진 것을 찾는다
    ass console                      # 콘솔(화면). 아래 명령을 화면에서 실행한다
    ass map                          # 여섯 단계 공정 지도와 명령의 상태
    ass stack                        # 기술 스택과 확인 상태
    ass compile                      # 장면 사양 → 프롬프트·내레이션 대본. 비용 없음
    ass render --dry-run             # 첫 호출의 요청 확인. 비용 없음
    ass render --scene 1             # 15초 한 장면 생성
    ass render --prompt "..." --duration 5 --name first_render   # 장면 사양 없이 프롬프트 한 줄로
    ass assemble                     # 세 장면을 이어 붙여 초안 한 편으로. 비용 없음
    ass bible                        # 제품 바이블 점검. 비용 없음
    ass sheet --dry-run              # 레퍼런스 시트 계획. 비용 없음
    ass sheet                        # 레퍼런스 시트 후보 만들기 (Nano Banana)
    ass sheet --select v001 --by 이름   # 사람이 고른 후보를 기록한다
    ass cost                         # 실행 기록을 모아 비용 장부와 오류 기록을 만든다
    ass brief --episode 편 --owner-confirmed    # 원문 → 소재 요약 초안 (글 모델)
    ass script --episode 편                     # 소재 요약 → 장면 사양 초안 (글 모델)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime

from ass import __version__
from ass.guards.cost_guard import BudgetGuard, UnknownPrice, estimate_image_cost, estimate_text_cost, estimate_video_cost
from ass.policy import load_policy
from ass import ledger
from ass.production import (assembler, bible_lint, drafting, image_client, omni_client, reference_sheet, retry, reuse,
                            text_client)
from ass.production.claims_guard import ClaimsGuard
from ass.production.grammar import check_grammar, storyboard_markdown
from ass.production.product_bible import load_product_bible
from ass.production.run_record import RunRecord
from ass.production.scene_compiler import CompileError, compile_scene
from ass.production.scene_spec import check_episode, load_scene
from ass.settings import EXAMPLE_DIR, OUTPUT_DIR, ROOT
from ass.workflow import check_workflow, load_workflow, render_markdown, render_stack, render_text


def _setup() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:  # python-dotenv 없이도 환경 변수로 실행할 수 있다
        pass
    if hasattr(sys.stdout, "reconfigure"):  # Windows 콘솔에서 한글이 깨지지 않게
        sys.stdout.reconfigure(encoding="utf-8")


def _run_budget_usd(budget_policy: dict) -> float:
    override = os.environ.get("ASS_RUN_BUDGET_USD", "").strip()
    return float(override) if override else float(budget_policy["run_budget_usd"])


def _load_episode(episode: str):
    folder = EXAMPLE_DIR / "episodes" / episode
    paths = sorted(folder.glob("scene_*.yaml"))
    if not paths:
        raise SystemExit(f"장면 사양이 없다: {folder}")
    return [load_scene(p) for p in paths]


def cmd_map(args: argparse.Namespace) -> int:
    """여섯 단계 공정 지도를 보여 준다. --write 를 주면 docs/workflow_map.md 를 만든다."""
    workflow = load_workflow()
    models = load_policy("models").data
    problems = check_workflow(workflow, models)
    for problem in problems:
        print(f"[공정 지도] {problem}")
    available = available_commands()
    print(render_text(workflow, available, models))
    if args.write:
        path = ROOT / "docs" / "workflow_map.md"
        path.write_text(render_markdown(workflow, available, models), encoding="utf-8")
        print(f"저장: {path}")
    return 1 if problems else 0


def cmd_stack(args: argparse.Namespace) -> int:
    """기술 스택을 확인된 것과 확인되지 않은 것으로 나눠 보여 준다."""
    print(render_stack(load_policy("models").data), end="")
    return 0


def cmd_console(args: argparse.Namespace) -> int:
    """콘솔(화면)을 연다. 콘솔은 이 파일의 명령들을 대신 실행한다."""
    try:
        from ass import console
    except ImportError as exc:      # tkinter 가 빠진 Python
        print(f"콘솔을 열 수 없다: {exc}\n"
              "tkinter 가 포함된 Python 이 필요하다. 명령줄에서는 ass map, ass compile, ass render 를 그대로 쓸 수 있다.")
        return 5
    return console.main(available_commands())


def cmd_compile(args: argparse.Namespace) -> int:
    """장면 사양을 영어 프롬프트와 내레이션 대본으로 컴파일한다. API를 호출하지 않는다."""
    spec = load_policy("production_spec")
    models = load_policy("models")
    bible = load_product_bible(EXAMPLE_DIR / "product_bible.yaml")
    scenes = _load_episode(args.episode)

    problems = check_episode(scenes, spec.data)
    for problem in problems:
        print(f"[형식·길이 정책] {problem}")
    notes = check_grammar(scenes, spec.data)
    for note in notes:
        print(f"[주의]{note}")

    resolution = spec.data["shot"]["draft_resolution"]
    out_dir = OUTPUT_DIR / "compiled" / args.episode
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0.0
    for scene in scenes:
        compiled = compile_scene(scene, bible, spec.data)
        (out_dir / f"{scene.scene_id}.prompt.txt").write_text(compiled.prompt + "\n", encoding="utf-8")
        (out_dir / f"{scene.scene_id}.compiled.json").write_text(
            json.dumps(compiled.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        try:
            cost = estimate_video_cost(scene.duration_s, resolution, models.data)
            total += cost
            cost_text = f"${cost:.2f}"
        except UnknownPrice:
            cost_text = "단가 미확인"
        print(f"\n=== {scene.scene_id} ({scene.duration_s}초, {resolution}, 추정 {cost_text}) ===")
        print(compiled.prompt)
        if compiled.narration:
            print(f"--- 내레이션 ({compiled.narration_mode}) ---")
            for line in compiled.narration:
                caption = f"  [자막: {line.caption}]" if line.caption else ""
                print(f"[{line.start_s}-{line.end_s}s] {line.text}{caption}")
        if compiled.needs_human_approval:
            print("!! 타사 제품이 나온다. 생성 전에 사람 승인이 필요하다.")

    print(f"\n장면 {len(scenes)}개, 생성 길이 합 {sum(s.duration_s for s in scenes)}초, "
          f"초안 1회 추정 비용 ${total:.2f} ({resolution})")
    title = promise = ""
    brief_path = EXAMPLE_DIR / "source_briefs" / f"{scenes[0].episode_id}.yaml"
    if brief_path.is_file():        # 소재 요약이 있으면 제목과 약속을 설계표 머리에 적는다
        from ass.production.source_brief import load_source_brief

        brief = load_source_brief(brief_path)
        title, promise = brief.title_ko, brief.promise_ko
    (out_dir / "storyboard.md").write_text(
        storyboard_markdown(scenes, spec.data, title=title, promise=promise), encoding="utf-8")
    if notes:
        print(f"문법 주의 {len(notes)}건. 막지는 않는다. 장면 설계표에서 확인한다.")
    print(f"policy_hash  production_spec={spec.policy_hash}  models={models.policy_hash}")
    print(f"저장: {out_dir} (프롬프트, 내레이션 대본, storyboard.md)")
    return 1 if problems else 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """환경을 점검한다. --write 를 주면 docs/setup.md 로 남긴다."""
    from ass import doctor

    checks = doctor.run_checks()
    print(doctor.render_text(checks))
    if args.write:
        path = ROOT / "docs" / "setup.md"
        path.write_text(doctor.render_markdown(checks), encoding="utf-8")
        print(f"저장: {path}")
    return 1 if any(c.status == "fail" for c in checks) else 0


def cmd_render(args: argparse.Namespace) -> int:
    """장면 하나를 Gemini Omni Flash로 생성하고 실행 기록(api_run.json)을 남긴다.

    --prompt 를 주면 장면 사양 없이 프롬프트 한 줄로 생성한다(2장의 첫 호출). 이때도 표현 가드와 비용 가드를 지난다.
    """
    spec = load_policy("production_spec")
    models = load_policy("models")
    budget = load_policy("budget_policy")

    if args.prompt:
        if args.duration is None:
            raise SystemExit("--prompt 로 생성할 때는 --duration 을 함께 준다")
        violations = ClaimsGuard().find(args.prompt, "prompt")
        if violations:
            print("[막힘] 제품 표현 가드 위반: " + ", ".join(f"'{v.term}' [{v.category}]" for v in violations))
            return 4
        prompt, label = args.prompt, "prompt"
        prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        duration, aspect, episode = args.duration, args.aspect or spec.data["shot"]["aspect_ratio"], "adhoc"
    else:
        bible = load_product_bible(EXAMPLE_DIR / "product_bible.yaml")
        scenes = _load_episode(args.episode)
        if not 1 <= args.scene <= len(scenes):
            raise SystemExit(f"--scene 은 1~{len(scenes)} 이어야 한다")
        scene = scenes[args.scene - 1]
        compiled = compile_scene(scene, bible, spec.data)
        if compiled.needs_human_approval:
            print("타사 제품이 나오는 장면이다. 사람 승인 절차(9.4절)를 거친 뒤 생성한다. "
                  "승인 명령이 생기기 전까지는 생성하지 않는다.")
            return 3
        prompt, prompt_sha, label = compiled.prompt, compiled.prompt_sha256, scene.scene_id
        duration, aspect, episode = args.duration or scene.duration_s, args.aspect or scene.aspect_ratio, args.episode

    resolution = args.resolution or spec.data["shot"]["draft_resolution"]
    model_id = models.data["video"]["id"]
    request = omni_client.build_request(
        prompt, model=model_id, duration_s=duration,
        aspect_ratio=aspect, resolution=resolution, delivery=args.delivery,
    )
    cost = estimate_video_cost(duration, resolution, models.data)
    guard = BudgetGuard(_run_budget_usd(budget.data))
    if cost > guard.cap_usd:        # 호출하기 전에, 요청만 확인할 때도 막는다
        guard.charge(cost, f"{label} {duration}초 {resolution}")

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = args.name or f"{label}.{run_id}"
    out_dir = OUTPUT_DIR / "renders" / episode
    record = RunRecord(
        run_id=run_id,
        purpose=f"ass render {episode} {label}",
        episode=episode,
        scene_id=None if args.prompt else label,
        model=model_id,
        request=omni_client.summarize_request(request),
        prompt_sha256=prompt_sha,
        policy_hashes={p.name: p.policy_hash for p in (spec, models, budget)},
        estimated_cost_usd=cost,
    )

    print(f"모델 {model_id} | {duration}초 | {resolution} | {aspect} | 추정 ${cost:.2f} "
          f"(실행 예산 ${guard.cap_usd:.2f})")
    print(prompt)

    record_path = out_dir / f"{stem}.api_run.json"
    if args.dry_run:
        record.status = "dry_run"
        print(f"\n[dry-run] 호출하지 않았다. 기록: {record.save(record_path)}")
        return 0

    if not os.environ.get("GEMINI_API_KEY"):
        print("\nGEMINI_API_KEY 가 없다. .env.example 을 .env 로 복사해 키를 넣는다. ass doctor 로 확인한다.")
        return 2

    retry_policy = load_policy("retry_policy").data
    api_version = models.data["video"].get("api_version", omni_client.DEFAULT_API_VERSION)
    record.notes = f"api_version={api_version}"

    def before_attempt(attempt: int) -> None:   # 시도할 때마다 추정 비용을 예산에서 뺀다
        guard.charge(cost, f"{label} {duration}초 {resolution} ({attempt}번째 시도)")
        record.attempts = attempt

    def on_retry(attempt: int, exc: BaseException, wait: float) -> None:
        print(f"\n{attempt}번째 시도 실패: {type(exc).__name__}: {exc}")
        print(f"{wait:.0f}초 뒤에 다시 시도한다 (남은 실행 예산 ${guard.remaining_usd:.2f})", flush=True)

    try:
        result, record.attempt_errors = retry.call_with_retry(
            lambda: omni_client.generate(request, out_dir / f"{stem}.mp4", api_version=api_version),
            retry_policy, before_attempt=before_attempt, on_retry=on_retry)
    except Exception as exc:  # 실패도 기록으로 남긴다 ('자주 나는 오류' 상자의 재료)
        record.status = "error"
        record.error = f"{type(exc).__name__}: {exc}"
        record.attempt_errors = list(getattr(exc, "attempt_errors", []))
        hint = omni_client.explain_error(exc)
        if hint:
            record.notes = f"{record.notes}; {hint}" if record.notes else hint
        print(f"\n실패: {record.error}")
        if hint:
            print(f"조치: {hint}")
        print(f"기록: {record.save(record_path)}")
        return 1

    record.interaction_id = result.interaction_id
    record.output_path = result.video_path
    record.elapsed_s = result.elapsed_s
    print(f"\n저장: {result.video_path} ({result.bytes_written / 1e6:.1f}MB, {result.elapsed_s}초 소요)")
    print(f"interaction id: {result.interaction_id}  ← 대화형 편집(9장)에 쓴다")
    print(f"기록: {record.save(record_path)}")
    return 0


def cmd_reuse(args: argparse.Namespace) -> int:
    """다른 프로젝트(기본: 견본)에서 같은 프롬프트로 이미 만든 영상을 가져온다. 비용 없음."""
    from ass import settings

    source = args.source
    if source == settings.PROJECT:
        print(f"[막힘] 지금 프로젝트({source})에서 가져올 수는 없다. --from 에 다른 프로젝트나 sample 을 적는다.")
        return 4
    if source != settings.SAMPLE_NAME and source not in settings.list_projects():
        print(f"[막힘] 없는 프로젝트: {source}")
        return 4
    _, source_outputs = settings.project_paths(source)
    spec = load_policy("production_spec")
    models = load_policy("models")
    bible = load_product_bible(EXAMPLE_DIR / "product_bible.yaml")
    scenes = _load_episode(args.episode)
    resolution = spec.data["shot"]["draft_resolution"]
    model_id = models.data["video"]["id"]
    target_dir = OUTPUT_DIR / "renders" / args.episode
    brought, saved = 0, 0.0
    print(f"{source} 에서 같은 프롬프트로 만든 영상을 찾는다 ({source_outputs / 'renders'})")
    for n, scene in enumerate(scenes, 1):
        compiled = compile_scene(scene, bible, spec.data)
        request = omni_client.build_request(compiled.prompt, model=model_id, duration_s=scene.duration_s,
                                            aspect_ratio=scene.aspect_ratio, resolution=resolution)
        cost = estimate_video_cost(scene.duration_s, resolution, models.data)
        label = f"장면 {n} {scene.scene_id}"
        if reuse.already_here(target_dir, scene.scene_id, compiled.prompt_sha256):
            print(f"  {label}: 이 프로젝트에 같은 프롬프트의 영상이 이미 있다. 가져오지 않는다")
            continue
        found = reuse.find_reusable(source_outputs, compiled.prompt_sha256, model_id, request["response_format"])
        if found is None:
            print(f"  {label}: 같은 프롬프트로 만든 영상이 없다. 생성해야 한다 (추정 ${cost:.2f})")
            continue
        if args.dry_run:
            print(f"  {label}: 가져올 수 있다 — 실행 {found.run_id} (다시 만들면 추정 ${cost:.2f})")
        else:
            video = reuse.bring(found, target_dir, scene.scene_id, args.episode, source)
            print(f"  {label}: 가져왔다 — {video}")
        brought += 1
        saved += cost
    verb = "가져올 수 있는" if args.dry_run else "가져온"
    print(f"{verb} 영상 {brought}개 · 다시 만들지 않아 아끼는 추정 비용 ${saved:.2f}")
    if args.dry_run:
        print("[dry-run] 복사하지 않았다.")
    elif brought:
        print("가져온 영상의 실행 기록에는 어디서 왔는지가 적혀 있고 추정 비용은 0 이다. 이어서 조립하면 된다.")
    return 0


def cmd_assemble(args: argparse.Namespace) -> int:
    """장면 영상을 차례로 이어 붙여 초안 한 편을 만든다. API를 호출하지 않는다."""
    spec = load_policy("production_spec")
    recipe = load_policy("assemble_recipe")
    scenes = _load_episode(args.episode)
    picks = dict(p.split("=", 1) for p in args.pick or [])
    render_dir = OUTPUT_DIR / "renders" / args.episode
    out_dir = OUTPUT_DIR / "episodes" / args.episode
    name = args.name or recipe.data["output_name"]

    try:
        clips = []
        for n, scene in enumerate(scenes, 1):
            run_id = picks.get(str(n)) or picks.get(scene.scene_id)
            path, rid = assembler.find_render(render_dir, scene.scene_id, run_id)
            clips.append((path, rid, assembler.probe(path)))
        assembly = assembler.plan(args.episode, scenes, clips, recipe.data, spec.data, out_dir / f"{name}.mp4")
    except assembler.AssembleError as exc:
        print(f"[조립] {exc}")
        return 2

    print(f"{'장면':<22}{'요청':>6}{'실제':>8}{'사용':>8}  {'크기':<10}{'프레임':>7}  소리  실행 기록")
    for c in assembly.clips:
        print(f"{c.scene_id:<22}{c.requested_s:>5g}초{c.info.duration_s:>7.2f}초{c.used_s:>7.2f}초  "
              f"{c.info.width}x{c.info.height:<6}{c.info.fps:>6g}  {'있음' if c.info.has_audio else '없음'}  "
              f"{c.run_id or '없음'}")
    for note in assembly.notes:
        print(f"[주의] {note}")
    for problem in assembly.problems:
        print(f"[형식·길이 정책] {problem}")
    print(f"전체 길이 {assembly.total_s:.2f}초")

    if args.dry_run:
        assembly.command = assembler.build_command(assembly, recipe.data)
        print("\n[dry-run] FFmpeg 를 실행하지 않았다. 실행할 명령:")
        print(" ".join(f'"{part}"' if any(ch in part for ch in " ;[]") else part for part in assembly.command))
        return 1 if assembly.problems else 0
    try:
        assembler.run(assembly, recipe.data)
        result = assembler.probe(out_dir / f"{name}.mp4")
    except assembler.AssembleError as exc:
        print(f"[조립] {exc}")
        return 2

    (out_dir / f"{name}.srt").write_text(assembler.srt_text(scenes, assembly), encoding="utf-8")
    manifest = assembly.model_dump()
    manifest["result"] = result.model_dump()
    manifest["policy_hashes"] = {p.name: p.policy_hash for p in (spec, recipe)}
    manifest["created_at"] = datetime.now().isoformat(timespec="seconds")
    (out_dir / f"{name}.assembly.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n저장: {out_dir / (name + '.mp4')} ({result.duration_s:.2f}초, {result.width}x{result.height}, "
          f"{result.size_bytes / 1e6:.1f}MB)")
    print(f"자막: {out_dir / (name + '.srt')} (영상에 입히지 않았다. 재생기에서 자막 파일로 불러온다)")
    print(f"기록: {out_dir / (name + '.assembly.json')}")
    review_path = out_dir / f"{name}.review.md"
    if review_path.is_file():           # 사람이 적은 것을 덮어쓰지 않는다
        print(f"검토 기록: {review_path} (이미 있다. 그대로 둔다)")
    else:
        review_path.write_text(assembler.review_template(assembly), encoding="utf-8")
        print(f"검토 기록: {review_path} (빈 양식. 초안을 보고 채운다)")
    print(f"policy_hash  production_spec={spec.policy_hash}  assemble_recipe={recipe.policy_hash}")
    return 1 if assembly.problems else 0


def cmd_cost(args: argparse.Namespace) -> int:
    """실행 기록을 모아 비용 장부(cost_ledger.csv)와 오류 기록(error_log.md)을 만든다."""
    rows = ledger.collect(OUTPUT_DIR, args.episode)
    out_dir = OUTPUT_DIR / "ledger"
    if not rows:
        print("실행 기록이 없다. ass render 를 먼저 실행한다.")
        return 0
    print(f"{'실행':<17}{'편':<15}{'장면':<20}{'길이':>5} {'해상도':<6}{'상태':<8}{'시도':>3}{'소요':>8}{'추정':>8}")
    for r in rows:
        length = f"{r.duration_s:g}초" if r.duration_s else "-"
        elapsed = f"{r.elapsed_s:.0f}초" if r.elapsed_s else "-"
        print(f"{r.run_id:<17}{r.episode:<15}{(r.scene_id or '-'):<20}{length:>5} {r.resolution:<6}"
              f"{('reused' if r.reused_from else r.status):<8}{r.calls:>3}{elapsed:>8}{'$' + format(r.charged_estimate_usd, '.2f'):>8}")
    s = ledger.summarize(rows)
    scope = args.episode or "전체"
    print(f"\n[{scope}] 성공 {s.ok_calls}건 추정 ${s.ok_usd:.2f} (영상 {s.ok_seconds:g}초, 처리 시간 {s.elapsed_s:.0f}초)")
    print(f"[{scope}] 실패한 시도 {s.failed_calls}건 추정 ${s.failed_usd:.2f} — 청구 여부는 확인하지 못했다. 결제 화면에서 본다")
    print(f"[{scope}] 요청만 확인 {s.dry_runs}건 $0.00")
    if s.reused:
        print(f"[{scope}] 가져온 영상 {s.reused}건 $0.00 (다시 만들지 않아 아낀 추정 ${s.reused_saved_usd:.2f})")
    print(f"[{scope}] 추정 합계 ${s.ok_usd:.2f} ~ ${s.worst_case_usd:.2f} (실패한 시도가 모두 청구될 때)")
    if s.ok_seconds:
        print(f"[{scope}] 영상 1초를 만드는 데 걸린 시간 {s.elapsed_s / s.ok_seconds:.1f}초")
    everything = ledger.collect(OUTPUT_DIR)      # 화면에는 고른 편만, 파일에는 늘 전체를 쓴다
    print(f"\n장부: {ledger.write_csv(everything, out_dir / 'cost_ledger.csv')} (전체 {len(everything)}건)")
    error_path = out_dir / "error_log.md"
    error_path.write_text(ledger.error_log_markdown(everything), encoding="utf-8")
    print(f"오류 기록: {error_path}")
    if args.billed is not None:
        row = ledger.append_billing_check(out_dir / "billing_checks.csv", scope, s.ok_usd, args.billed, args.note or "")
        print(f"실제 청구액 ${row['billed_usd']:.2f} · 성공 호출 추정 ${row['estimated_usd']:.2f} · "
              f"차이 {row['diff_usd']:+.2f} → {out_dir / 'billing_checks.csv'}")
    else:
        print("실제 청구액은 AI Studio 의 Billing 화면에서 보고 적는다. 콘솔: [작업] → 실제 청구액 적기 · 명령: ass cost --billed 금액")
    return 0


def _print_findings(findings: list, product_id: str | None = None) -> None:
    for f in findings:
        if product_id is None or f.product_id == product_id:
            mark = "[막힘]" if f.level == "error" else "[주의]"
            print(f"  {mark} {f.where}: {f.message}")


def cmd_bible(args: argparse.Namespace) -> int:
    """제품 바이블을 점검한다. 외형 서술, 사실의 출처, 표현, 레퍼런스 상태를 본다. 비용 없음."""
    bible = load_product_bible(EXAMPLE_DIR / "product_bible.yaml")
    rules = load_policy("bible_rules")
    recipe = load_policy("reference_sheet").data
    findings = bible_lint.lint_bible(bible, rules.data, ClaimsGuard())
    products = [bible.get(args.product)] if args.product else list(bible.products.values())
    print(f"제품 바이블 v{bible.version} · 제품 {len(bible.products)}개 · {EXAMPLE_DIR / 'product_bible.yaml'}")
    for product in products:
        own = "자사" if product.is_own else "타사 (이 제품이 나오는 장면은 사람 승인)"
        print(f"\n{product.id} — {product.name_ko} · {own}")
        print(f"  외형: {product.appearance_en}")
        print(f"  사실 {len(product.facts)}개 · 써도 되는 표현 {len(product.say)}개 · 쓰지 않는 표현 {len(product.dont_say)}개")
        manifest = reference_sheet.load_manifest(reference_sheet.manifest_path(product.id, recipe, EXAMPLE_DIR))
        print(f"  레퍼런스: {reference_sheet.manifest_line(manifest)}")
        for problem in reference_sheet.manifest_problems(product, manifest, recipe, EXAMPLE_DIR):
            print(f"  [주의] 레퍼런스: {problem}")
        _print_findings(findings, product.id)
    shown = [f for f in findings if not args.product or f.product_id == args.product]
    errors = sum(f.level == "error" for f in shown)
    print(f"\n막힘 {errors}건 · 주의 {len(shown) - errors}건 · 규칙 bible_rules={rules.policy_hash}")
    print("이 점검은 형식을 본다. 사실이 참인지, 표현이 법에 맞는지는 사람이 확인한다.")
    return 4 if errors else 0


def _dump_yaml(doc: dict, path, header: str) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n" + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")


def _draft_call(kind: str, episode: str, prompt: str, system: str, policy, models, *, dry_run: bool):
    """글 모델을 한 번 부른다. (읽은 JSON 또는 None, 기록, 종료코드)를 돌려준다. 실패와 요청만 확인도 기록으로 남긴다."""
    text_model = models.data["text"]
    request = text_client.build_request(prompt, model=text_model.get("id"), system_instruction=system,
                                        temperature=policy.data.get("temperature"))
    budget = load_policy("budget_policy")
    cost = estimate_text_cost(len(prompt) + len(system), models.data, int(policy.data["output_tokens_ceiling"]))
    guard = BudgetGuard(_run_budget_usd(budget.data))
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = OUTPUT_DIR / "drafts" / episode
    record = RunRecord(
        run_id=run_id, purpose=f"ass {kind} {episode}", episode=episode, scene_id=kind, model=request["model"],
        request={"model": request["model"], "input_chars": len(prompt), "system_chars": len(system),
                 "generation_config": request.get("generation_config", {})},
        prompt_sha256=hashlib.sha256((system + "\n" + prompt).encode("utf-8")).hexdigest(),
        policy_hashes={p.name: p.policy_hash for p in (policy, models, budget)}, estimated_cost_usd=cost,
        notes="추정 비용은 어림 상한이다. 글자 수를 토큰 수로 쳤고 단가는 확인하지 못한 값이다",
    )
    record_path = out_dir / f"{kind}.{run_id}.api_run.json"
    print(f"모델 {request['model']} | 보내는 글 {len(prompt) + len(system)}자 | 어림 상한 ${cost:.4f} "
          f"(실행 예산 ${guard.cap_usd:.2f})")
    print("--- 지시 ---")
    print(system.strip())
    print("--- 보내는 글 ---")
    print(prompt)
    if dry_run:
        record.status = "dry_run"
        print(f"\n[dry-run] 호출하지 않았다. 기록: {record.save(record_path)}")
        return None, record, 0
    if not os.environ.get("GEMINI_API_KEY"):
        print("\nGEMINI_API_KEY 가 없다. .env.example 을 .env 로 복사해 키를 넣는다. ass doctor 로 확인한다.")
        return None, record, 2

    def before_attempt(attempt: int) -> None:
        guard.charge(cost, f"{kind} {episode} ({attempt}번째 시도)")
        record.attempts = attempt

    def on_retry(attempt: int, exc: BaseException, wait: float) -> None:
        print(f"\n{attempt}번째 시도 실패: {type(exc).__name__}: {exc}\n{wait:.0f}초 뒤에 다시 시도한다", flush=True)

    print("\n초안을 만드는 중 …", flush=True)
    try:
        result, record.attempt_errors = retry.call_with_retry(
            lambda: text_client.generate(request), load_policy("retry_policy").data,
            before_attempt=before_attempt, on_retry=on_retry)
    except Exception as exc:
        record.status, record.error = "error", f"{type(exc).__name__}: {exc}"
        record.attempt_errors = list(getattr(exc, "attempt_errors", []))
        record.save(record_path)
        print(f"실패: {record.error}")
        hint = omni_client.explain_error(exc)
        if hint:
            print(f"조치: {hint}")
        return None, record, 1
    record.interaction_id, record.elapsed_s = result.interaction_id, result.elapsed_s
    if result.usage:
        record.notes = f"{record.notes} | usage={json.dumps(result.usage, ensure_ascii=False, default=str)}"
    raw_path = out_dir / f"{kind}.{run_id}.answer.txt"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(result.text, encoding="utf-8")
    record.output_path = str(raw_path)
    try:
        doc = text_client.parse_json(result.text)
    except text_client.DraftParseError as exc:
        record.status, record.error = "error", f"DraftParseError: {exc}"
        record.save(record_path)
        print(f"실패: 모델의 답을 읽지 못했다. {exc}\n받은 글: {raw_path}")
        return None, record, 1
    record.save(record_path)
    print(f"받았다 ({result.elapsed_s:.1f}초). 받은 글: {raw_path}")
    return doc, record, 0


def _print_check(issues: list[str]) -> None:
    if not issues:
        print("확인할 것: 프로그램이 찾은 것은 없다. 그래도 사람이 원문과 견주어 읽는다.")
        return
    print(f"확인할 것 {len(issues)}개:")
    for issue in issues:
        print(f"  ! {issue}")


def cmd_brief(args: argparse.Namespace) -> int:
    """원문(아이디어 한 줄, 본인 블로그 글, 본인 영상의 대본)에서 소재 요약의 초안을 만든다. 저장본은 건드리지 않는다."""
    if not args.owner_confirmed:
        print("[막힘] 내가 쓴 것이거나 쓸 권리가 있는 소재만 보낸다. 확인했으면 --owner-confirmed 를 붙인다. "
              "콘솔에서는 소재 입력의 “내가 쓴 것이거나 쓸 권리가 있는 소재다”에 표시한다.")
        return 2
    spec, policy, models = load_policy("production_spec"), load_policy("draft_policy"), load_policy("models")
    if args.format not in spec.data["formats"]:
        print(f"[막힘] 없는 형식: {args.format}. 있는 것: {', '.join(spec.data['formats'])}")
        return 2
    bible = load_product_bible(EXAMPLE_DIR / "product_bible.yaml")
    product_ids = [p.strip() for p in (args.products or "").split(",") if p.strip()]
    try:
        products = [bible.get(pid) for pid in product_ids]
    except KeyError as exc:
        print(f"[막힘] {exc.args[0]}. 있는 제품: {', '.join(bible.products)}")
        return 2
    source_path = EXAMPLE_DIR / "sources" / f"{args.episode}.txt"
    source_text = args.idea or (source_path.read_text(encoding="utf-8") if source_path.is_file() else "")
    if args.source_type != "idea" and not args.origin:
        print("[막힘] 블로그 글이나 영상의 대본은 출처(--origin)를 적는다.")
        return 2
    try:
        prompt = drafting.brief_prompt(policy.data, source_type=args.source_type, fmt=args.format,
                                       format_spec=spec.data["formats"][args.format], products=products,
                                       source_text=source_text)
    except ValueError as exc:
        print(f"[막힘] {exc}. 원문은 소재 입력의 원문 칸에 적거나 {source_path} 에 둔다.")
        return 2
    draft, record, code = _draft_call("brief", args.episode, prompt, policy.data["brief"]["system"], policy, models,
                                      dry_run=args.dry_run)
    if draft is None:
        return code
    issues = drafting.check_brief(draft, source_text=source_text, source_type=args.source_type, products=products,
                                  quote_min_chars=int(policy.data["quote_min_chars"]))
    doc = drafting.brief_draft_doc(draft, episode=args.episode, source_type=args.source_type, fmt=args.format,
                                   origin=args.origin, product_ids=product_ids, issues=issues,
                                   model=record.model, created_at=record.created_at)
    target = EXAMPLE_DIR / "drafts" / args.episode / "brief.yaml"
    _dump_yaml(doc, target, f"# 소재 요약 초안 — {record.model} 이 만들었다. 사람이 고쳐서 저장해야 쓰인다")
    print(f"\n제목: {doc['title_ko']}\n약속: {doc['promise_ko']}")
    for n, point in enumerate(doc["key_points"], 1):
        print(f"요점 {n}: {point['text_ko']}")
        print(f"    인용: {point.get('quote', '—')} · 근거: {', '.join(point.get('evidence', [])) or '—'}")
    _print_check(issues)
    print(f"초안: {target}\n다음: [입력] → ② 소재 입력 → [초안 불러오기]. 고친 뒤 저장한다.")
    return 0


def cmd_script(args: argparse.Namespace) -> int:
    """저장된 소재 요약에서 장면 사양 셋의 초안을 만든다. 저장본은 건드리지 않는다."""
    from ass.production.source_brief import load_source_brief

    spec, policy, models = load_policy("production_spec"), load_policy("draft_policy"), load_policy("models")
    brief_path = EXAMPLE_DIR / "source_briefs" / f"{args.episode}.yaml"
    if not brief_path.is_file():        # 견본은 편 폴더와 소재 요약의 이름이 다르다. 장면에 적힌 episode_id 로 찾는다
        scenes = sorted((EXAMPLE_DIR / "episodes" / args.episode).glob("scene_*.yaml"))
        if scenes:
            brief_path = EXAMPLE_DIR / "source_briefs" / f"{load_scene(scenes[0]).episode_id}.yaml"
    if not brief_path.is_file():
        print(f"[막힘] 소재 요약이 없다: {brief_path}. 먼저 소재 입력을 저장한다.")
        return 2
    try:
        brief = load_source_brief(brief_path)
    except Exception as exc:
        print(f"[막힘] 소재 요약을 읽지 못했다: {exc}")
        return 2
    bible = load_product_bible(EXAMPLE_DIR / "product_bible.yaml")
    try:
        products = [bible.get(pid) for pid in brief.products]
    except KeyError as exc:
        print(f"[막힘] {exc.args[0]}")
        return 2
    format_spec = spec.data["formats"][brief.format]
    prompt = drafting.script_prompt(policy.data, brief=brief.model_dump(), format_spec=format_spec,
                                    production_spec=spec.data, products=products)
    draft, record, code = _draft_call("script", args.episode, prompt, policy.data["script"]["system"], policy, models,
                                      dry_run=args.dry_run)
    if draft is None:
        return code
    try:
        docs = drafting.scene_docs(draft, episode=args.episode, fmt=brief.format, format_spec=format_spec,
                                   product_ids=list(brief.products))
    except ValueError as exc:
        print(f"실패: {exc}")
        return 1
    issues = drafting.check_scenes(docs, products=products, production_spec=spec.data)
    folder = EXAMPLE_DIR / "drafts" / args.episode
    for n, doc in enumerate(docs, 1):
        _dump_yaml(doc, folder / f"scene_{n:02d}.yaml", f"# 장면 {n} 초안 — {record.model} 이 만들었다. 사람이 고쳐서 저장해야 쓰인다")
        print(f"\n=== 장면 {n} · {doc['role']} ===")
        for beat in doc["beats"]:
            print(f"[{beat.get('start_s')}-{beat.get('end_s')}s] {beat.get('visual_ko', '')}")
            print(f"    내레이션: {beat.get('narration_ko', '—')} · 자막: {beat.get('caption_ko', '—')} · "
                  f"근거: {', '.join(beat.get('evidence', [])) or '—'}")
    _dump_yaml({"by": record.model, "created_at": record.created_at, "check": issues}, folder / "script_check.yaml",
               "# 장면 초안에서 사람이 확인할 것")
    print()
    _print_check(issues)
    print(f"초안: {folder}\\scene_01.yaml … scene_{len(docs):02d}.yaml\n"
          f"다음: [입력] → ③ 장면 작성 → [초안 불러오기]. 장면마다 고친 뒤 저장한다.")
    return 0


def cmd_sheet(args: argparse.Namespace) -> int:
    """제품 레퍼런스 시트. 후보를 만들거나(--select 없이), 사람이 고른 후보를 기록한다(--select)."""
    bible = load_product_bible(EXAMPLE_DIR / "product_bible.yaml")
    try:
        product = bible.get(args.product)
    except KeyError as exc:
        print(f"[막힘] {exc.args[0]}. 있는 제품: {', '.join(bible.products)}")
        return 2
    recipe_policy = load_policy("reference_sheet")
    recipe = recipe_policy.data
    root = reference_sheet.sheet_root(product.id, OUTPUT_DIR)

    if args.select:                                   # ---- 고르기: 사람이 한다. 비용 없음
        try:
            picks, explicit = reference_sheet.parse_picks(args.select, recipe)
            manifest = reference_sheet.select(product, picks, recipe, EXAMPLE_DIR, OUTPUT_DIR, bible.version,
                                              args.by or "", args.note or "", explicit=explicit)
        except reference_sheet.SheetError as exc:
            print(f"[막힘] {exc}")
            return 4
        print(f"{product.id} 레퍼런스 {len(manifest['images'])}장 · 기록 {manifest['manifest_version']}판 · "
              f"{manifest['selected_by']} · {manifest['selected_at']}")
        for image in manifest["images"]:
            print(f"  {image['view']:<14}{image['from_version']}  {image['file']}  sha256 {image['sha256'][:12]}")
        print(f"기록: {reference_sheet.manifest_path(product.id, recipe, EXAMPLE_DIR)}")
        return 0

    findings = bible_lint.lint_bible(bible, load_policy("bible_rules").data, ClaimsGuard())
    if bible_lint.has_errors(findings, product.id):   # ---- 만들기 전에 바이블부터
        print(f"[막힘] {product.id}: 제품 바이블에 고칠 것이 있다. 틀린 서술로 만든 레퍼런스는 모든 장면에 퍼진다.")
        _print_findings([f for f in findings if f.level == "error"], product.id)
        return 4
    if not product.is_own and not args.approved_by:
        print(f"[막힘] {product.id} 는 타사 제품이다. 타사 제품의 이미지를 만드는 일은 사람이 승인한다 (--approved-by 이름).")
        print("  실제 타사 제품이라면 외형을 글로 지어내지 않는다. 직접 구입해 찍은 사진만 쓴다.")
        return 4

    models = load_policy("models")
    budget = load_policy("budget_policy")
    image_cfg = models.data["image"]
    photos = reference_sheet.photo_paths(product.id, recipe, EXAMPLE_DIR)
    mode = "photo" if photos else "text"
    version = reference_sheet.next_version(root)
    version_dir = root / version
    only = [v.strip() for v in args.views.split(",") if v.strip()] if args.views else None
    try:
        plans = reference_sheet.plan_views(product, recipe, photos, version_dir, only)
    except reference_sheet.SheetError as exc:
        print(f"[막힘] {exc}")
        return 4
    size = recipe["image"]["size"]
    unit = estimate_image_cost(size, models.data)
    total = round(unit * len(plans), 4)
    guard = BudgetGuard(_run_budget_usd(budget.data))

    print(f"{product.id} — {product.name_ko} · 후보 {version} · 방향 {len(plans)}개")
    if photos:
        print(f"만드는 길: 본인 사진 {len(photos)}장을 보고 그린다 ({reference_sheet.photo_dir(product.id, recipe, EXAMPLE_DIR)})")
    else:
        print(f"만드는 길: 사진이 없다. 외형 서술로 기준 방향({recipe['anchor_view']})을 먼저 만들고 나머지는 그것을 보고 그린다")
        print(f"  사진을 넣는 곳: {reference_sheet.photo_dir(product.id, recipe, EXAMPLE_DIR)}")
    print(f"모델 {image_cfg['id']} | {size} | {recipe['image']['aspect_ratio']} | "
          f"한 장 추정 ${unit:.4f} × {len(plans)} = ${total:.2f} (실행 예산 ${guard.cap_usd:.2f})")
    print("  추정에는 출력 이미지 값만 들어 있다. 입력과 사고 토큰은 따로 청구된다.")
    for plan in plans:
        refs = "기준 방향을 보고" if plan.uses_anchor else (f"사진 {len(plan.image_paths)}장을 보고" if plan.image_paths else "글만으로")
        print(f"\n[{plan.view_id} · {plan.name_ko}] {refs}")
        print(f"  {plan.prompt}")
    if total > guard.cap_usd:
        guard.charge(total, f"{product.id} 레퍼런스 시트 {len(plans)}장")

    if args.dry_run:
        print("\n[dry-run] 호출하지 않았다. 파일도 쓰지 않았다.")
        return 0
    if not os.environ.get("GEMINI_API_KEY"):
        print("\nGEMINI_API_KEY 가 없다. .env 에 키를 넣은 뒤 다시 실행한다.")
        return 2

    retry_policy = load_policy("retry_policy").data
    api_version = image_cfg.get("api_version", omni_client.DEFAULT_API_VERSION)
    made: list[str] = []
    failed = False
    for plan in plans:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = version_dir / os.path.basename(plan.output_path)
        request = image_client.build_request(
            plan.prompt, model=image_cfg["id"], image_paths=plan.image_paths,
            aspect_ratio=recipe["image"]["aspect_ratio"], image_size=size, mime_type=recipe["image"]["mime_type"],
            max_images=int(image_cfg["max_reference_images"]))
        record = RunRecord(
            run_id=run_id, purpose=f"ass sheet {product.id} {plan.view_id}", episode="sheet",
            scene_id=f"{product.id}/{plan.view_id}", model=image_cfg["id"],
            request=image_client.summarize_request(request, plan.image_paths),
            prompt_sha256=hashlib.sha256(plan.prompt.encode("utf-8")).hexdigest(),
            policy_hashes={p.name: p.policy_hash for p in (models, recipe_policy, budget)},
            estimated_cost_usd=unit, notes=f"api_version={api_version} mode={mode} version={version}")

        def before_attempt(attempt: int, plan=plan, record=record) -> None:
            guard.charge(unit, f"{product.id} {plan.view_id} ({attempt}번째 시도)")
            record.attempts = attempt

        def on_retry(attempt: int, exc: BaseException, wait: float) -> None:
            print(f"{attempt}번째 시도 실패: {type(exc).__name__}: {exc}")
            print(f"{wait:.0f}초 뒤에 다시 시도한다 (남은 실행 예산 ${guard.remaining_usd:.2f})", flush=True)

        print(f"\n{plan.view_id} 생성 중 …", flush=True)
        try:
            result, record.attempt_errors = retry.call_with_retry(
                lambda request=request, out=out: image_client.generate(request, out, api_version=api_version),
                retry_policy, before_attempt=before_attempt, on_retry=on_retry)
        except Exception as exc:
            record.status = "error"
            record.error = f"{type(exc).__name__}: {exc}"
            record.attempt_errors = list(getattr(exc, "attempt_errors", []))
            hint = omni_client.explain_error(exc)
            if hint:
                record.notes = f"{record.notes} | {hint}"
            record.save(out.with_suffix(".api_run.json"))
            print(f"실패: {record.error}")
            if hint:
                print(f"조치: {hint}")
            failed = True
            break                                      # 기준 방향이 없으면 나머지를 만들 수 없다
        record.interaction_id = result.interaction_id
        record.output_path = result.image_path
        record.elapsed_s = result.elapsed_s
        if result.usage:
            record.notes = f"{record.notes} | usage={json.dumps(result.usage, ensure_ascii=False)}"
        record.save(out.with_suffix(".api_run.json"))
        made.append(plan.view_id)
        print(f"저장: {out} ({result.bytes_written / 1e6:.2f}MB, {result.elapsed_s:.0f}초)")

    if made:
        ext = os.path.splitext(plans[0].output_path)[1]
        order = [v["id"] for v in recipe["views"] if (version_dir / f"{v['id']}{ext}").is_file()]
        sheet = reference_sheet.contact_sheet([version_dir / f"{v}{ext}" for v in order],
                                              version_dir / "contact_sheet.png", int(recipe["contact_sheet"]["cell_px"]))
        (version_dir / "sheet.json").write_text(json.dumps({
            "product_id": product.id, "version": version, "mode": mode, "views": made,
            "photos": [{"file": p.name, "sha256": reference_sheet.sha256_file(p)} for p in photos],
            "appearance_en": product.appearance_en, "bible_version": bible.version,
            "approved_by": args.approved_by, "created_at": datetime.now().isoformat(timespec="seconds"),
            "estimated_cost_usd": round(guard.spent_usd, 4),
            "policy_hashes": {p.name: p.policy_hash for p in (models, recipe_policy)},
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n후보 {version}: {', '.join(made)} · 추정 ${guard.spent_usd:.2f}")
        if sheet:
            print(f"한눈에 보기: {sheet} (왼쪽부터 {', '.join(order)})")
        else:
            print("한눈에 보는 이음판은 만들지 못했다 (FFmpeg 가 없다). 낱장을 하나씩 연다.")
        print(f"보고 고른다: ass sheet --product {product.id} --select {version} --by 이름")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ass", description="ASS (Autonomous Shorts Studio)",
        epilog="다른 명령은 해당 장에서 추가한다. 목록과 상태는 README 를 본다.",
    )
    parser.add_argument("--version", action="version", version=f"ass {__version__}")
    parser.add_argument("--project", default=None, metavar="이름",
                        help="이번 한 번만 이 프로젝트에서 실행한다. 견본은 sample. 기본은 현재 프로젝트")
    sub = parser.add_subparsers(dest="command", required=True)

    i = sub.add_parser("init", help="내 프로젝트 폴더를 만든다")
    i.add_argument("name", help="프로젝트 이름. 영문 소문자, 숫자, 밑줄")
    i.set_defaults(func=cmd_init)

    pj = sub.add_parser("project", help="현재 프로젝트를 보여 주거나 바꾼다")
    pj.add_argument("name", nargs="?", default=None, help="바꿀 프로젝트 이름. 견본은 sample")
    pj.set_defaults(func=cmd_project)

    d = sub.add_parser("doctor", help="환경 점검")
    d.add_argument("--write", action="store_true", help="docs/setup.md 로 저장")
    d.set_defaults(func=cmd_doctor)

    g = sub.add_parser("console", help="콘솔(화면)을 연다")
    g.set_defaults(func=cmd_console)

    m = sub.add_parser("map", help="여섯 단계 공정 지도와 명령의 상태")
    m.add_argument("--write", action="store_true", help="docs/workflow_map.md 로 저장")
    m.set_defaults(func=cmd_map)

    s = sub.add_parser("stack", help="기술 스택과 확인 상태")
    s.set_defaults(func=cmd_stack)

    c = sub.add_parser("compile", help="장면 사양 → 프롬프트·내레이션 대본 (비용 없음)")
    c.add_argument("--episode", default="product_intro", help="예제 폴더의 episodes 아래 이름")
    c.set_defaults(func=cmd_compile)

    r = sub.add_parser("render", help="장면 하나를 생성하고 실행 기록을 남김")
    r.add_argument("--episode", default="product_intro")
    r.add_argument("--scene", type=int, default=1, help="장면 번호 (1부터)")
    r.add_argument("--duration", type=int, default=None, help="초(3~15). 기본은 장면 사양의 길이")
    r.add_argument("--prompt", default=None, help="장면 사양 대신 쓸 프롬프트 한 줄 (--duration 필요)")
    r.add_argument("--resolution", default=None, choices=["360p", "720p", "1080p", "4k"],
                   help="기본은 production_spec 의 초안 해상도")
    r.add_argument("--aspect", default=None, choices=["9:16", "16:9"], help="화면비. 기본 9:16")
    r.add_argument("--delivery", default="inline", choices=["inline", "uri"],
                   help="결과를 받는 방식. 4MB 를 넘으면 uri")
    r.add_argument("--name", default=None, help="결과 파일 이름(확장자 없이). 기본은 장면 id 와 실행 시각")
    r.add_argument("--dry-run", action="store_true", help="API를 호출하지 않고 요청만 출력")
    r.set_defaults(func=cmd_render)

    a = sub.add_parser("assemble", help="장면 영상을 이어 붙여 초안 한 편을 만든다 (비용 없음)")
    a.add_argument("--episode", default="product_intro")
    a.add_argument("--pick", action="append", metavar="장면=RUN_ID",
                   help="장면에 쓸 실행을 고른다. 예: --pick 2=20261120-101500. 기본은 가장 최근의 성공한 실행")
    a.add_argument("--name", default=None, help="결과 파일 이름(확장자 없이). 기본은 레시피의 output_name")
    a.add_argument("--dry-run", action="store_true", help="FFmpeg 를 실행하지 않고 계획과 명령만 출력")
    a.set_defaults(func=cmd_assemble)

    b = sub.add_parser("bible", help="제품 바이블을 점검한다 (비용 없음)")
    b.add_argument("--product", default=None, help="한 제품만 볼 때. 기본은 전체")
    b.set_defaults(func=cmd_bible)

    s = sub.add_parser("sheet", help="제품 레퍼런스 시트 후보를 만들거나, 고른 후보를 기록한다")
    s.add_argument("--product", default="moalab_aqua_serum")
    s.add_argument("--views", default=None, help="만들 방향. 쉼표로 나눈다. 기본은 레시피의 전체")
    s.add_argument("--dry-run", action="store_true", help="호출하지 않고 계획과 프롬프트만 출력")
    s.add_argument("--approved-by", default=None, help="타사 제품의 이미지를 만들 때 승인한 사람")
    s.add_argument("--select", action="append", metavar="버전 또는 방향=버전",
                   help="사람이 고른 후보. 예: --select v002 (전체) --select label=v001 (한 방향)")
    s.add_argument("--by", default=None, help="--select 와 함께. 고른 사람")
    s.add_argument("--note", default=None, help="--select 와 함께. 고른 이유")
    s.set_defaults(func=cmd_sheet)

    bf = sub.add_parser("brief", help="원문에서 소재 요약의 초안을 만든다 (글 모델)")
    bf.add_argument("--episode", default="product_intro")
    bf.add_argument("--type", dest="source_type", default="idea", choices=["idea", "own_blog", "own_video_script"])
    bf.add_argument("--format", default="product_intro")
    bf.add_argument("--products", default="", help="나오는 제품 id. 쉼표로 여럿")
    bf.add_argument("--origin", default=None, help="블로그 글이나 영상의 주소, 파일 경로")
    bf.add_argument("--idea", default=None, help="아이디어 한 줄. 없으면 sources/<편>.txt 를 읽는다")
    bf.add_argument("--owner-confirmed", action="store_true", help="내가 쓴 것이거나 쓸 권리가 있는 소재임을 확인했다")
    bf.add_argument("--dry-run", action="store_true", help="호출하지 않고 보내는 글만 출력")
    bf.set_defaults(func=cmd_brief)

    sc = sub.add_parser("script", help="소재 요약에서 장면 사양의 초안을 만든다 (글 모델)")
    sc.add_argument("--episode", default="product_intro")
    sc.add_argument("--dry-run", action="store_true", help="호출하지 않고 보내는 글만 출력")
    sc.set_defaults(func=cmd_script)

    u = sub.add_parser("reuse", help="다른 프로젝트에서 같은 프롬프트로 만든 영상을 가져온다 (비용 없음)")
    u.add_argument("--from", dest="source", default="sample", help="가져올 곳. 프로젝트 이름. 기본은 견본(sample)")
    u.add_argument("--episode", default="product_intro")
    u.add_argument("--dry-run", action="store_true", help="복사하지 않고 무엇을 가져올 수 있는지만 본다")
    u.set_defaults(func=cmd_reuse)

    k = sub.add_parser("cost", help="실행 기록을 모아 비용 장부와 오류 기록을 만든다")
    k.add_argument("--episode", default=None, help="한 편만 볼 때. 기본은 전체")
    k.add_argument("--billed", type=float, default=None, help="결제 화면에서 본 실제 청구액(USD)을 적는다")
    k.add_argument("--note", default=None, help="--billed 와 함께 남길 메모")
    k.set_defaults(func=cmd_cost)
    return parser


def available_commands() -> set[str]:
    """실제로 등록된 명령 이름. 공정 지도의 '있음/없음' 표시는 여기서 나온다."""
    parser = build_parser()
    for action in parser._subparsers._group_actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return set(action.choices)
    return set()


def cmd_init(args: argparse.Namespace) -> int:
    """내 프로젝트 폴더를 만들고 현재 프로젝트로 삼는다."""
    from ass import authoring, settings

    try:
        folder = authoring.init_project(args.name)
    except authoring.InputError as exc:
        print(f"[막힘] {exc}")
        return 4
    settings.write_prefs({"project": args.name})
    print(f"프로젝트를 만들었다: {folder}")
    print("  product_bible.yaml   제품        콘솔 [입력] → 제품 등록")
    print("  source_briefs/       소재 요약    콘솔 [입력] → 소재 입력")
    print("  episodes/            장면        콘솔 [입력] → 장면 작성")
    print("  assets/products/     사진과 고른 레퍼런스")
    print("  outputs/             이 프로젝트의 산출물")
    print(f"현재 프로젝트: {args.name}. 이제부터 명령과 콘솔이 이 폴더를 쓴다. 견본으로 돌아가려면 ass project sample")
    return 0


def cmd_project(args: argparse.Namespace) -> int:
    """현재 프로젝트를 보여 주거나 바꾼다."""
    from ass import settings

    names = settings.list_projects()
    if args.name:
        if args.name != settings.SAMPLE_NAME and args.name not in names:
            print(f"[막힘] 없는 프로젝트: {args.name}. 있는 것: {', '.join(names) or '없음'}. 새로 만들려면 ass init {args.name}")
            return 4
        settings.write_prefs({"project": args.name})
        folder, outputs = settings.project_paths(args.name)
        print(f"현재 프로젝트: {args.name}\n  작업 폴더: {folder}\n  산출물: {outputs}")
        return 0
    current = settings.resolve_project()
    for name in [settings.SAMPLE_NAME] + names:
        folder, _ = settings.project_paths(name)
        note = " (책의 견본. 고치지 않는다)" if name == settings.SAMPLE_NAME else ""
        print(f"{'*' if name == current else ' '} {name:<20}{folder}{note}")
    print("바꾸기: ass project 이름 · 새로 만들기: ass init 이름 · 한 번만 다른 곳에서: ass --project 이름 명령")
    return 0


def _run_in_project(name: str, argv: list[str]) -> int:
    """`--project 이름` 은 그 프로젝트를 가리키는 환경 변수를 주고 같은 명령을 다시 실행한다.

    작업 폴더는 프로그램이 시작할 때 한 번 정해지므로, 도중에 바꾸지 않고 새로 시작한다.
    """
    import subprocess

    from ass import settings

    if name != settings.SAMPLE_NAME and name not in settings.list_projects():
        print(f"[막힘] 없는 프로젝트: {name}. 새로 만들려면 ass init {name}")
        return 4
    rest, skip = [], False
    for arg in argv:
        if skip:
            skip = False
        elif arg == "--project":
            skip = True
        elif not arg.startswith("--project="):
            rest.append(arg)
    env = dict(os.environ, ASS_PROJECT=name)
    return subprocess.call([sys.executable, "-m", "ass", *rest], env=env)


def main(argv: list[str] | None = None) -> int:
    _setup()
    argv = sys.argv[1:] if argv is None else list(argv)
    args = build_parser().parse_args(argv)
    from ass import settings

    if getattr(args, "project", None) and args.project != settings.PROJECT:
        return _run_in_project(args.project, argv)
    if settings.PROJECT != settings.SAMPLE_NAME and args.command not in ("init", "project", "console", "doctor"):
        print(f"[프로젝트 {settings.PROJECT}] {settings.PROJECT_DIR}", flush=True)
    try:
        return int(args.func(args))
    except CompileError as exc:      # 가드가 막은 것은 오류가 아니라 정상 동작이다
        print(f"[막힘] {exc}")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
