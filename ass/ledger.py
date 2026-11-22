"""비용 장부 (4.3절). 실행 기록(api_run.json)을 모아 cost_ledger.csv 와 error_log.md 를 만든다.

장부의 금액은 추정값(초 × 초당 단가)이다. 실제 청구액은 결제 화면에서 보고 `ass cost --billed` 로 적는다.
실패한 호출이 청구되는지는 확인하지 못했다(실험 E04). 그래서 성공한 호출과 실패한 호출을 따로 더한다.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

COLUMNS = ["run_id", "created_at", "episode", "scene_id", "purpose", "model", "duration_s", "resolution",
           "status", "attempts", "elapsed_s", "estimated_cost_usd", "billed_cost_usd", "error", "record"]


class LedgerRow(BaseModel):
    run_id: str
    created_at: str = ""
    episode: str = ""
    scene_id: str = ""
    purpose: str = ""
    model: str = ""
    duration_s: float | None = None
    resolution: str = ""
    status: str = ""
    attempts: int = 0
    elapsed_s: float | None = None
    estimated_cost_usd: float = 0.0
    billed_cost_usd: float | None = None
    error: str = ""
    notes: str = ""
    reused_from: str = ""             # 다른 프로젝트에서 가져온 영상이면 그 출처. 여기서는 돈이 들지 않았다
    original_cost_usd: float = 0.0
    record: str = ""                  # 실행 기록 파일 (outputs 기준 경로)

    @property
    def calls(self) -> int:
        """실제로 호출한 횟수. 예전 기록에는 attempts 가 없어 상태로 미룬다."""
        if self.status == "dry_run" or self.reused_from:
            return 0
        return max(self.attempts, 1)

    @property
    def charged_estimate_usd(self) -> float:
        """시도한 횟수만큼 곱한 추정 비용."""
        return round(self.estimated_cost_usd * self.calls, 4)


def _seconds(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).rstrip("s"))
    except ValueError:
        return None


def row_from_record(doc: dict[str, Any], record_path: Path, output_dir: Path) -> LedgerRow:
    request = doc.get("request") or {}
    fmt = request.get("response_format") or {}
    episode = doc.get("episode") or record_path.parent.name
    try:
        rel = record_path.relative_to(output_dir).as_posix()
    except ValueError:
        rel = record_path.as_posix()
    return LedgerRow(
        run_id=str(doc.get("run_id", "")), created_at=str(doc.get("created_at", "")),
        episode=str(episode), scene_id=str(doc.get("scene_id") or ""),
        purpose=str(doc.get("purpose", "")), model=str(doc.get("model", "")),
        duration_s=_seconds(fmt.get("duration")), resolution=str(fmt.get("resolution") or fmt.get("image_size") or ""),
        status=str(doc.get("status", "")), attempts=int(doc.get("attempts") or 0),
        elapsed_s=doc.get("elapsed_s"), estimated_cost_usd=float(doc.get("estimated_cost_usd") or 0.0),
        billed_cost_usd=doc.get("billed_cost_usd"), error=str(doc.get("error") or ""),
        notes=str(doc.get("notes") or ""), record=rel, reused_from=str(doc.get("reused_from") or ""),
        original_cost_usd=float(doc.get("original_cost_usd") or 0.0),
    )


def collect(output_dir: Path, episode: str | None = None) -> list[LedgerRow]:
    """outputs 아래의 실행 기록을 모두 읽어 시간 순으로 돌려준다. 읽지 못한 파일은 건너뛴다."""
    rows: list[LedgerRow] = []
    for path in sorted(output_dir.rglob("*.api_run.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        row = row_from_record(doc, path, output_dir)
        if episode is None or row.episode == episode:
            rows.append(row)
    rows.sort(key=lambda r: (r.created_at, r.run_id))
    return rows


class Summary(BaseModel):
    ok_calls: int = 0
    ok_usd: float = 0.0                # 성공한 호출의 추정 비용
    failed_calls: int = 0              # 실패로 끝난 호출 + 다시 시도하기 전에 실패한 시도
    failed_usd: float = 0.0            # 그 추정 비용. 청구 여부는 확인하지 못했다
    dry_runs: int = 0
    reused: int = 0                    # 다른 프로젝트에서 가져온 영상. 호출하지 않았다
    reused_saved_usd: float = 0.0      # 가져와서 아낀 추정 비용
    ok_seconds: float = 0.0            # 성공한 호출이 만든 영상 길이의 합
    elapsed_s: float = 0.0             # 성공한 호출의 처리 시간 합

    @property
    def worst_case_usd(self) -> float:
        return round(self.ok_usd + self.failed_usd, 4)


def summarize(rows: list[LedgerRow]) -> Summary:
    s = Summary()
    for r in rows:
        if r.status == "dry_run":
            s.dry_runs += 1
        elif r.reused_from:
            s.reused += 1
            s.reused_saved_usd = round(s.reused_saved_usd + r.original_cost_usd, 4)
        elif r.status == "ok":
            s.ok_calls += 1
            s.ok_usd += r.estimated_cost_usd
            s.ok_seconds += r.duration_s or 0.0
            s.elapsed_s += r.elapsed_s or 0.0
            s.failed_calls += r.calls - 1                       # 성공하기 전에 실패한 시도
            s.failed_usd += r.estimated_cost_usd * (r.calls - 1)
        else:
            s.failed_calls += r.calls
            s.failed_usd += r.charged_estimate_usd
    s.ok_usd, s.failed_usd = round(s.ok_usd, 4), round(s.failed_usd, 4)
    s.ok_seconds, s.elapsed_s = round(s.ok_seconds, 1), round(s.elapsed_s, 1)
    return s


def write_csv(rows: list[LedgerRow], path: Path) -> Path:
    """Excel 에서 한글이 깨지지 않게 BOM 을 붙여 쓴다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for r in rows:
            data = r.model_dump()
            writer.writerow({k: ("" if data[k] is None else data[k]) for k in COLUMNS})
    return path


