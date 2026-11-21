"""조립 (4.1절). 장면 영상 세 개를 FFmpeg 로 이어 붙여 초안 한 편을 만든다.

하는 일은 넷이다.
  1. 장면마다 쓸 영상을 고른다 — 실행 기록(api_run.json)이 ok 인 것 가운데 가장 최근 것.
  2. ffprobe 로 실제 길이, 크기, 프레임 수, 소리 유무를 잰다 — 요청한 값과 다를 수 있다.
  3. 크기와 프레임 수를 맞추고 차례로 잇는 FFmpeg 명령을 만든다.
  4. 자막 문구를 시간에 맞춰 .srt 파일로 쓴다 — 영상에 입히지는 않는다(12장).

전환, 자막 입히기, 내레이션과 음악은 여기서 다루지 않는다. 레시피는 configs/assemble_recipe.yaml 에 있다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ass.production.scene_spec import SceneSpec


class AssembleError(Exception):
    """조립할 수 없다. 영상이 없거나 FFmpeg 가 없거나 실패했다."""


class ClipInfo(BaseModel):
    """ffprobe 로 잰 값."""
    duration_s: float
    width: int
    height: int
    fps: float
    has_audio: bool
    video_codec: str = ""
    size_bytes: int = 0


class Clip(BaseModel):
    scene_id: str
    path: str
    run_id: str | None = None          # 실행 기록이 없는 영상이면 None
    requested_s: float | None = None   # 장면 사양의 길이
    info: ClipInfo
    start_s: float = 0.0               # 이 장면에서 쓰는 구간 (잘라 낸 뒤)
    end_s: float = 0.0

    @property
    def used_s(self) -> float:
        return round(self.end_s - self.start_s, 3)


class Assembly(BaseModel):
    episode: str
    output_path: str
    clips: list[Clip]
    total_s: float
    notes: list[str] = []              # 알려 줄 것. 막지는 않는다
    problems: list[str] = []           # 길이 정책 위반
    command: list[str] = []
    recipe_version: str = ""


# ---------------------------------------------------------------- 고르기
def find_render(render_dir: Path, scene_id: str, run_id: str | None = None) -> tuple[Path, str | None]:
    """장면 하나에 쓸 영상을 고른다. 돌려주는 값은 (영상 경로, run_id).

    실행 기록이 ok 이고 영상 파일이 있는 것 가운데 가장 최근 것을 쓴다. run_id 를 주면 그것을 쓴다.
    기록 없이 <scene_id>.mp4 만 있으면(화면에서 만든 영상을 넣어 둔 경우) 그것을 쓴다.
    """
    candidates: list[tuple[str, Path]] = []
    for record_path in sorted(render_dir.glob(f"{scene_id}.*.api_run.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        video = record_path.with_name(record_path.name.replace(".api_run.json", ".mp4"))
        if record.get("status") == "ok" and video.is_file():
            candidates.append((str(record.get("run_id", "")), video))
    if run_id is not None:
        for rid, video in candidates:
            if rid == run_id:
                return video, rid
        raise AssembleError(f"{scene_id}: run_id {run_id} 의 영상이 없다 ({render_dir})")
    if candidates:
        rid, video = max(candidates, key=lambda c: c[0])
        return video, rid
    plain = render_dir / f"{scene_id}.mp4"
    if plain.is_file():
        return plain, None
    raise AssembleError(
        f"{scene_id}: 이어 붙일 영상이 없다. 먼저 ass render --scene N 으로 생성한다 ({render_dir})")


# ---------------------------------------------------------------- 재기
def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise AssembleError(f"{name} 가 없다. winget install -e --id Gyan.FFmpeg 로 설치하고 창을 새로 연 뒤 ass doctor 로 확인한다.")
    return path


def _fps(text: str) -> float:
    try:
        num, _, den = text.partition("/")
        return round(float(num) / float(den or 1), 3)
    except (ValueError, ZeroDivisionError):
        return 0.0


def parse_probe(doc: dict[str, Any]) -> ClipInfo:
    """ffprobe -of json 의 출력을 ClipInfo 로 바꾼다."""
    streams = doc.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise AssembleError("영상 스트림이 없는 파일이다")
    fmt = doc.get("format", {})
    return ClipInfo(
        duration_s=round(float(fmt.get("duration") or video.get("duration") or 0), 3),
        width=int(video["width"]), height=int(video["height"]),
        fps=_fps(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        video_codec=str(video.get("codec_name", "")),
        size_bytes=int(fmt.get("size") or 0),
    )


def probe(path: Path) -> ClipInfo:
    result = subprocess.run(
        [_tool("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise AssembleError(f"{path.name}: ffprobe 실패 — {result.stderr.strip().splitlines()[-1:]}")
    return parse_probe(json.loads(result.stdout))


# ---------------------------------------------------------------- 계획
def plan(episode: str, scenes: list[SceneSpec], clips: list[tuple[Path, str | None, ClipInfo]],
         recipe: dict[str, Any], production_spec: dict[str, Any], output_path: Path) -> Assembly:
    """무엇을 어디서 어디까지 쓸지 정하고, 길이 정책에 맞는지 본다. FFmpeg 를 부르지 않는다."""
    head, tail = float(recipe["trim"]["head_s"]), float(recipe["trim"]["tail_s"])
    tolerance = float(recipe.get("length_tolerance_s", 0.5))
    target_w, target_h = int(recipe["video"]["width"]), int(recipe["video"]["height"])
    notes: list[str] = []
    planned: list[Clip] = []
    for scene, (path, run_id, info) in zip(scenes, clips):
        end = round(info.duration_s - tail, 3)
        if end - head <= 0:
            raise AssembleError(f"{scene.scene_id}: 잘라 내면 남는 길이가 없다 (실제 {info.duration_s}초)")
        planned.append(Clip(scene_id=scene.scene_id, path=str(path), run_id=run_id,
                            requested_s=scene.duration_s, info=info, start_s=head, end_s=end))
        if abs(info.duration_s - scene.duration_s) > tolerance:
            notes.append(f"{scene.scene_id}: 요청한 길이는 {scene.duration_s}초인데 실제는 {info.duration_s:.2f}초다")
        if (info.width, info.height) != (target_w, target_h):
            notes.append(f"{scene.scene_id}: 크기가 {info.width}x{info.height} 다. {target_w}x{target_h} 로 맞춘다")
        if not info.has_audio:
            notes.append(f"{scene.scene_id}: 소리가 없다. 이 구간은 무음으로 채운다")
        if run_id is None:
            notes.append(f"{scene.scene_id}: 실행 기록이 없는 영상이다. 비용 장부에 잡히지 않는다")
    rates = {c.info.fps for c in planned}
    if len(rates) > 1:
        notes.append(f"장면마다 프레임 수가 다르다 ({', '.join(str(r) for r in sorted(rates))}). 하나로 맞춘다")

    total = round(sum(c.used_s for c in planned), 3)
    policy = production_spec["episode"]
    lo, hi, hard = policy["total_duration_s"]["min"], policy["total_duration_s"]["max"], policy["hard_max_s"]
    problems: list[str] = []
    if total > hard:
        problems.append(f"전체 길이 {total:.1f}초가 상한 {hard}초를 넘는다")
    elif not lo <= total <= hi:
        problems.append(f"전체 길이 {total:.1f}초가 목표 {lo}~{hi}초를 벗어난다")
    return Assembly(episode=episode, output_path=str(output_path), clips=planned, total_s=total,
                    notes=notes, problems=problems, recipe_version=str(recipe.get("version", "")))


def build_command(assembly: Assembly, recipe: dict[str, Any], ffmpeg: str = "ffmpeg") -> list[str]:
    """FFmpeg 명령을 만든다. 장면마다 자르고, 크기·프레임 수·소리 형식을 맞춘 뒤 차례로 잇는다."""
    v, a = recipe["video"], recipe["audio"]
    w, h = int(v["width"]), int(v["height"])
    fps = assembly.clips[0].info.fps if str(v["fps"]) == "source" else float(v["fps"])
    fps_text = f"{fps:g}" if fps else "30"
    rate, layout = int(a["sample_rate"]), str(a["channel_layout"])

    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for clip in assembly.clips:
        command += ["-i", clip.path]
    chains: list[str] = []
    labels = ""
    for n, clip in enumerate(assembly.clips):
        chains.append(
            f"[{n}:v]trim=start={clip.start_s:g}:end={clip.end_s:g},setpts=PTS-STARTPTS,"
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,fps={fps_text},format={v['pixel_format']}[v{n}]")
        if clip.info.has_audio:
            chains.append(
                f"[{n}:a]atrim=start={clip.start_s:g}:end={clip.end_s:g},asetpts=PTS-STARTPTS,"
                f"aresample={rate},aformat=channel_layouts={layout}[a{n}]")
        else:                       # 소리가 없는 장면은 같은 길이의 무음으로 채운다
            chains.append(f"anullsrc=r={rate}:cl={layout},atrim=duration={clip.used_s:g}[a{n}]")
        labels += f"[v{n}][a{n}]"
    chains.append(f"{labels}concat=n={len(assembly.clips)}:v=1:a=1[v][a]")
    command += [
        "-filter_complex", ";".join(chains), "-map", "[v]", "-map", "[a]",
        "-c:v", str(v["codec"]), "-crf", str(v["crf"]), "-preset", str(v["preset"]),
        "-c:a", str(a["codec"]), "-b:a", str(a["bitrate"]),
        "-movflags", "+faststart", assembly.output_path,
    ]
    return command


def run(assembly: Assembly, recipe: dict[str, Any]) -> Assembly:
    """FFmpeg 를 실행한다. 실패하면 FFmpeg 가 낸 마지막 줄을 붙여 AssembleError 를 낸다."""
    assembly.command = build_command(assembly, recipe, _tool("ffmpeg"))
    Path(assembly.output_path).parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(assembly.command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-3:])
        raise AssembleError(f"FFmpeg 실패 (종료코드 {result.returncode})\n{tail}")
    return assembly


# ---------------------------------------------------------------- 자막
def _stamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_text(scenes: list[SceneSpec], assembly: Assembly) -> str:
    """장면 사양의 자막 문구를 완성본의 시간에 맞춰 SubRip(.srt) 으로 쓴다.

    잘라 낸 만큼 시간을 당기고, 잘려 나간 구간의 자막은 뺀다. 영상에 입히지 않으므로
    재생기에서 자막 파일로 불러와 본다.
    """
    blocks: list[str] = []
    offset = 0.0
    for scene, clip in zip(scenes, assembly.clips):
        for beat in scene.beats:
            if not beat.caption_ko:
                continue
            start = max(float(beat.start_s), clip.start_s)
            end = min(float(beat.end_s), clip.end_s)
            if end - start <= 0.2:
                continue
            blocks.append(f"{len(blocks) + 1}\n"
                          f"{_stamp(offset + start - clip.start_s)} --> {_stamp(offset + end - clip.start_s)}\n"
                          f"{beat.caption_ko}\n")
        offset += clip.used_s
    return "\n".join(blocks)


# ---------------------------------------------------------------- 검토 기록
REVIEW_ITEMS = [
    ("제품 형태", "병 모양, 뚜껑, 색, 크기가 장면마다 같은가"),
    ("라벨 글자", "라벨의 글자가 읽히는가. 프레임마다 바뀌지 않는가"),
    ("넣지 말라고 한 것", "얼굴, 덧붙은 글자, 배경 음악, 말소리가 생기지 않았는가"),
    ("오디오", "장면마다 소리의 크기와 결이 이어지는가"),
    ("장면 연결", "장면이 바뀔 때 장소, 빛, 색이 이어지는가"),
    ("구간 타이밍", "사양의 구간대로 화면이 바뀌는가. 자막 시간과 맞는가"),
    ("사실", "화면이 제품 바이블의 사실과 어긋나지 않는가 (용량, 제형, 색)"),
]


def review_template(assembly: Assembly) -> str:
    """사람이 초안을 보고 적는 검토 기록의 빈 양식 (4.2절). 8장의 채점 기준이 여기서 나온다."""
    lines = [f"# 초안 검토 기록 — {assembly.episode}", "",
             f"대상: {Path(assembly.output_path).name} ({assembly.total_s:.1f}초). 본 날짜: ____ . 본 사람: ____ .", "",
             "보는 순서: ① 소리를 끄고 처음부터 끝까지 ② 화면을 보지 않고 소리만 ③ 장면이 바뀌는 앞뒤 2초만 되풀이 ④ 제품이 나오는 곳에서 멈춰서.",
             "표시: O 괜찮다 / △ 거슬리지만 쓸 수 있다 / X 못 쓴다. X 와 △ 에는 몇 초인지와 무엇인지를 적는다.", ""]
    head = "| 항목 | 무엇을 보는가 | " + " | ".join(c.scene_id for c in assembly.clips) + " | 메모 |"
    lines += [head, "|---|---|" + "---|" * (len(assembly.clips) + 1)]
    for name, what in REVIEW_ITEMS:
        lines.append(f"| {name} | {what} | " + " | ".join("" for _ in assembly.clips) + " |  |")
    lines += ["", "## 조립할 때 알려 준 것", ""]
    lines += [f"- {note}" for note in assembly.notes + assembly.problems] or ["- 없음"]
    lines += ["", "## 다시 뽑을 장면과 이유", "", "- ", "", "## 2부에서 풀 문제", "", "- ", ""]
    return "\n".join(lines)
