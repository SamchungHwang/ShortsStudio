"""ASS 콘솔 — 여섯 단계를 화면에서 실행한다 (`ass console`).

콘솔은 `python -m ass <명령>` 을 대신 실행하고 그 출력을 보여 준다. 새 기능은 없다.
가드, 예산 상한, 실행 기록은 명령줄과 똑같이 적용된다. 비용이 드는 실행은 추정 비용을 보여 주고 확인을 받는다.
판단 부분은 console_model.py 에 있다.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, simpledialog, ttk

from ass import __version__
from ass import console_model as model
from ass.guards.cost_guard import UnknownPrice
from ass.policy import load_policy
from ass.settings import OUTPUT_DIR, ROOT
from ass.workflow import load_workflow, render_markdown, render_stack

UI_FAMILY = "맑은 고딕"
MONO_FAMILY = "Consolas"
NAVY = "#1F4E79"
GREY = "#666666"
GREEN = "#2E7D32"
RED = "#C62828"
AMBER = "#B26A00"
MAX_LOG_LINES = 1000


class ConsoleApp:
    def __init__(self, root: tk.Tk, available: set[str]) -> None:
        self.root = root
        self.available = available
        self.workflow = load_workflow()
        self.models = load_policy("models").data
        self.process: subprocess.Popen | None = None
        self.pending: list[list[str]] = []
        self.events: queue.Queue = queue.Queue()
        self.stop_requested = False

        root.title("ASS — Shorts 제작 콘솔")
        root.geometry("1320x960")
        root.minsize(1000, 720)
        self.font_size = model.load_font_size()
        self._build_fonts()

        self.episode = tk.StringVar()
        self.scene = tk.StringVar(value=model.ALL_SCENES)
        self.duration = tk.StringVar(value=model.SPEC_DURATION)
        self.stage = tk.StringVar()
        self.command = tk.StringVar()
        self.dry_run = tk.BooleanVar(value=True)
        self.status = tk.StringVar()
        self.summary = tk.StringVar()
        self.hint = tk.StringVar()
        self.notice = tk.StringVar()
        self.run_text = tk.StringVar(value="대기 중")
        self.started_at: float | None = None
        self.log_count = tk.StringVar(value="로그 0줄")
        self.file_rows: list = []
        self.picks: dict[str, str] = {}      # 조립에 쓸 영상: 장면 번호 → 실행. 비어 있으면 가장 최근 것

        self._build_menu()
        self._build_header()
        self._build_work()
        self._build_stages()
        self._build_details()
        self.reload()
        self.root.after(100, self._drain)

    # ---------------------------------------------------------------- 글자 크기
    def _build_fonts(self) -> None:
        """글꼴을 이름 붙은 객체로 만든다. 크기를 바꾸면 그 글꼴을 쓰는 모든 곳이 함께 바뀐다."""
        self.f_ui = tkfont.Font(root=self.root, family=UI_FAMILY, size=10)
        self.f_bold = tkfont.Font(root=self.root, family=UI_FAMILY, size=10, weight="bold")
        self.f_title = tkfont.Font(root=self.root, family=UI_FAMILY, size=18, weight="bold")
        self.f_badge = tkfont.Font(root=self.root, family=UI_FAMILY, size=14, weight="bold")
        self.f_mono = tkfont.Font(root=self.root, family=MONO_FAMILY, size=10)
        self.root.option_add("*Font", self.f_ui)
        self._apply_fonts()

    def _px(self, width: int) -> int:
        """표의 칸 너비를 글자 크기에 맞춰 늘린다. 기준은 10 크기 글자다."""
        return int(width * max(self.font_size, 10) / 10)

    def _apply_fonts(self) -> None:
        sizes = model.font_sizes(self.font_size)
        for font, key in ((self.f_ui, "ui"), (self.f_bold, "ui"), (self.f_title, "title"),
                          (self.f_badge, "badge"), (self.f_mono, "mono")):
            font.configure(size=sizes[key])
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkTooltipFont"):
            try:        # ttk 위젯(표, 단추, 탭, 고르는 칸)은 이 이름 붙은 글꼴을 쓴다
                tkfont.nametofont(name).configure(family=UI_FAMILY, size=sizes["ui"])
            except tk.TclError:
                pass
        style = ttk.Style(self.root)
        style.configure("Treeview", rowheight=sizes["row"], font=self.f_ui)
        style.configure("Treeview.Heading", font=self.f_ui)
        style.configure("TNotebook.Tab", font=self.f_ui, padding=(10, 4))
        self.root.option_add("*TCombobox*Listbox.font", self.f_ui)      # 고르는 칸을 펼친 목록

    def change_font(self, step: int) -> None:
        """글자를 한 단계 키우거나 줄인다. step 이 0 이면 기본 크기로."""
        self.font_size = model.clamp_font_size(self.font_size + step) if step else model.DEFAULT_FONT_SIZE
        self._apply_fonts()
        model.save_font_size(self.font_size)
        self.notice.set(f"글자 크기 {self.font_size}")

    # ---------------------------------------------------------------- 화면
    def _build_menu(self) -> None:
        bar = tk.Menu(self.root)
        work = tk.Menu(bar, tearoff=0)
        work.add_command(label="환경 점검 (ass doctor)", command=self.run_doctor)
        work.add_separator()
        work.add_command(label="제품 바이블 점검 (ass bible)", command=self.run_bible)
        work.add_command(label="레퍼런스 고르기… (ass sheet --select)", command=self.choose_references)
        work.add_separator()
        work.add_command(label="조립에 쓸 영상 고르기… (ass assemble --pick)", command=self.choose_renders)
        work.add_separator()
        work.add_command(label="비용 장부와 오류 기록 만들기 (ass cost)", command=self.run_cost)
        work.add_command(label="실제 청구액 적기… (ass cost --billed)", command=self.record_billed)
        work.add_separator()
        work.add_command(label="공정 지도를 파일로 저장 (docs/workflow_map.md)", command=self.save_map)
        work.add_command(label="다시 읽기", command=self.reload)
        work.add_separator()
        work.add_command(label="끝내기", command=self.close)
        bar.add_cascade(label="작업", menu=work)
        view = tk.Menu(bar, tearoff=0)
        view.add_command(label="글자 크게", accelerator="Ctrl +", command=lambda: self.change_font(1))
        view.add_command(label="글자 작게", accelerator="Ctrl -", command=lambda: self.change_font(-1))
        view.add_command(label="글자 기본 크기", accelerator="Ctrl 0", command=lambda: self.change_font(0))
        view.add_separator()
        view.add_command(label="산출물 폴더 열기", command=self.open_outputs)
        view.add_command(label="저장소 폴더 열기", command=lambda: self._open(ROOT))
        bar.add_cascade(label="보기", menu=view)
        self.root.config(menu=bar)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        for keys, step in ((("<Control-plus>", "<Control-equal>", "<Control-KP_Add>"), 1),
                           (("<Control-minus>", "<Control-KP_Subtract>"), -1), (("<Control-Key-0>",), 0)):
            for key in keys:
                self.root.bind(key, lambda e, s=step: self.change_font(s))

    def _build_header(self) -> None:
        head = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        head.pack(fill="x")
        tk.Label(head, text=" ASS ", bg=NAVY, fg="white", font=self.f_badge,
                 padx=10, pady=6).pack(side="left")
        ttk.Label(head, text="  Shorts 제작 콘솔", font=self.f_title).pack(side="left")
        ttk.Label(head, textvariable=self.notice, foreground=GREY).pack(side="right")
        line = ttk.Frame(self.root, padding=(12, 4, 12, 4))
        line.pack(fill="x")
        ttk.Label(line, textvariable=self.status, font=self.f_bold).pack(side="left")
        ttk.Label(line, text="초안 제작 도구입니다 · 영상 공개는 사람이 승인한 뒤에 합니다",
                  foreground=GREY).pack(side="right")

    def _build_work(self) -> None:
        box = ttk.LabelFrame(self.root, text="소재와 실행", padding=10)
        box.pack(fill="x", padx=12, pady=4)
        for col in (1, 3, 5):
            box.columnconfigure(col, weight=1)

        ttk.Label(box, text="저장소").grid(row=0, column=0, sticky="w", pady=3)
        path = ttk.Entry(box)
        path.insert(0, str(ROOT))
        path.configure(state="readonly")
        path.grid(row=0, column=1, columnspan=5, sticky="ew", padx=6)
        ttk.Button(box, text="다시 읽기", command=self.reload).grid(row=0, column=6, padx=4)

        ttk.Label(box, text="편").grid(row=1, column=0, sticky="w", pady=3)
        self.episode_box = ttk.Combobox(box, textvariable=self.episode, state="readonly", width=22)
        self.episode_box.grid(row=1, column=1, sticky="w", padx=6)
        self.episode_box.bind("<<ComboboxSelected>>", lambda e: self.on_episode())
        ttk.Label(box, text="장면").grid(row=1, column=2, sticky="e")
        self.scene_box = ttk.Combobox(box, textvariable=self.scene, state="readonly", width=10)
        self.scene_box.grid(row=1, column=3, sticky="w", padx=6)
        self.scene_box.bind("<<ComboboxSelected>>", lambda e: self.on_selection())
        ttk.Label(box, text="길이").grid(row=1, column=4, sticky="e")
        self.duration_box = ttk.Combobox(
            box, textvariable=self.duration, state="readonly", width=14,
            values=[model.SPEC_DURATION] + [str(n) for n in range(3, 16)])
        self.duration_box.grid(row=1, column=5, sticky="w", padx=6)
        self.duration_box.bind("<<ComboboxSelected>>", lambda e: self.on_selection())
        ttk.Label(box, textvariable=self.summary, foreground=GREY).grid(
            row=2, column=0, columnspan=7, sticky="w", pady=(0, 6))

        ttk.Label(box, text="단계").grid(row=3, column=0, sticky="w", pady=3)
        self.stage_box = ttk.Combobox(box, textvariable=self.stage, state="readonly", width=22)
        self.stage_box.grid(row=3, column=1, sticky="w", padx=6)
        self.stage_box.bind("<<ComboboxSelected>>", lambda e: self.on_stage())
        ttk.Label(box, text="명령").grid(row=3, column=2, sticky="e")
        self.command_box = ttk.Combobox(box, textvariable=self.command, state="readonly", width=14)
        self.command_box.grid(row=3, column=3, sticky="w", padx=6)
        self.command_box.bind("<<ComboboxSelected>>", lambda e: self.on_selection())
        self.run_button = ttk.Button(box, text="실행", command=self.run)
        self.run_button.grid(row=3, column=4, padx=4)
        self.stop_button = ttk.Button(box, text="멈춤", command=self.stop, state="disabled")
        self.stop_button.grid(row=3, column=5, sticky="w", padx=4)
        # 실행 상태: 글자는 늘 보이고, 움직이는 막대는 실행 중에만 보인다.
        state = ttk.Frame(box)
        state.grid(row=3, column=6, padx=4, sticky="w")
        self.run_label = tk.Label(state, textvariable=self.run_text, font=self.f_bold, fg=GREY,
                                  width=24, anchor="w")
        self.run_label.pack(anchor="w")
        self.progress = ttk.Progressbar(state, mode="indeterminate", length=180)

        ttk.Checkbutton(box, text="호출하지 않고 요청만 확인 (비용 없음)", variable=self.dry_run,
                        command=self.on_selection).grid(row=4, column=1, columnspan=2, sticky="w", padx=6)
        ttk.Label(box, textvariable=self.hint, foreground=GREY, wraplength=720, justify="left").grid(
            row=4, column=3, columnspan=4, sticky="w")

    def _build_stages(self) -> None:
        box = ttk.LabelFrame(self.root, text="여섯 단계", padding=6)
        box.pack(fill="x", padx=12, pady=4)
        columns = ("no", "name", "question", "commands", "models", "guards", "chapters")
        titles = {"no": "", "name": "단계", "question": "답하는 질문", "commands": "명령",
                  "models": "모델", "guards": "가드", "chapters": "장"}
        widths = {"no": 30, "name": 100, "question": 250, "commands": 240, "models": 160, "guards": 260, "chapters": 80}
        self.stage_tree = ttk.Treeview(box, columns=columns, show="headings", height=6, selectmode="browse")
        for col in columns:
            self.stage_tree.heading(col, text=titles[col])
            self.stage_tree.column(col, width=self._px(widths[col]), anchor="center" if col in ("no", "chapters") else "w")
        self.stage_tree.pack(fill="x")
        self.stage_tree.bind("<<TreeviewSelect>>", lambda e: self.on_stage_row())

    def _build_details(self) -> None:
        box = ttk.LabelFrame(self.root, text="자세히", padding=6)
        box.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        self.tabs = ttk.Notebook(box)
        self.tabs.pack(fill="both", expand=True)

        files = ttk.Frame(self.tabs)
        self.tabs.add(files, text="읽고 쓰는 파일")
        self.files_tab = files
        self.files_note = tk.StringVar()
        ttk.Label(files, textvariable=self.files_note, foreground=GREY).pack(side="bottom", anchor="w", pady=4)
        self.files_tree = ttk.Treeview(files, columns=("mark", "kind", "path", "what", "status"),
                                       show="headings", height=8, selectmode="browse")
        for col, title, width, anchor in (
                ("mark", "", 36, "center"), ("kind", "구분", 56, "center"), ("path", "파일", 430, "w"),
                ("what", "여기서 가져오는 것 / 여기에 쓰는 것", 420, "w"), ("status", "고친 때", 170, "w")):
            self.files_tree.heading(col, text=title)
            self.files_tree.column(col, width=self._px(width), anchor=anchor)
        self.files_tree.tag_configure("write", foreground="#1F5FA8")
        self.files_tree.tag_configure("missing", foreground="#B4501E")
        files_scroll = ttk.Scrollbar(files, command=self.files_tree.yview)
        self.files_tree.configure(yscrollcommand=files_scroll.set)
        files_scroll.pack(side="right", fill="y")
        self.files_tree.pack(fill="both", expand=True, side="left")
        self.files_tree.bind("<Double-1>", lambda e: self.open_selected_file())

        self.preview_text = self._text_tab("프롬프트·내레이션")
        out = ttk.Frame(self.tabs)
        self.tabs.add(out, text="산출물")
        self.output_tree = ttk.Treeview(out, columns=("path", "time", "size"), show="headings", height=8)
        for col, title, width in (("path", "파일", 620), ("time", "만든 때", 150), ("size", "크기", 90)):
            self.output_tree.heading(col, text=title)
            self.output_tree.column(col, width=self._px(width), anchor="w" if col == "path" else "center")
        self.output_tree.pack(fill="both", expand=True, side="top")
        self.output_tree.bind("<Double-1>", lambda e: self.open_selected_output())
        bar = ttk.Frame(out)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="폴더 열기", command=self.open_outputs).pack(side="right", padx=2)
        ttk.Button(bar, text="새로 고침", command=self.refresh_outputs).pack(side="right", padx=2)
        ttk.Label(bar, text="두 번 누르면 파일이 열립니다", foreground=GREY).pack(side="left")

        self.stack_text = self._text_tab("기술 스택")

        log = ttk.Frame(self.tabs)
        self.tabs.add(log, text="실행 로그")
        self.log_tab = log
        self.log_text = tk.Text(log, height=10, font=self.f_mono, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(log, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        bar = ttk.Frame(log)
        bar.pack(fill="x", side="bottom", pady=4)
        ttk.Label(bar, textvariable=self.log_count, foreground=GREY).pack(side="left")
        ttk.Button(bar, text="지우기", command=self.clear_log).pack(side="right", padx=2)
        ttk.Button(bar, text="복사", command=self.copy_log).pack(side="right", padx=2)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True, side="left")

    def _text_tab(self, title: str) -> tk.Text:
        frame = ttk.Frame(self.tabs)
        self.tabs.add(frame, text=title)
        text = tk.Text(frame, height=10, font=self.f_mono, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True, side="left")
        return text

    # ---------------------------------------------------------------- 읽기
    def reload(self) -> None:
        """설정 파일과 예제 폴더를 다시 읽는다."""
        self.workflow = load_workflow()
        self.models = load_policy("models").data
        rows = model.stage_rows(self.workflow, self.available, self.models)
        ready = sum(r.ready for r in rows)
        total = sum(r.total for r in rows)
        self.status.set(f"명령 {total}개 중 {ready}개 있음 · 기술 스택 확인일 {self.models['verified_on']} · ASS {__version__}")

        self.stage_tree.delete(*self.stage_tree.get_children())
        for r in rows:
            self.stage_tree.insert("", "end", iid=r.stage_id, values=(
                r.number, r.name, r.question, r.commands, r.models, r.guards, r.chapters))
        names = [f"{r.number}. {r.name}" for r in rows]
        self.stage_box.configure(values=names)
        if self.stage.get() not in names:
            self.stage.set(names[1] if len(names) > 1 else names[0])     # 대본 단계: compile 이 있다

        episodes = model.list_episodes()
        self.episode_box.configure(values=episodes)
        if self.episode.get() not in episodes:
            self.episode.set(episodes[0] if episodes else "")
        self._set_text(self.stack_text, render_stack(self.models))
        self.on_stage()
        self.on_episode()
        self.refresh_outputs()

    def _stage(self):
        index = int(self.stage.get().split(".")[0]) - 1
        return self.workflow.stages[index]

    def on_stage_row(self) -> None:
        selected = self.stage_tree.selection()
        if not selected:
            return
        for n, s in enumerate(self.workflow.stages, 1):
            if s.id == selected[0]:
                self.stage.set(f"{n}. {s.name_ko}")
                self.on_stage()

    def on_stage(self) -> None:
        stage = self._stage()
        self.command_box.configure(values=stage.commands)
        ready = [c for c in stage.commands if c in self.available]
        self.command.set(ready[0] if ready else stage.commands[0])
        self.on_selection()

    def on_episode(self) -> None:
        episode = self.episode.get()
        self.picks = {}                      # 편이 바뀌면 고른 영상도 버린다
        if not episode:
            self.summary.set("examples 폴더에 장면 사양이 없습니다")
            return
        try:
            count = len(model.load_episode(episode))
            choices = [model.ALL_SCENES] + [str(n) for n in range(1, count + 1)]
            self.scene_box.configure(values=choices)
            if self.scene.get() not in choices:
                self.scene.set(model.ALL_SCENES)
            self.summary.set(model.episode_summary(episode))
        except Exception as exc:                       # 장면 사양 파일이 깨졌을 때도 창은 떠 있어야 한다
            self.summary.set(f"장면 사양을 읽지 못했습니다: {exc}")
        self.on_selection()

    def on_selection(self) -> None:
        """선택이 바뀔 때마다 안내문, 실행 버튼, 미리보기를 맞춘다."""
        command = self.command.get()
        note = self.workflow.command_notes.get(command, "")
        runnable = command in self.available and command in model.RUNNABLE
        if command not in self.available:
            self.hint.set(f"ass {command} — 아직 없는 명령입니다. {note}")
        elif not runnable:
            self.hint.set(f"ass {command} — {note}")
        else:
            cost = ""
            if command == "assemble":
                cost = " · 계획만 확인합니다" if self.dry_run.get() else " · 비용 없음"
                if self.picks:
                    cost += " · 직접 고른 영상: " + ", ".join(f"장면 {n}={r}" for n, r in sorted(self.picks.items()))
            if command in ("render", "sheet"):
                try:
                    amount = model.paid_estimate(command, self.episode.get(), self.scene.get(),
                                                 self.duration.get(), self.dry_run.get())
                    cost = f" · 이번 실행 추정 ${amount:.2f}" if amount else " · 요청만 확인합니다"
                except (UnknownPrice, ValueError) as exc:
                    cost = f" · {exc}"
            summary = model.files_summary(self._files(command))
            self.hint.set(f"ass {command} — {note}{cost}" + (f" · {summary}" if summary else ""))
        busy = self.process is not None
        self.run_button.configure(state="normal" if runnable and not busy else "disabled")
        self.refresh_files()
        self.refresh_preview()

    def _files(self, command: str) -> list:
        return model.command_files(command, self.episode.get(), self.scene.get(), picks=self.picks)

    def refresh_files(self) -> None:
        """고른 명령이 읽는 파일과 쓰는 파일을 실행 전에 보여 준다."""
        command = self.command.get()
        self.files_tree.delete(*self.files_tree.get_children())
        try:
            self.file_rows = self._files(command)
        except Exception as exc:
            self.file_rows = []
            self.files_note.set(f"파일 목록을 만들지 못했습니다: {exc}")
            return
        for i, row in enumerate(self.file_rows):
            tag = "write" if row.kind == "씀" else ("missing" if not row.exists and "없어도" not in row.status else "")
            self.files_tree.insert("", "end", iid=str(i), tags=(tag,) if tag else (),
                                   values=(row.mark, row.kind, row.path, row.what, row.status))
        if self.file_rows:
            self.files_note.set(
                f"ass {command} — {model.files_summary(self.file_rows)} · 두 번 누르면 파일이 열립니다 · "
                + ("다른 실행의 영상을 쓰려면 [작업] → 조립에 쓸 영상 고르기" if command == "assemble" else
                   "결과를 바꾸려면 ‘읽음’ 쪽 파일을 고칩니다. ‘씀’ 쪽은 실행할 때마다 다시 써집니다"))
        else:
            self.files_note.set(f"ass {command} — 이 명령이 생기면 여기에 읽고 쓰는 파일이 나옵니다")

    def open_selected_file(self) -> None:
        selected = self.files_tree.selection()
        if not selected:
            return
        row = self.file_rows[int(selected[0])]
        target = ROOT / row.path
        if row.exists:
            self._open(target)
        elif row.kind == "씀":
            folder = target.parent
            folder.mkdir(parents=True, exist_ok=True)
            self._open(folder)
        else:
            messagebox.showwarning("파일이 없습니다", f"{row.path}\n\n이 파일을 먼저 만들어야 합니다.")

    def refresh_preview(self) -> None:
        episode = self.episode.get()
        if not episode:
            return
        try:
            text = model.preview(episode, self.scene.get())
        except Exception as exc:
            text = f"미리보기를 만들지 못했습니다: {exc}"
        self._set_text(self.preview_text, text)

    def refresh_outputs(self) -> None:
        self.output_tree.delete(*self.output_tree.get_children())
        for path, when, size in model.list_outputs():
            self.output_tree.insert("", "end", values=(path, when, size))

    # ---------------------------------------------------------------- 실행
    def run(self) -> None:
        if self.process is not None:
            return
        command, episode = self.command.get(), self.episode.get()
        approved_by = ""
        try:
            if command == "sheet" and any(not p.is_own for p in model.episode_products(episode)):
                approved_by = simpledialog.askstring(
                    "타사 제품 승인",
                    "이 편에는 타사 제품이 나옵니다. 타사 제품의 이미지를 만드는 일은 사람이 승인합니다.\n"
                    "실제 타사 제품이라면 직접 구입해 찍은 사진만 씁니다.\n\n승인하는 사람의 이름을 적으세요.",
                    parent=self.root) or ""
                if not approved_by.strip():
                    return
            runs = model.build_runs(command, episode, self.scene.get(), self.duration.get(), self.dry_run.get(),
                                    picks=self.picks, approved_by=approved_by.strip())
            cost = model.paid_estimate(command, episode, self.scene.get(), self.duration.get(), self.dry_run.get())
        except (UnknownPrice, ValueError) as exc:
            messagebox.showwarning("실행할 수 없습니다", str(exc))
            return
        if cost > 0:
            budget = model.run_budget_usd()
            if cost > budget:
                messagebox.showwarning(
                    "예산 상한을 넘습니다",
                    f"추정 비용 ${cost:.2f} 가 실행 예산 ${budget:.2f} 를 넘습니다.\n"
                    "장면을 하나씩 실행하거나 configs/budget_policy.yaml 의 상한을 확인하세요.")
                return
            if not messagebox.askokcancel(
                    "비용이 드는 실행입니다",
                    (f"{episode} 의 제품 레퍼런스 시트를 실제로 생성합니다.\n\n" if command == "sheet" else
                     f"{episode} · 장면 {self.scene.get()} · 실제로 생성합니다.\n\n") +
                    f"추정 비용 ${cost:.2f} (실행 예산 ${budget:.2f})\n"
                    "추정값이며 실제 청구액은 결제 화면에서 확인해야 합니다.\n\n실행할까요?"):
                return
        reads = [r for r in getattr(self, "file_rows", []) if r.kind == "읽음"]
        if reads:
            self._log(f"읽는 파일 {len(reads)}개:")
            for r in reads:
                self._log(f"  {r.mark} {r.path}" + ("" if r.exists else f"  ← {r.status}"))
        self._begin(runs)

    def run_cost(self) -> None:
        """실행 기록을 모아 비용 장부를 만든다. 호출하지 않으므로 묻지 않고 실행한다."""
        if self.process is not None:
            return
        self._begin(model.build_runs("cost", self.episode.get()))

    def run_bible(self) -> None:
        if self.process is not None:
            return
        self._begin(model.build_runs("bible", self.episode.get()))

    def choose_references(self) -> None:
        """후보 가운데 쓸 레퍼런스를 사람이 고른다. 고른 사람의 이름을 함께 적는다."""
        if self.process is not None:
            return
        episode = self.episode.get()
        try:
            choices = model.sheet_choices(episode)
        except Exception as exc:
            messagebox.showwarning("고를 수 없습니다", str(exc))
            return
        if not any(c.versions for c in choices):
            messagebox.showinfo("고를 후보가 없습니다",
                                "만들어 둔 후보가 없습니다.\n단계 ‘3. 제품 레퍼런스’에서 후보를 먼저 만드세요.")
            return
        keep = "그대로 둔다"
        win = tk.Toplevel(self.root)
        win.title("레퍼런스 고르기")
        win.transient(self.root)
        ttk.Label(win, padding=10, text="후보 이미지를 ‘산출물’ 탭에서 열어 보고, 방향마다 쓸 후보를 고릅니다. "
                                        "‘그대로 둔다’는 지금 골라져 있는 것을 바꾸지 않습니다."
                  ).grid(row=0, column=0, columnspan=3, sticky="w")
        selected: dict[tuple[str, str], tk.StringVar] = {}
        for row, c in enumerate(choices, 1):
            ttk.Label(win, text=c.product_name, padding=(10, 3)).grid(row=row, column=0, sticky="w")
            ttk.Label(win, text=f"{c.view_name} ({c.view_id})", padding=(10, 3)).grid(row=row, column=1, sticky="w")
            now = f" · 지금 {c.current}" if c.current else " · 아직 고르지 않음"
            var = tk.StringVar(value=keep if (c.current or not c.versions) else c.versions[0])
            ttk.Combobox(win, textvariable=var, state="readonly" if c.versions else "disabled", width=14,
                         values=[keep] + c.versions).grid(row=row, column=2, sticky="w", padx=6, pady=3)
            ttk.Label(win, text=now if c.versions else " · 후보 없음", foreground=GREY).grid(row=row, column=3, sticky="w", padx=6)
            selected[(c.product_id, c.view_id)] = var

        def apply() -> None:
            picks = {key: var.get() for key, var in selected.items() if var.get() != keep}
            if not picks:
                win.destroy()
                return
            by = simpledialog.askstring("고른 사람", "고른 사람의 이름을 적으세요. 기록에 남습니다.", parent=win) or ""
            if not by.strip():
                return
            note = simpledialog.askstring("고른 이유", "고른 이유를 한 줄로 적으세요. 비워도 됩니다.", parent=win) or ""
            win.destroy()
            self._begin(model.select_runs(picks, by.strip(), note.strip()))

        bar = ttk.Frame(win, padding=10)
        bar.grid(row=len(choices) + 1, column=0, columnspan=4, sticky="e")
        ttk.Button(bar, text="취소", command=win.destroy).pack(side="right", padx=4)
        ttk.Button(bar, text="기록", command=apply).pack(side="right", padx=4)
        win.grab_set()

    def run_doctor(self) -> None:
        if self.process is not None:
            return
        self._begin(model.build_runs("doctor", self.episode.get()))

    def record_billed(self) -> None:
        """결제 화면에서 본 실제 청구액을 장부에 적는다."""
        if self.process is not None:
            return
        episode = self.episode.get()
        amount = simpledialog.askfloat(
            "실제 청구액 적기",
            f"{episode} 편을 만드는 데 실제로 청구된 금액(USD)을 적습니다.\n"
            "AI Studio 의 Billing 화면에서 생성 전과 후의 잔액 차이를 봅니다.",
            parent=self.root, minvalue=0.0)
        if amount is None:
            return
        note = simpledialog.askstring("메모", "함께 남길 메모 (예: 생성 전 잔액 10.00, 후 6.85). 비워도 됩니다.",
                                      parent=self.root) or ""
        argv = ["cost", "--episode", episode, "--billed", f"{amount:.2f}"]
        self._begin([argv + (["--note", note] if note else [])])

    def choose_renders(self) -> None:
        """장면마다 조립에 쓸 영상을 고른다. 고르지 않으면 가장 최근의 성공한 실행을 쓴다."""
        episode = self.episode.get()
        try:
            choices = model.render_choices(episode)
        except Exception as exc:
            messagebox.showwarning("고를 수 없습니다", str(exc))
            return
        if not any(runs for _, _, runs in choices):
            messagebox.showinfo("고를 영상이 없습니다",
                                "성공한 생성이 아직 없습니다.\n단계 ‘4. 장면 생성’에서 장면을 먼저 생성하세요.")
            return
        latest = "가장 최근 것"
        win = tk.Toplevel(self.root)
        win.title("조립에 쓸 영상 고르기")
        win.transient(self.root)
        ttk.Label(win, text=f"{episode} · 장면마다 쓸 영상을 고릅니다. 고르지 않으면 가장 최근의 성공한 실행을 씁니다.",
                  padding=10).grid(row=0, column=0, columnspan=2, sticky="w")
        selected: dict[str, tuple[tk.StringVar, dict[str, str]]] = {}
        for row, (n, scene_id, runs) in enumerate(choices, 1):
            ttk.Label(win, text=f"장면 {n} · {scene_id}", padding=(10, 4)).grid(row=row, column=0, sticky="w")
            labels = {c.label: c.run_id for c in runs}
            var = tk.StringVar(value=latest)
            for label, run_id in labels.items():
                if self.picks.get(str(n)) == run_id:
                    var.set(label)
            box = ttk.Combobox(win, textvariable=var, state="readonly" if runs else "disabled", width=46,
                               values=[latest] + list(labels))
            box.grid(row=row, column=1, sticky="w", padx=10, pady=4)
            if not runs:
                var.set("성공한 생성이 없습니다")
            selected[str(n)] = (var, labels)

        def apply() -> None:
            self.picks = {n: labels[var.get()] for n, (var, labels) in selected.items() if var.get() in labels}
            win.destroy()
            self.on_selection()

        bar = ttk.Frame(win, padding=10)
        bar.grid(row=len(choices) + 1, column=0, columnspan=2, sticky="e")
        ttk.Button(bar, text="취소", command=win.destroy).pack(side="right", padx=4)
        ttk.Button(bar, text="적용", command=apply).pack(side="right", padx=4)
        win.grab_set()

    def _begin(self, runs: list[list[str]]) -> None:
        self.pending = runs
        self.stop_requested = False
        self.tabs.select(self.log_tab)
        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.started_at = time.monotonic()
        self._show_state("실행 중 · 0초", NAVY)
        self.notice.set("실행 중")
        self.progress.pack(anchor="w", pady=(2, 0))
        self.progress.start(12)
        self._start_next()

    def _start_next(self) -> None:
        argv = self.pending.pop(0)
        self._log(f"$ ass {' '.join(argv)}")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.process = subprocess.Popen(
            [sys.executable, "-m", "ass", *argv], cwd=str(ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", creationflags=flags)
        threading.Thread(target=self._pump, args=(self.process,), daemon=True).start()

    def _pump(self, process: subprocess.Popen) -> None:
        """다른 스레드에서 출력을 읽어 큐에 넣는다. 화면은 _drain 이 고친다."""
        assert process.stdout is not None
        for line in process.stdout:
            self.events.put(("line", line.rstrip("\n")))
        self.events.put(("done", process.wait()))

    def _drain(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "line":
                    self._log(value)
                else:
                    self._finished(int(value))
        except queue.Empty:
            pass
        if self.process is not None and self.started_at is not None:
            self.run_text.set(f"실행 중 · {int(time.monotonic() - self.started_at)}초")
        self.root.after(100, self._drain)

    def _show_state(self, text: str, color: str) -> None:
        self.run_text.set(text)
        self.run_label.configure(fg=color)

    def _finished(self, code: int) -> None:
        self._log(f"[종료코드 {code}]")
        self.process = None
        if code == 0 and self.pending and not self.stop_requested:
            self._start_next()
            return
        if self.pending:
            self._log(f"남은 실행 {len(self.pending)}건은 하지 않았습니다.")
        self.pending = []
        self.progress.stop()
        self.progress.pack_forget()          # 멈춘 막대가 남아 있으면 아직 도는 것처럼 보인다
        self.stop_button.configure(state="disabled")
        elapsed = time.monotonic() - self.started_at if self.started_at is not None else 0.0
        self.started_at = None
        text, color = model.finish_state(code, self.stop_requested)
        self.notice.set(text)
        stamp = f"{time.strftime('%H:%M:%S')} · {elapsed:.1f}초"
        self._show_state(f"{model.finish_mark(code, self.stop_requested)} {text} · {stamp}",
                         {"ok": GREEN, "guard": AMBER, "stop": AMBER, "fail": RED}[color])
        self._log(f"── {text} ({stamp}) ──")
        self.refresh_outputs()
        self.on_selection()

    def stop(self) -> None:
        self.stop_requested = True
        if self.process is not None:
            self._log("멈춤을 요청했습니다. 이미 보낸 호출은 청구될 수 있습니다.")
            self.process.terminate()

    # ---------------------------------------------------------------- 그 밖
    def save_map(self) -> None:
        path = ROOT / "docs" / "workflow_map.md"
        path.write_text(render_markdown(self.workflow, self.available, self.models), encoding="utf-8")
        self.notice.set(f"저장했습니다: {path.name}")

    def open_outputs(self) -> None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self._open(OUTPUT_DIR)

    def open_selected_output(self) -> None:
        selected = self.output_tree.selection()
        if selected:
            self._open(OUTPUT_DIR / self.output_tree.item(selected[0], "values")[0])

    def _open(self, path) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showwarning("열 수 없습니다", str(exc))

    def _log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > MAX_LOG_LINES:
            self.log_text.delete("1.0", f"{lines - MAX_LOG_LINES}.0")
            lines = MAX_LOG_LINES
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.log_count.set(f"로그 {max(0, lines - 1)}줄")

    def copy_log(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_text.get("1.0", "end-1c"))
        self.notice.set("로그를 복사했습니다")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.log_count.set("로그 0줄")

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def close(self) -> None:
        if self.process is not None:
            if not messagebox.askokcancel("실행 중입니다", "실행 중인 명령을 멈추고 끝낼까요?"):
                return
            self.process.terminate()
        self.root.destroy()


def main(available: set[str]) -> int:
    root = tk.Tk()
    ConsoleApp(root, available)
    root.mainloop()
    return 0
