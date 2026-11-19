"""공정 지도 (1.2절). 한 편이 만들어지는 여섯 단계를 configs/workflow.yaml 에서 읽는다."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ass.settings import load_config


class Stage(BaseModel):
    id: str
    name_ko: str
    question_ko: str
    inputs: list[str] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)
    commands: list[str] = Field(min_length=1)
    models: list[str] = []
    guards: list[str] = []
    chapters: str


class Workflow(BaseModel):
    version: str
    stages: list[Stage]
    command_notes: dict[str, str] = {}

    def stage_of(self, command: str) -> Stage | None:
        return next((s for s in self.stages if command in s.commands), None)

    def commands(self) -> list[str]:
        return [c for s in self.stages for c in s.commands]


def load_workflow(config: dict[str, Any] | None = None) -> Workflow:
    return Workflow.model_validate(config or load_config("workflow"))


def check_workflow(workflow: Workflow, models_config: dict[str, Any]) -> list[str]:
    """공정 지도가 스스로 모순되지 않는지 본다. 문제 목록을 돌려준다."""
    problems: list[str] = []
    produced: set[str] = set()
    external = {"아이디어 한 줄", "본인 블로그 글", "본인 영상의 대본", "product_bible", "제품 사진", "자막 문구"}
    for stage in workflow.stages:
        for item in stage.inputs:
            if item not in produced and item not in external:
                problems.append(f"{stage.name_ko}: 입력 '{item}' 을 만드는 앞 단계가 없다")
        produced.update(stage.outputs)
        for model in stage.models:
            if model not in models_config:
                problems.append(f"{stage.name_ko}: models.yaml 에 없는 모델 역할 '{model}'")
    seen: set[str] = set()
    for command in workflow.commands():
        if command in seen:
            problems.append(f"명령 '{command}' 이 두 단계에 있다")
        seen.add(command)
    return problems


def render_text(workflow: Workflow, available: set[str], models_config: dict[str, Any]) -> str:
    """터미널용 공정 지도. available 은 실제로 있는 명령의 집합이다."""
    lines = ["ASS 공정 지도 — 한 편이 만들어지는 여섯 단계", ""]
    for n, stage in enumerate(workflow.stages, 1):
        lines.append(f"{n}. {stage.name_ko} — {stage.question_ko}  ({stage.chapters}장)")
        lines.append(f"   입력  {', '.join(stage.inputs)}")
        lines.append(f"   출력  {', '.join(stage.outputs)}")
        marks = [f"ass {c} [{'있음' if c in available else '없음'}]" for c in stage.commands]
        lines.append(f"   명령  {'  '.join(marks)}")
        if stage.models:
            names = [str(models_config[m]["name"]) for m in stage.models if m in models_config]
            lines.append(f"   모델  {', '.join(names)}")
        if stage.guards:
            lines.append(f"   가드  {', '.join(stage.guards)}")
        lines.append("")
    total = workflow.commands()
    have = [c for c in total if c in available]
    lines.append(f"명령 {len(total)}개 중 {len(have)}개가 있다: {', '.join(have) or '없음'}")
    return "\n".join(lines)


def render_markdown(workflow: Workflow, available: set[str], models_config: dict[str, Any]) -> str:
    """docs/workflow_map.md 의 내용."""
    out = [
        "# ASS 공정 지도",
        "",
        f"`ass map --write` 가 `configs/workflow.yaml`(버전 {workflow.version})에서 만든 파일이다. 손으로 고치지 않는다.",
        "",
        "```",
        "  →  ".join(s.name_ko for s in workflow.stages),
        "```",
        "",
        "| 단계 | 답하는 질문 | 입력 | 출력 | 명령 | 모델 | 가드 | 장 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for n, s in enumerate(workflow.stages, 1):
        commands = "<br>".join(f"`ass {c}` ({'있음' if c in available else '없음'})" for c in s.commands)
        models = ", ".join(str(models_config[m]["name"]) for m in s.models if m in models_config) or "—"
        out.append(
            f"| {n}. {s.name_ko} | {s.question_ko} | {', '.join(s.inputs)} | {', '.join(s.outputs)} "
            f"| {commands} | {models} | {', '.join(s.guards) or '—'} | {s.chapters} |"
        )
    total = workflow.commands()
    have = [c for c in total if c in available]
    out += ["", f"명령 {len(total)}개 중 {len(have)}개가 있다."]
    return "\n".join(out) + "\n"


def render_stack(models_config: dict[str, Any]) -> str:
    """터미널용 기술 스택 표. 확인된 것과 확인되지 않은 것을 나눠 보여 준다."""
    lines = [f"ASS 기술 스택 — 확인일 {models_config['verified_on']}", ""]
    for key, m in models_config.items():
        if not isinstance(m, dict) or "name" not in m:
            continue
        lines.append(f"{m['name']} — {m['role_ko']}  ({m['chapters']}장)")
        lines.append(f"   모델 ID  {m.get('id') or '미확인'}")
        for item in m.get("confirmed", []):
            lines.append(f"   [확인]   {item}")
        for item in m.get("unverified", []):
            lines.append(f"   [미확인] {item}")
        lines.append(f"   근거     {m.get('source', '—')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
