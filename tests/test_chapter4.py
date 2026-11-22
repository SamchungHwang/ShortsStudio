"""4장: 조립(ass assemble), 재시도, 비용 장부(ass cost)."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from ass import cli, ledger
from ass import console_model as model
from ass.policy import load_policy
from ass.production import assembler, retry
from ass.production.assembler import AssembleError, ClipInfo
from ass.production.run_record import RunRecord

RECIPE = load_policy("assemble_recipe").data
RETRY = load_policy("retry_policy").data


def info(duration=15.0, w=720, h=1280, fps=24.0, audio=True) -> ClipInfo:
    return ClipInfo(duration_s=duration, width=w, height=h, fps=fps, has_audio=audio)


def record(folder, scene_id, run_id, status="ok", video=True, **extra):
    stem = f"{scene_id}.{run_id}"
    RunRecord(run_id=run_id, purpose=f"ass render product_intro {scene_id}", episode="product_intro",
              scene_id=scene_id, model="gemini-omni-1.2-flash",
              request={"response_format": {"duration": "15s", "resolution": "720p"}},
              estimated_cost_usd=1.05, status=status, **extra).save(folder / f"{stem}.api_run.json")
    if video:
        (folder / f"{stem}.mp4").write_bytes(b"x")
    return folder / f"{stem}.mp4"


# ---------------------------------------------------------------- 고르기
def test_가장_최근의_성공한_실행을_고른다(tmp_path):
    record(tmp_path, "serum_s01", "20261120-100000")
    newest = record(tmp_path, "serum_s01", "20261120-110000")
    record(tmp_path, "serum_s01", "20261120-120000", status="error", video=False)
    record(tmp_path, "serum_s01", "20261120-130000", status="dry_run", video=False)
    assert assembler.find_render(tmp_path, "serum_s01") == (newest, "20261120-110000")
    picked, run_id = assembler.find_render(tmp_path, "serum_s01", "20261120-100000")
    assert picked.name == "serum_s01.20261120-100000.mp4" and run_id == "20261120-100000"


def test_영상이_없으면_무엇을_할지_알려_준다(tmp_path):
    with pytest.raises(AssembleError, match="ass render --scene N"):
        assembler.find_render(tmp_path, "serum_s01")
    (tmp_path / "serum_s01.mp4").write_bytes(b"x")        # 화면에서 만든 영상을 넣어 둔 경우
    assert assembler.find_render(tmp_path, "serum_s01") == (tmp_path / "serum_s01.mp4", None)


def test_ffprobe_출력을_읽는다():
    doc = {"streams": [{"codec_type": "video", "width": 720, "height": 1280, "avg_frame_rate": "24000/1001",
                        "codec_name": "h264"}, {"codec_type": "audio"}],
           "format": {"duration": "15.015", "size": "3900000"}}
    got = assembler.parse_probe(doc)
    assert (got.duration_s, got.width, got.height, got.fps, got.has_audio) == (15.015, 720, 1280, 23.976, True)
    with pytest.raises(AssembleError):
        assembler.parse_probe({"streams": [{"codec_type": "audio"}]})


# ---------------------------------------------------------------- 계획
def _plan(scenes, production_spec, infos, recipe=RECIPE, tmp="out.mp4"):
    clips = [(f"/r/{s.scene_id}.mp4", "20261120-110000", i) for s, i in zip(scenes, infos)]
    return assembler.plan("product_intro", scenes, clips, recipe, production_spec, tmp)


def test_세_장면_45초는_정책_안이다(scenes, production_spec):
    a = _plan(scenes, production_spec, [info(), info(), info()])
    assert a.total_s == 45.0 and a.problems == [] and a.notes == []


def test_요청과_다른_것은_알려_준다(scenes, production_spec):
    a = _plan(scenes, production_spec, [info(), info(14.2), info(w=1280, h=720, fps=30.0, audio=False)])
    text = " / ".join(a.notes)
    assert "요청한 길이는 15초인데 실제는 14.20초" in text
    assert "크기가 1280x720" in text and "소리가 없다" in text and "프레임 수가 다르다" in text
    assert a.total_s == 44.2 and a.problems == []


def test_길이_정책을_벗어나면_문제로_적는다(scenes, production_spec):
    short = _plan(scenes, production_spec, [info(10), info(10), info(10)])
    assert "목표 42~48초를 벗어난다" in short.problems[0]
    long = _plan(scenes, production_spec, [info(25), info(25), info(25)])
    assert "상한 60초를 넘는다" in long.problems[0]


def test_잘라_내기와_FFmpeg_명령(scenes, production_spec):
    recipe = json.loads(json.dumps(RECIPE))
    recipe["trim"] = {"head_s": 0.5, "tail_s": 0.5}
    a = _plan(scenes, production_spec, [info(), info(), info(audio=False)], recipe)
    assert [c.used_s for c in a.clips] == [14.0, 14.0, 14.0] and a.total_s == 42.0
    command = assembler.build_command(a, recipe)
    graph = command[command.index("-filter_complex") + 1]
    assert command.count("-i") == 3 and command[-1] == "out.mp4"
    assert "[0:v]trim=start=0.5:end=14.5" in graph and "scale=720:1280" in graph and "fps=24" in graph
    assert "anullsrc=r=48000:cl=stereo,atrim=duration=14[a2]" in graph      # 소리 없는 장면은 무음
    assert graph.endswith("[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a]")


def test_자막_시간은_앞_장면의_실제_길이만큼_밀린다(scenes, production_spec):
    a = _plan(scenes, production_spec, [info(), info(14.6), info()])
    srt = assembler.srt_text(scenes, a)
    assert srt.startswith("1\n00:00:00,000 --> ")
    assert "00:00:29,600 --> " in srt           # 장면 3 은 15 + 14.6 초에서 시작한다
    assert "00:00:44,600" in srt


# ---------------------------------------------------------------- 재시도
class ApiError(Exception):
    def __init__(self, code):
        super().__init__(f"Error code: {code} - 예시")
        self.code = code


def test_다시_해도_되는_오류와_안_되는_오류():
    assert retry.status_code(ApiError(429)) == 429
    assert retry.status_code(Exception("404 Model not found")) == 404
    assert retry.should_retry(ApiError(429), RETRY) and retry.should_retry(ApiError(503), RETRY)
    assert not retry.should_retry(ApiError(402), RETRY) and not retry.should_retry(ApiError(404), RETRY)
    assert not retry.should_retry(TimeoutError("timed out"), RETRY)     # 청구됐을 수 있다
    assert not retry.should_retry(ValueError("모르는 오류"), RETRY)


def test_기다렸다가_다시_부르고_시도마다_예산을_뺀다():
    calls, waits, charged = [], [], []

    def call():
        calls.append(1)
        if len(calls) < 3:
            raise ApiError(429)
        return "ok"

    result, errors = retry.call_with_retry(call, RETRY, before_attempt=charged.append, sleep=waits.append)
    assert result == "ok" and len(errors) == 2 and charged == [1, 2, 3] and waits == [30.0, 60.0]


def test_다시_해도_같은_오류는_바로_올린다():
    waits = []
    with pytest.raises(ApiError) as caught:
        retry.call_with_retry(lambda: (_ for _ in ()).throw(ApiError(402)), RETRY, sleep=waits.append)
    assert waits == [] and caught.value.attempts == 1


def test_끝까지_실패하면_앞선_오류를_붙여_올린다():
    with pytest.raises(ApiError) as caught:
        retry.call_with_retry(lambda: (_ for _ in ()).throw(ApiError(503)), RETRY, sleep=lambda s: None)
    assert caught.value.attempts == 3 and len(caught.value.attempt_errors) == 2


def test_render_는_다시_시도한_횟수를_기록에_남긴다(tmp_path, monkeypatch, capsys):
    from ass.production import omni_client

    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cli, "_setup", lambda: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(retry.time, "sleep", lambda s: None)
    attempts = []

    def fake(request, path, api_version):
        attempts.append(1)
        if len(attempts) == 1:
            raise ApiError(503)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video")
        return omni_client.OmniResult(video_path=str(path), interaction_id="i-1", model="m", elapsed_s=90.0,
                                      bytes_written=5, request={})

    monkeypatch.setattr(omni_client, "generate", fake)
    assert cli.main(["render", "--scene", "1", "--name", "t"]) == 0
    doc = json.loads((tmp_path / "renders" / "product_intro" / "t.api_run.json").read_text(encoding="utf-8"))
    assert doc["attempts"] == 2 and len(doc["attempt_errors"]) == 1 and doc["status"] == "ok"
    assert doc["episode"] == "product_intro" and doc["scene_id"] == "serum_s01"
    assert "30초 뒤에 다시 시도한다" in capsys.readouterr().out


# ---------------------------------------------------------------- 비용 장부
def _ledger_fixture(tmp_path):
    folder = tmp_path / "renders" / "product_intro"
    folder.mkdir(parents=True)
    record(folder, "serum_s01", "20261120-110000", attempts=1, elapsed_s=95.2)
    record(folder, "serum_s02", "20261120-110100", status="error", video=False, attempts=3,
           error="ClientError: Error code: 429", notes="요청 한도에 걸렸다.")
    record(folder, "serum_s02", "20261120-110200", attempts=2, elapsed_s=101.7)
    record(folder, "serum_s03", "20261120-110500", attempts=1, elapsed_s=88.0)
    record(folder, "serum_s03", "20261120-100000", status="dry_run", video=False)
    return folder


def test_장부는_성공과_실패를_따로_더한다(tmp_path):
    _ledger_fixture(tmp_path)
    rows = ledger.collect(tmp_path)
    s = ledger.summarize(rows)
    assert (s.ok_calls, s.ok_usd, s.ok_seconds) == (3, 3.15, 45.0)
    assert (s.failed_calls, s.failed_usd) == (4, 4.2)        # 실패 3회 + 성공 전 실패 1회
    assert s.dry_runs == 1 and s.worst_case_usd == 7.35 and s.elapsed_s == 284.9
    assert ledger.collect(tmp_path, "other") == []


def test_cost_명령은_장부와_오류_기록을_쓴다(tmp_path, monkeypatch, capsys):
    _ledger_fixture(tmp_path)
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cli, "_setup", lambda: None)
    assert cli.main(["cost", "--episode", "product_intro", "--billed", "3.20", "--note", "예시"]) == 0
    out = capsys.readouterr().out
    assert "성공 3건 추정 $3.15" in out and "청구 여부는 확인하지 못했다" in out and "차이 +0.05" in out
    csv_text = (tmp_path / "ledger" / "cost_ledger.csv").read_text(encoding="utf-8-sig")
    assert csv_text.splitlines()[0].startswith("run_id,created_at,episode,scene_id") and len(csv_text.splitlines()) == 6
    log = (tmp_path / "ledger" / "error_log.md").read_text(encoding="utf-8")
    assert "실패한 호출 1건" in log and "Error code: 429" in log and "시도 횟수: 3" in log
    assert "3.2" in (tmp_path / "ledger" / "billing_checks.csv").read_text(encoding="utf-8-sig")


def test_기록이_없으면_할_일을_알려_준다(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cli, "_setup", lambda: None)
    assert cli.main(["cost"]) == 0 and "ass render 를 먼저" in capsys.readouterr().out


# ---------------------------------------------------------------- 명령과 콘솔
def test_assemble_은_영상이_없으면_막고_이유를_말한다(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cli, "_setup", lambda: None)
    assert cli.main(["assemble"]) == 2
    assert "이어 붙일 영상이 없다" in capsys.readouterr().out


def test_콘솔은_assemble_이_읽고_쓰는_파일을_보여_준다(tmp_path):
    rows = model.command_files("assemble", "product_intro", output_dir=tmp_path)
    assert [r.mark for r in rows] == ["①", "①", "①", "②", "②", "②", "③", "④", "→", "→", "→", "→"]
    assert "ass render --scene 2 을 먼저 실행한다" in rows[1].what and not rows[1].exists
    folder = tmp_path / "renders" / "product_intro"
    folder.mkdir(parents=True)
    record(folder, "serum_s02", "20261120-110200")
    rows = model.command_files("assemble", "product_intro", output_dir=tmp_path)
    assert rows[1].exists and "실행 20261120-110200" in rows[1].what
    assert model.build_runs("assemble", "product_intro", dry_run=True) == [["assemble", "--episode", "product_intro", "--dry-run"]]
    assert model.build_runs("assemble", "product_intro", dry_run=False) == [["assemble", "--episode", "product_intro"]]


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg 가 없다")
def test_실제_FFmpeg_로_세_장면을_잇는다(tmp_path, monkeypatch, capsys):
    """합성 영상 세 개(길이, 크기, 프레임 수, 소리 유무가 서로 다르다)를 실제로 이어 붙인다."""
    folder = tmp_path / "renders" / "product_intro"
    folder.mkdir(parents=True)
    shapes = [("serum_s01", "3", "720x1280", "24", True), ("serum_s02", "2.6", "720x1280", "24", True),
              ("serum_s03", "3", "1280x720", "30", False)]
    for scene_id, seconds, size, fps, audio in shapes:
        video = record(folder, scene_id, "20261120-110000")
        command = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={size}:r={fps}:d={seconds}"]
        if audio:
            command += ["-f", "lavfi", "-i", f"sine=f=440:d={seconds}", "-c:a", "aac", "-shortest"]
        subprocess.run(command + ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cli, "_setup", lambda: None)
    assert cli.main(["assemble"]) == 1                    # 8.6초라 길이 정책을 벗어난다. 영상은 만든다
    out = capsys.readouterr().out
    assert "목표 42~48초를 벗어난다" in out and "소리가 없다" in out
    result = assembler.probe(tmp_path / "episodes" / "product_intro" / "draft_45s.mp4")
    assert (result.width, result.height, result.has_audio) == (720, 1280, True)
    assert abs(result.duration_s - 8.6) < 0.2 and result.fps == 24.0
    manifest = json.loads((tmp_path / "episodes" / "product_intro" / "draft_45s.assembly.json").read_text(encoding="utf-8"))
    assert manifest["total_s"] == 8.6 and manifest["policy_hashes"]["assemble_recipe"]
    assert (tmp_path / "episodes" / "product_intro" / "draft_45s.srt").is_file()
    review = tmp_path / "episodes" / "product_intro" / "draft_45s.review.md"
    assert "| 라벨 글자 |" in review.read_text(encoding="utf-8")
    review.write_text("사람이 적은 것", encoding="utf-8")
    cli.main(["assemble"])
    assert review.read_text(encoding="utf-8") == "사람이 적은 것"       # 덮어쓰지 않는다


def test_콘솔에서_고를_수_있는_영상은_성공한_실행뿐이다(tmp_path):
    folder = tmp_path / "renders" / "product_intro"
    folder.mkdir(parents=True)
    record(folder, "serum_s02", "20261120-110200", elapsed_s=101.7)
    record(folder, "serum_s02", "20261120-120000", elapsed_s=90.0)
    record(folder, "serum_s02", "20261120-130000", status="error", video=False)
    choices = model.render_choices("product_intro", output_dir=tmp_path)
    assert [(n, scene_id, len(runs)) for n, scene_id, runs in choices] == [
        (1, "serum_s01", 0), (2, "serum_s02", 2), (3, "serum_s03", 0)]
    assert choices[1][2][0].run_id == "20261120-120000" and "90초 걸림" in choices[1][2][0].label   # 최근 것부터
    rows = model.command_files("assemble", "product_intro", output_dir=tmp_path, picks={"2": "20261120-110200"})
    assert "실행 20261120-110200" in rows[1].what and "직접 고른 것" in rows[1].what


def test_cost_는_편을_골라도_장부_파일에는_전체를_쓴다(tmp_path, monkeypatch, capsys):
    _ledger_fixture(tmp_path)
    other = tmp_path / "renders" / "adhoc"
    other.mkdir()
    RunRecord(run_id="20261119-090000", purpose="ch02", model="m", request={}, estimated_cost_usd=0.35,
              status="ok").save(other / "first_render.api_run.json")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cli, "_setup", lambda: None)
    assert cli.main(["cost", "--episode", "product_intro"]) == 0
    out = capsys.readouterr().out
    assert "adhoc" not in out.split("장부:")[0] and "(전체 6건)" in out
    assert "adhoc" in (tmp_path / "ledger" / "cost_ledger.csv").read_text(encoding="utf-8-sig")


# ---------------------------------------------------------------- 이미 만든 영상 다시 쓰기
def test_같은_요청으로_만든_영상만_가져온다(tmp_path):
    from ass.production import reuse

    source = tmp_path / "sample_outputs"
    folder = source / "renders" / "product_intro"
    folder.mkdir(parents=True)
    fmt = {"type": "video", "aspect_ratio": "9:16", "resolution": "720p", "duration": "15s"}

    def make(run_id, sha, status="ok", video=True, **request):
        RunRecord(run_id=run_id, purpose="p", model="m", request={"response_format": {**fmt, **request}},
                  prompt_sha256=sha, estimated_cost_usd=1.05, status=status).save(folder / f"s1.{run_id}.api_run.json")
        if video:
            (folder / f"s1.{run_id}.mp4").write_bytes(run_id.encode())

    make("20261121-100000", "aaa")
    make("20261121-110000", "aaa")
    make("20261121-120000", "aaa", status="error", video=False)
    make("20261121-130000", "bbb")
    make("20261121-140000", "aaa", resolution="1080p")
    found = reuse.find_reusable(source, "aaa", "m", fmt)
    assert found.run_id == "20261121-110000" and found.estimated_cost_usd == 1.05          # 가장 최근의 같은 요청
    assert reuse.find_reusable(source, "ccc", "m", fmt) is None                            # 프롬프트가 다르면 없다
    assert reuse.find_reusable(source, "aaa", "other", fmt) is None                        # 모델이 달라도 없다

    target = tmp_path / "mine" / "renders" / "ep"
    assert not reuse.already_here(target, "serum_s01", "aaa")
    video = reuse.bring(found, target, "serum_s01", "ep", "sample")
    assert video.read_bytes() == b"20261121-110000" and reuse.already_here(target, "serum_s01", "aaa")
    doc = json.loads((target / "serum_s01.20261121-110000.api_run.json").read_text(encoding="utf-8"))
    assert doc["estimated_cost_usd"] == 0.0 and doc["original_cost_usd"] == 1.05 and doc["reused_from"].startswith("sample: ")
    assert assembler.find_render(target, "serum_s01") == (video, "20261121-110000")       # 조립이 그대로 쓴다
    rows = ledger.collect(tmp_path / "mine")
    s = ledger.summarize(rows)
    assert (s.reused, s.reused_saved_usd, s.ok_calls, s.ok_usd) == (1, 1.05, 0, 0.0) and rows[0].calls == 0
    assert reuse.find_reusable(tmp_path / "mine", "aaa", "m", fmt) is None                 # 가져온 것을 또 가져가지 않는다