def error_log_markdown(rows: list[LedgerRow], generated_at: str | None = None) -> str:
    """실패한 호출을 모은다. '자주 나는 오류' 상자와 부록 A 의 재료다."""
    failed = [r for r in rows if r.status == "error"]
    when = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["# 오류 기록", "",
             f"`ass cost` 가 실행 기록에서 모았다. 만든 때: {when}. 실패한 호출 {len(failed)}건.", ""]
    if not failed:
        lines.append("실패한 호출이 없다.")
        return "\n".join(lines) + "\n"
    kinds: dict[str, int] = {}
    for r in failed:
        key = r.error.split(":", 1)[0] if r.error else "알 수 없음"
        kinds[key] = kinds.get(key, 0) + 1
    lines += ["| 오류 종류 | 건수 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(kinds.items())] + [""]
    for r in failed:
        lines += [f"## {r.run_id} · {r.episode} {r.scene_id}".rstrip(), "",
                  f"- 요청: {r.model}, {r.duration_s:g}초, {r.resolution}" if r.duration_s else f"- 요청: {r.model}",
                  f"- 시도 횟수: {r.calls}",
                  f"- 추정 비용: ${r.charged_estimate_usd:.2f} (청구 여부는 결제 화면에서 확인한다)",
                  f"- 오류: {r.error}"]
        if r.notes:
            lines.append(f"- 조치: {r.notes}")
        lines += [f"- 기록: {r.record}", ""]
    return "\n".join(lines) + "\n"


def append_billing_check(path: Path, episode: str, estimated_usd: float, billed_usd: float,
                         note: str = "", checked_at: str | None = None) -> dict[str, Any]:
    """결제 화면에서 본 실제 청구액을 적어 둔다. 추정과의 차이가 4장의 실측값이다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "checked_at": checked_at or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "episode": episode, "estimated_usd": round(estimated_usd, 4), "billed_usd": round(billed_usd, 4),
        "diff_usd": round(billed_usd - estimated_usd, 4), "note": note,
    }
    new = not path.is_file()
    with open(path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        if new:
            writer.writeheader()
        writer.writerow(row)
    return row
