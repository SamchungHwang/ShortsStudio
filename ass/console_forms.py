"""콘솔의 입력 화면 (3장). 제품, 소재 요약, 장면을 칸에 적어 프로젝트의 파일로 만든다.

화면은 값을 모아 ass/authoring.py 에 넘길 뿐이다. 무엇이 파일로 가는지, 무엇이 막히는지는 거기서 정한다.
그래서 화면 없이도 같은 파일을 만들 수 있고(명령, 6장의 초안 생성), 화면은 얇게 남는다.

  ProjectDialog   새 프로젝트를 만들거나 다른 프로젝트로 바꾼다
  ProductForm     제품 등록 → product_bible.yaml
  BriefForm       소재 입력 → source_briefs/<편>.yaml
  SceneForm       장면 작성 → episodes/<편>/scene_0N_<역할>.yaml
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from ass import authoring, settings
from ass.authoring import InputError
from ass.policy import load_policy

GREY = "#666666"
PAD = {"padx": 6, "pady": 3}


class TextField:
    """여러 줄을 적는 칸. get/set 으로만 다룬다."""

    def __init__(self, parent: Any, height: int, width: int = 80) -> None:
        self.widget = tk.Text(parent, height=height, width=width, wrap="word", undo=True)

    def get(self) -> str:
        return str(self.widget.get("1.0", "end-1c"))

    def set(self, value: str) -> None:
        self.widget.delete("1.0", "end")
        self.widget.insert("1.0", value or "")


def need_project(app: Any) -> bool:
    """입력은 내 프로젝트에만 한다. 견본을 보고 있으면 프로젝트부터 만들게 한다."""
    if settings.PROJECT != settings.SAMPLE_NAME:
        return True
    if messagebox.askokcancel(
            "내 프로젝트가 필요합니다",
            "지금은 책의 견본(moalab_skincare)을 보고 있습니다. 견본은 고치지 않습니다.\n\n"
            "내용을 입력하려면 내 프로젝트를 먼저 만듭니다. 지금 만들까요?"):
        ProjectDialog(app).create()
    return False


# ---------------------------------------------------------------- 프로젝트
class ProjectDialog:
    def __init__(self, app: Any) -> None:
        self.app = app

    def create(self) -> None:
        name = simpledialog.askstring(
            "새 프로젝트",
            "프로젝트 이름을 적습니다. 폴더 이름이 됩니다.\n영문 소문자, 숫자, 밑줄만 씁니다. 예: my_first, moa_shop",
            parent=self.app.root)
        if not name:
            return
        try:
            folder = authoring.init_project(name.strip())
        except InputError as exc:
            messagebox.showwarning("만들 수 없습니다", str(exc))
            return
        settings.write_prefs({"project": name.strip()})
        messagebox.showinfo("프로젝트를 만들었습니다",
                            f"{folder}\n\n콘솔을 이 프로젝트로 다시 엽니다.\n다음은 [입력] → 제품 등록입니다.")
        self.app.restart(name.strip())

    def switch(self) -> None:
        names = [settings.SAMPLE_NAME] + settings.list_projects()
        win = tk.Toplevel(self.app.root)
        win.title("프로젝트 바꾸기")
        win.transient(self.app.root)
        ttk.Label(win, padding=10, text="작업할 프로젝트를 고릅니다. sample 은 책의 견본입니다(고치지 않습니다)."
                  ).grid(row=0, column=0, columnspan=2, sticky="w")
        var = tk.StringVar(value=settings.PROJECT)
        ttk.Combobox(win, textvariable=var, values=names, state="readonly", width=30).grid(row=1, column=0, **PAD)

        def apply() -> None:
            name = var.get()
            win.destroy()
            if name != settings.PROJECT:
                settings.write_prefs({"project": name})
                self.app.restart(name)

        ttk.Button(win, text="바꾸기", command=apply).grid(row=1, column=1, **PAD)
        ttk.Button(win, text="취소", command=win.destroy).grid(row=1, column=2, **PAD)
        win.grab_set()


# ---------------------------------------------------------------- 제품
class ProductForm:
    """제품 등록. 저장하면 product_bible.yaml 의 그 제품이 바뀐다."""

    ENTRIES = [("brand", "브랜드", 30), ("name_ko", "제품 이름 (우리말)", 40), ("name_en", "제품 이름 (영어)", 40),
               ("appearance_ko", "외형 (우리말)", 80), ("label_text", "라벨에 적힌 글자", 30)]

    def __init__(self, app: Any) -> None:
        self.app = app
        self.project_dir = settings.PROJECT_DIR
        self.product_id = tk.StringVar()
        self.is_own = tk.BooleanVar(value=True)
        self.sample = tk.StringVar(value=authoring.SAMPLE_PRODUCT)
        self.vars: dict[str, Any] = {key: tk.StringVar() for key, _, _ in self.ENTRIES}
        self.texts: dict[str, TextField] = {}
        self.win: Any = None

    def open(self) -> None:
        win = self.win = tk.Toplevel(self.app.root)
        win.title(f"제품 등록 — {settings.PROJECT}")
        win.transient(self.app.root)
        body = ttk.Frame(win, padding=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(body, text="제품 id").grid(row=row, column=0, sticky="w", **PAD)
        top = ttk.Frame(body)
        top.grid(row=row, column=1, sticky="w")
        ids = ttk.Combobox(top, textvariable=self.product_id, values=authoring.product_ids(self.project_dir), width=28)
        ids.pack(side="left", **PAD)
        ids.bind("<<ComboboxSelected>>", lambda e: self.load())
        ttk.Label(top, text="영문 소문자, 숫자, 밑줄. 예: moalab_aqua_serum", foreground=GREY).pack(side="left")
        row += 1
        ttk.Label(body, text="견본").grid(row=row, column=0, sticky="w", **PAD)
        sample = ttk.Frame(body)
        sample.grid(row=row, column=1, sticky="w")
        ttk.Combobox(sample, textvariable=self.sample, values=authoring.sample_product_ids(), state="readonly",
                     width=28).pack(side="left", **PAD)
        ttk.Button(sample, text="견본으로 채우기", command=self.fill_sample).pack(side="left", **PAD)
        ttk.Label(sample, text="책의 모아랩 제품 값이 칸에 들어갑니다", foreground=GREY).pack(side="left")

        for key, label, width in self.ENTRIES:
            row += 1
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", **PAD)
            ttk.Entry(body, textvariable=self.vars[key], width=width).grid(row=row, column=1, sticky="w", **PAD)
        row += 1
        ttk.Checkbutton(body, text="자사 제품이다 (표시를 끄면 타사 제품: 이 제품이 나오는 장면은 사람이 승인한다)",
                        variable=self.is_own).grid(row=row, column=1, sticky="w", **PAD)

        blocks = [
            ("appearance_en", "외형 (영어)", 2,
             "눈에 보이는 것만: 용기, 크기, 재질과 색, 뚜껑, 라벨 글자. 모든 장면 프롬프트에 그대로 들어갑니다"),
            ("facts", "사실", 5, "한 줄에 하나:  사실 id | 말해도 되는 사실 | 출처"),
            ("say", "써도 되는 표현", 3, "한 줄에 하나:  표현 | 근거가 되는 사실 id (쉼표로 여럿)"),
            ("dont_say", "쓰지 않는 표현", 3, "한 줄에 하나:  표현 | 쓰지 않는 이유"),
        ]
        for key, label, height, hint in blocks:
            row += 1
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="nw", **PAD)
            cell = ttk.Frame(body)
            cell.grid(row=row, column=1, sticky="ew")
            ttk.Label(cell, text=hint, foreground=GREY).pack(anchor="w", padx=6)
            self.texts[key] = TextField(cell, height)
            self.texts[key].widget.pack(fill="x", padx=6, pady=2)

        bar = ttk.Frame(win, padding=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="닫기", command=win.destroy).pack(side="right", padx=4)
        ttk.Button(bar, text="저장하고 점검", command=lambda: self.save(check=True)).pack(side="right", padx=4)
        ttk.Button(bar, text="저장", command=self.save).pack(side="right", padx=4)
        ttk.Button(bar, text="사진 넣기…", command=self.add_photos).pack(side="left", padx=4)
        ttk.Label(bar, text="저장하면 product_bible.yaml 에 적습니다", foreground=GREY).pack(side="left", padx=8)

    def show(self, product_id: str, doc: dict[str, Any]) -> None:
        self.product_id.set(product_id)
        for key, _, _ in self.ENTRIES:
            self.vars[key].set(str(doc.get(key, "") or ""))
        self.is_own.set(bool(doc.get("is_own", True)))
        self.texts["appearance_en"].set(str(doc.get("appearance_en", "")))
        self.texts["facts"].set(authoring.format_facts(doc.get("facts", [])))
        self.texts["say"].set(authoring.format_say(doc.get("say", [])))
        self.texts["dont_say"].set(authoring.format_dont_say(doc.get("dont_say", [])))

    def load(self) -> None:
        doc = authoring.product_doc(self.project_dir, self.product_id.get().strip())
        if doc is not None:
            self.show(self.product_id.get().strip(), doc)

    def fill_sample(self) -> None:
        self.show(self.sample.get(), authoring.sample_product(self.sample.get()))

    def collect(self) -> dict[str, Any]:
        data: dict[str, Any] = {key: self.vars[key].get().strip() for key, _, _ in self.ENTRIES}
        data["appearance_en"] = " ".join(self.texts["appearance_en"].get().split())
        data["is_own"] = bool(self.is_own.get())
        data["facts"] = authoring.parse_facts(self.texts["facts"].get())
        data["say"] = authoring.parse_say(self.texts["say"].get())
        data["dont_say"] = authoring.parse_dont_say(self.texts["dont_say"].get())
        return data

    def save(self, check: bool = False) -> bool:
        try:
            product = authoring.save_product(self.project_dir, self.product_id.get(), self.collect())
        except InputError as exc:
            messagebox.showwarning("저장하지 않았습니다", str(exc), parent=self.win)
            return False
        self.app.reload()
        if check:
            self.win.destroy()
            self.app.run_bible()
        else:
            messagebox.showinfo("저장했습니다", f"{product.name_ko} ({product.id})\n{self.project_dir / 'product_bible.yaml'}",
                                parent=self.win)
        return True

    def add_photos(self) -> None:
        product_id = self.product_id.get().strip()
        if authoring.product_doc(self.project_dir, product_id) is None:
            messagebox.showinfo("먼저 저장합니다", "제품을 저장한 뒤에 사진을 넣습니다.", parent=self.win)
            return
        paths = filedialog.askopenfilenames(
            parent=self.win, title="본인이 찍은 제품 사진을 고릅니다",
            filetypes=[("사진", "*.jpg *.jpeg *.png *.webp")])
        if not paths:
            return
        try:
            copied = authoring.add_photos(self.project_dir, product_id, list(paths))
        except InputError as exc:
            messagebox.showwarning("넣지 않았습니다", str(exc), parent=self.win)
            return
        messagebox.showinfo("사진을 넣었습니다",
                            f"{len(copied)}장을 복사했습니다.\n{copied[0].parent}\n\n"
                            "본인이 찍었거나 쓸 권리가 있는 사진만 넣습니다.", parent=self.win)


# ---------------------------------------------------------------- 소재 요약
class BriefForm:
    """소재 입력. 저장하면 source_briefs/<편>.yaml 이 된다."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.project_dir = settings.PROJECT_DIR
        self.formats = {v["name_ko"]: k for k, v in load_policy("production_spec").data["formats"].items()}
        self.kinds = {v: k for k, v in authoring.SOURCE_TYPES.items()}
        self.episode = tk.StringVar(value=authoring.SAMPLE_EPISODE)
        self.format = tk.StringVar(value=next(iter(self.formats)))
        self.kind = tk.StringVar(value=authoring.SOURCE_TYPES["idea"])
        self.origin, self.title, self.promise, self.products = (tk.StringVar() for _ in range(4))
        self.owner = tk.BooleanVar(value=False)
        self.owner_hint = tk.StringVar()
        self.points = [(tk.StringVar(), tk.StringVar()) for _ in range(3)]
        self.source: TextField | None = None
        self.win: Any = None

    def open(self) -> None:
        win = self.win = tk.Toplevel(self.app.root)
        win.title(f"소재 입력 — {settings.PROJECT}")
        win.transient(self.app.root)
        body = ttk.Frame(win, padding=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        def line(row: int, label: str) -> Any:
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", **PAD)
            cell = ttk.Frame(body)
            cell.grid(row=row, column=1, sticky="w")
            return cell

        cell = line(0, "편 이름")
        box = ttk.Combobox(cell, textvariable=self.episode, values=authoring.episode_ids(self.project_dir), width=24)
        box.pack(side="left", **PAD)
        box.bind("<<ComboboxSelected>>", lambda e: self.load())
        ttk.Label(cell, text="폴더 이름이 됩니다. 영문 소문자, 숫자, 밑줄. 책을 따라 할 때는 product_intro",
                  foreground=GREY).pack(side="left")
        cell = line(1, "형식")
        ttk.Combobox(cell, textvariable=self.format, values=list(self.formats), state="readonly", width=14).pack(side="left", **PAD)
        ttk.Button(cell, text="견본으로 채우기", command=self.fill_sample).pack(side="left", **PAD)
        ttk.Label(cell, text="책의 수분 세럼 편 값이 칸에 들어갑니다", foreground=GREY).pack(side="left")
        cell = line(2, "소재의 종류")
        ttk.Combobox(cell, textvariable=self.kind, values=list(self.kinds), state="readonly", width=20).pack(side="left", **PAD)
        ttk.Label(cell, text="출처").pack(side="left")
        ttk.Entry(cell, textvariable=self.origin, width=46).pack(side="left", **PAD)
        ttk.Label(cell, text="블로그 글이나 영상이면 주소", foreground=GREY).pack(side="left")
        cell = line(3, "")
        ttk.Checkbutton(cell, text="내가 쓴 것이거나 쓸 권리가 있는 소재다 (표시가 없으면 저장하지 않습니다)",
                        variable=self.owner, command=lambda: self.owner_hint.set("")).pack(side="left", **PAD)
        tk.Label(cell, textvariable=self.owner_hint, fg="#C62828").pack(side="left")
        cell = line(4, "제목")
        ttk.Entry(cell, textvariable=self.title, width=70).pack(side="left", **PAD)
        cell = line(5, "시청자에게 하는 약속")
        ttk.Entry(cell, textvariable=self.promise, width=70).pack(side="left", **PAD)
        ttk.Label(cell, text="하나만", foreground=GREY).pack(side="left")
        cell = line(6, "나오는 제품")
        ttk.Entry(cell, textvariable=self.products, width=50).pack(side="left", **PAD)
        known = ", ".join(authoring.product_ids(self.project_dir)) or "등록한 제품이 없습니다. 먼저 제품 등록"
        ttk.Label(cell, text=f"제품 id (쉼표로 여럿). 등록된 것: {known}", foreground=GREY).pack(side="left")
        for n, (text, evidence) in enumerate(self.points, 1):
            cell = line(6 + n, f"요점 {n}")
            ttk.Entry(cell, textvariable=text, width=56).pack(side="left", **PAD)
            ttk.Label(cell, text="근거").pack(side="left")
            ttk.Entry(cell, textvariable=evidence, width=30).pack(side="left", **PAD)
            if n == 1:
                ttk.Label(cell, text="사실 id (쉼표로 여럿)", foreground=GREY).pack(side="left")
        ttk.Label(body, text="원문").grid(row=10, column=0, sticky="nw", **PAD)
        cell = ttk.Frame(body)
        cell.grid(row=10, column=1, sticky="ew")
        head = ttk.Frame(cell)
        head.pack(fill="x")
        ttk.Label(head, text="블로그 글이나 대본을 붙여 넣습니다. 비워도 됩니다. 6장에서 초안을 만들 때 씁니다",
                  foreground=GREY).pack(side="left", padx=6)
        ttk.Button(head, text="파일에서 불러오기…", command=self.load_source_file).pack(side="right", padx=6)
        self.source = TextField(cell, 7)
        self.source.widget.pack(fill="both", expand=True, padx=6, pady=2)

        bar = ttk.Frame(win, padding=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="닫기", command=win.destroy).pack(side="right", padx=4)
        ttk.Button(bar, text="저장하고 장면 작성으로", command=lambda: self.save(next_step=True)).pack(side="right", padx=4)
        ttk.Button(bar, text="저장", command=self.save).pack(side="right", padx=4)
        ttk.Label(bar, text="저장하면 source_briefs/<편 이름>.yaml 에 적습니다", foreground=GREY).pack(side="left", padx=8)

    def show(self, doc: dict[str, Any]) -> None:
        names = {v: k for k, v in self.formats.items()}
        self.format.set(names.get(doc.get("format", ""), self.format.get()))
        self.kind.set(authoring.SOURCE_TYPES.get(doc.get("source_type", "idea"), self.kind.get()))
        self.origin.set(doc.get("origin") or "")
        self.owner.set(bool(doc.get("owner_confirmed", False)))
        self.title.set(doc.get("title_ko", ""))
        self.promise.set(doc.get("promise_ko", ""))
        self.products.set(", ".join(doc.get("products", [])))
        points = doc.get("key_points", [])
        for n, (text, evidence) in enumerate(self.points):
            point = points[n] if n < len(points) else {}
            text.set(point.get("text_ko", ""))
            evidence.set(", ".join(point.get("evidence", [])))

    def load(self) -> None:
        doc = authoring.brief_doc(self.project_dir, self.episode.get().strip())
        if doc is not None:
            self.show(doc)
            source = self.project_dir / "sources" / f"{self.episode.get().strip()}.txt"
            if self.source is not None and source.is_file():
                self.source.set(source.read_text(encoding="utf-8"))

    def fill_sample(self) -> None:
        doc = authoring.sample_brief(self.episode.get().strip() or authoring.SAMPLE_EPISODE)
        doc["owner_confirmed"] = False          # 이 표시는 사람이 직접 한다. 견본이 대신 하지 않는다
        self.show(doc)
        self.owner_hint.set("← 이 칸은 견본이 채우지 않습니다. 직접 눌러 표시하세요")

    def load_source_file(self) -> None:
        path = filedialog.askopenfilename(parent=self.win, title="내가 쓴 글이나 대본 파일을 고릅니다",
                                          filetypes=[("글", "*.txt *.md"), ("모든 파일", "*.*")])
        if not path or self.source is None:
            return
        try:
            self.source.set(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            messagebox.showwarning("읽지 못했습니다", f"UTF-8 글 파일만 읽습니다.\n{exc}", parent=self.win)
            return
        if not self.origin.get().strip():
            self.origin.set(str(path))

    def collect(self) -> dict[str, Any]:
        return {
            "source_type": self.kinds[self.kind.get()], "origin": self.origin.get().strip(),
            "owner_confirmed": bool(self.owner.get()), "format": self.formats[self.format.get()],
            "title_ko": self.title.get().strip(), "promise_ko": self.promise.get().strip(),
            "products": authoring.split_ids(self.products.get()),
            "key_points": [{"text_ko": t.get().strip(), "evidence": authoring.split_ids(e.get())} for t, e in self.points],
        }

    def save(self, next_step: bool = False) -> bool:
        episode = self.episode.get().strip()
        if not self.owner.get():            # 가장 자주 빠뜨리는 칸이다. 무엇을 하면 되는지를 말해 준다
            messagebox.showwarning(
                "표시할 칸이 하나 남았습니다",
                "“내가 쓴 것이거나 쓸 권리가 있는 소재다”에 표시가 없습니다.\n\n"
                "소재의 종류 아래에 있는 네모 칸을 눌러 표시한 뒤 다시 저장하세요.\n"
                "이 칸은 [견본으로 채우기]가 채우지 않습니다. 소재가 내 것인지는 사람이 직접 확인합니다.",
                parent=self.win)
            return False
        try:
            brief = authoring.save_brief(self.project_dir, episode, self.collect(),
                                         self.source.get() if self.source is not None else "")
        except InputError as exc:
            messagebox.showwarning("저장하지 않았습니다", str(exc), parent=self.win)
            return False
        self.app.reload()
        if next_step:
            self.win.destroy()
            form = SceneForm(self.app)
            form.episode.set(episode)
            form.open()
        else:
            messagebox.showinfo("저장했습니다", f"{brief.title_ko}\n{self.project_dir / 'source_briefs' / (episode + '.yaml')}",
                                parent=self.win)
        return True


# ---------------------------------------------------------------- 장면
class SceneForm:
    """장면 작성. 한 번에 장면 하나. 저장하면 episodes/<편>/scene_0N_<역할>.yaml 이 된다."""

    BEAT_ROWS = [("visual_ko", "화면 (우리말)"), ("visual_en", "화면 (영어)"), ("camera_en", "카메라 (영어)"),
                 ("narration_ko", "내레이션")]

    def __init__(self, app: Any) -> None:
        self.app = app
        self.project_dir = settings.PROJECT_DIR
        self.spec = load_policy("production_spec").data
        self.episode = tk.StringVar(value=(authoring.episode_ids(self.project_dir) or [authoring.SAMPLE_EPISODE])[0])
        self.number = tk.StringVar(value="1")
        self.role = tk.StringVar()
        self.scene_id, self.duration, self.products, self.setting, self.audio = (tk.StringVar() for _ in range(5))
        self.beats = [{key: tk.StringVar() for key in
                       ("start_s", "end_s", "visual_ko", "visual_en", "camera_en", "narration_ko", "caption_ko", "evidence")}
                      for _ in range(3)]
        self.facts = tk.StringVar()
        self.progress = tk.StringVar()
        self.format = ""
        self._role = ""
        self.next_button: Any = None
        self.win: Any = None

    def open(self) -> None:
        if not authoring.episode_ids(self.project_dir):
            messagebox.showinfo("먼저 소재를 입력합니다",
                                "편이 아직 없습니다. [입력] → ② 소재 입력에서 편 이름과 형식을 먼저 정합니다.")
            return
        win = self.win = tk.Toplevel(self.app.root)
        win.title(f"장면 작성 — {settings.PROJECT}")
        win.transient(self.app.root)
        body = ttk.Frame(win, padding=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        top = ttk.Frame(body)
        top.grid(row=0, column=0, sticky="w")
        ttk.Label(top, text="편").pack(side="left", **PAD)
        box = ttk.Combobox(top, textvariable=self.episode, values=authoring.episode_ids(self.project_dir),
                           state="readonly", width=22)
        box.pack(side="left", **PAD)
        box.bind("<<ComboboxSelected>>", lambda e: self.load())
        ttk.Label(top, text="장면").pack(side="left", **PAD)
        number = ttk.Combobox(top, textvariable=self.number, values=["1", "2", "3"], state="readonly", width=4)
        number.pack(side="left", **PAD)
        number.bind("<<ComboboxSelected>>", lambda e: self.load())
        ttk.Label(top, textvariable=self.role, foreground=GREY).pack(side="left", **PAD)
        ttk.Button(top, text="견본으로 채우기", command=self.fill_sample).pack(side="left", padx=12)
        ttk.Label(top, text="지금 보이는 장면 하나만 채웁니다", foreground=GREY).pack(side="left")
        tk.Label(body, textvariable=self.progress, fg="#1F3A5F", anchor="w").grid(row=9, column=0, sticky="w", padx=6, pady=(6, 0))

        head = ttk.Frame(body)
        head.grid(row=1, column=0, sticky="w")
        for label, var, width in (("장면 id", self.scene_id, 18), ("길이(초)", self.duration, 4),
                                  ("제품 id", self.products, 36)):
            ttk.Label(head, text=label).pack(side="left", **PAD)
            ttk.Entry(head, textvariable=var, width=width).pack(side="left", **PAD)
        for row, (label, var) in enumerate((("장소 (영어)", self.setting), ("소리 (영어)", self.audio)), 2):
            line = ttk.Frame(body)
            line.grid(row=row, column=0, sticky="ew")
            ttk.Label(line, text=label, width=12).pack(side="left", **PAD)
            ttk.Entry(line, textvariable=var, width=100).pack(side="left", fill="x", expand=True, **PAD)
        ttk.Label(body, textvariable=self.facts, foreground=GREY, wraplength=900, justify="left"
                  ).grid(row=4, column=0, sticky="w", padx=6, pady=(6, 2))

        for n, beat in enumerate(self.beats):
            frame = ttk.LabelFrame(body, text=f"구간 {n + 1}", padding=6)
            frame.grid(row=5 + n, column=0, sticky="ew", pady=3)
            frame.columnconfigure(1, weight=1)
            times = ttk.Frame(frame)
            times.grid(row=0, column=0, columnspan=2, sticky="w")
            for label, key, width in (("시작(초)", "start_s", 4), ("끝(초)", "end_s", 4), ("자막", "caption_ko", 24),
                                      ("근거 (사실 id)", "evidence", 34)):
                ttk.Label(times, text=label).pack(side="left", **PAD)
                ttk.Entry(times, textvariable=beat[key], width=width).pack(side="left", **PAD)
            for row, (key, label) in enumerate(self.BEAT_ROWS, 1):
                ttk.Label(frame, text=label, width=14).grid(row=row, column=0, sticky="w", **PAD)
                ttk.Entry(frame, textvariable=beat[key], width=100).grid(row=row, column=1, sticky="ew", **PAD)

        bar = ttk.Frame(win, padding=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="닫기", command=win.destroy).pack(side="right", padx=4)
        ttk.Button(bar, text="저장하고 검사", command=lambda: self.save(check=True)).pack(side="right", padx=4)
        self.next_button = ttk.Button(bar, text="저장하고 다음 장면", command=lambda: self.save(advance=True))
        self.next_button.pack(side="right", padx=4)
        ttk.Button(bar, text="저장", command=self.save).pack(side="right", padx=4)
        ttk.Label(bar, text="화면(우리말)이 빈 구간은 저장하지 않습니다. 구간의 끝이 다음 구간의 시작과 같아야 합니다",
                  foreground=GREY).pack(side="left", padx=8)
        self.load()

    def _brief(self) -> dict[str, Any]:
        return authoring.brief_doc(self.project_dir, self.episode.get().strip()) or {}

    def show(self, doc: dict[str, Any]) -> None:
        self.format = doc.get("format", self.format)
        fmt = self.spec["formats"].get(self.format, {})
        number = int(self.number.get())
        role = doc.get("role", "")
        names = dict(zip(fmt.get("scene_roles", []), fmt.get("role_names_ko", [])))
        self.role.set(f"{fmt.get('name_ko', '')} · 장면 {number}의 역할: {names.get(role, role)} ({role})")
        self.scene_id.set(doc.get("scene_id", ""))
        self.duration.set(str(doc.get("duration_s", 15)))
        self.products.set(", ".join(doc.get("products", [])))
        self.setting.set(doc.get("setting_en", ""))
        self.audio.set(doc.get("audio_en", "") or "")
        beats = doc.get("beats", [])
        for n, row in enumerate(self.beats):
            beat = beats[n] if n < len(beats) else {}
            for key, var in row.items():
                value = beat.get(key, "")
                var.set(", ".join(value) if isinstance(value, list) else ("" if value is None else str(value)))
        self._role = role
        self.show_facts()

    def show_facts(self) -> None:
        lines = []
        for pid in authoring.split_ids(self.products.get()):
            doc = authoring.product_doc(self.project_dir, pid) or {}
            lines += [f"{f['id']}({f['text_ko']})" for f in doc.get("facts", [])]
        self.facts.set("근거로 쓸 수 있는 사실: " + (", ".join(lines) if lines else "없음. 제품 id 를 적거나 제품 등록에서 사실을 적습니다"))

    def missing(self) -> list[int]:
        """아직 저장하지 않은 장면 번호. 한 편은 세 장면이다."""
        count = int(self.spec["episode"]["scene_count"])
        episode = self.episode.get().strip()
        return [n for n in range(1, count + 1) if authoring.scene_path(self.project_dir, episode, n) is None]

    def show_progress(self) -> None:
        count = int(self.spec["episode"]["scene_count"])
        missing = self.missing()
        marks = "  ".join(f"장면 {n} {'—' if n in missing else '✔'}" for n in range(1, count + 1))
        tail = "세 장면이 모두 저장됐습니다. [저장하고 검사]를 누르면 됩니다" if not missing else \
            f"한 편은 {count}장면입니다. 장면 {', '.join(str(n) for n in missing)}을(를) 더 적어야 검사를 통과합니다"
        self.progress.set(f"저장된 장면:  {marks}   ·   {tail}")

    def is_last(self) -> bool:
        return int(self.number.get()) >= int(self.spec["episode"]["scene_count"])

    def load(self) -> None:
        self.show_progress()
        if self.next_button is not None:     # 마지막 장면에는 다음 장면이 없다
            self.next_button.configure(state="disabled" if self.is_last() else "normal")
        episode, number = self.episode.get().strip(), int(self.number.get())
        doc = authoring.scene_doc(self.project_dir, episode, number)
        if doc is None:
            brief = self._brief()
            fmt = brief.get("format") or next(iter(self.spec["formats"]))
            doc = authoring.blank_scene(episode, number, fmt, self.spec, brief.get("products", []))
        self.show(doc)

    def fill_sample(self) -> None:
        self.show(authoring.sample_scene(self.episode.get().strip(), int(self.number.get())))

    def collect(self) -> dict[str, Any]:
        beats = []
        for row in self.beats:
            beat: dict[str, Any] = {key: var.get().strip() for key, var in row.items()}
            beat["evidence"] = authoring.split_ids(beat["evidence"])
            beats.append(beat)
        return {
            "scene_id": self.scene_id.get().strip(), "format": self.format, "role": self._role,
            "duration_s": self.duration.get().strip(), "products": authoring.split_ids(self.products.get()),
            "setting_en": self.setting.get().strip(), "audio_en": self.audio.get().strip(), "beats": beats,
        }

    def save(self, advance: bool = False, check: bool = False) -> bool:
        episode, number = self.episode.get().strip(), int(self.number.get())
        try:
            scene = authoring.save_scene(self.project_dir, episode, number, self.collect())
        except InputError as exc:
            messagebox.showwarning("저장하지 않았습니다", str(exc), parent=self.win)
            return False
        self.app.reload()
        self.app.select_episode(episode)
        self.show_progress()
        missing = self.missing()
        if check and missing:               # 장면이 모자란 채로 검사하면 형식·길이 정책에 걸린다. 먼저 묻는다
            go_on = messagebox.askyesno(
                "아직 적지 않은 장면이 있습니다",
                f"장면 {number}을(를) 저장했습니다.\n"
                f"한 편은 세 장면인데 장면 {', '.join(str(n) for n in missing)}이(가) 아직 없습니다.\n"
                "이대로 검사하면 “장면 수”와 “길이”에서 걸립니다.\n\n"
                f"[예] 장면 {missing[0]}을(를) 적으러 간다\n[아니요] 지금 있는 것만 검사한다",
                parent=self.win)
            if go_on:
                self.number.set(str(missing[0]))
                self.load()
                return True
        if check:
            self.win.destroy()
            self.app.run_compile()
        elif advance and not self.is_last():
            self.number.set(str(number + 1))
            self.load()
        else:
            messagebox.showinfo("저장했습니다", f"{scene.scene_id}\n{authoring.scene_path(self.project_dir, episode, number)}",
                                parent=self.win)
        return True
