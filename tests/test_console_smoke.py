"""화면 코드의 연기 테스트. tkinter 를 가짜로 바꿔, 위젯 없이 콘솔의 흐름만 돌려 본다.

실제 창이 어떻게 보이는지는 이 테스트로 알 수 없다. 이름 오타, 잘못된 호출 순서, 비용 확인 누락을 잡는다.
"""
import sys
import types
from unittest.mock import MagicMock

import pytest


class Var:
    def __init__(self, value=None):
        self._value = "" if value is None else value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


@pytest.fixture
def console(monkeypatch, tmp_path):
    def widget(*args, **kwargs):      # 어떤 위젯이든 호출을 받아 주는 가짜
        return MagicMock()

    tk = types.ModuleType("tkinter")
    tk.Tk = tk.Menu = tk.Label = tk.Text = tk.Toplevel = widget
    tk.StringVar = tk.BooleanVar = Var
    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "LabelFrame", "Entry", "Button", "Combobox", "Checkbutton",
                 "Progressbar", "Treeview", "Notebook", "Scrollbar"):
        setattr(ttk, name, widget)
    messagebox = MagicMock()
    simpledialog = MagicMock()
    font = types.ModuleType("tkinter.font")
    font.Font = widget
    font.nametofont = widget
    tk.font, tk.TclError, ttk.Style = font, RuntimeError, widget
    monkeypatch.setitem(sys.modules, "tkinter.font", font)
    tk.ttk, tk.messagebox, tk.simpledialog, tk.filedialog = ttk, messagebox, simpledialog, MagicMock()
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", tk.filedialog)
    monkeypatch.delitem(sys.modules, "ass.console_forms", raising=False)
    monkeypatch.setitem(sys.modules, "tkinter.simpledialog", simpledialog)
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", messagebox)
    monkeypatch.delitem(sys.modules, "ass.console", raising=False)
    from ass import console_model

    monkeypatch.setattr(console_model, "PREFS_PATH", tmp_path / ".ass_console.json")
    monkeypatch.setattr(console_model.load_font_size, "__defaults__", (tmp_path / ".ass_console.json",))
    monkeypatch.setattr(console_model.save_font_size, "__defaults__", (tmp_path / ".ass_console.json",))
    # 고르는 창은 outputs 를 읽는다. 실제로 생성한 영상이 있는 PC 에서도 같은 결과가 나오게 빈 폴더를 보게 한다
    empty = tmp_path / "outputs"
    render_choices, sheet_choices = console_model.render_choices, console_model.sheet_choices
    monkeypatch.setattr(console_model, "render_choices", lambda episode: render_choices(episode, output_dir=empty))
    monkeypatch.setattr(console_model, "sheet_choices", lambda episode: sheet_choices(episode, output_dir=empty))
    from ass import console as module

    monkeypatch.setattr(module, "messagebox", messagebox)
    return module, messagebox


def _app(module):
    from ass import cli

    return module.ConsoleApp(MagicMock(), cli.available_commands())


class FakeProcess:
    def __init__(self, lines, code=0):
        self.stdout, self._code, self.terminated = iter(lines), code, False

    def wait(self):
        return self._code

    def terminate(self):
        self.terminated = True


def test_console_opens_on_script_stage_with_compile_ready(console):
    module, _ = console
    app = _app(module)
    assert app.status.get().startswith("명령 12개 중 4개 있음")
    assert app.stage.get() == "2. 대본" and app.command.get() == "compile"
    assert app.episode.get() == "product_intro"
    assert "제품 설명 · 장면 3개 · 45초" in app.summary.get()
    assert app.hint.get().startswith("ass compile — 장면 사양을")


def test_missing_command_is_explained_and_not_runnable(console):
    module, _ = console
    app = _app(module)
    app.stage.set("6. 조립·업로드")
    app.on_stage()
    assert app.command.get() == "assemble" and "계획만 확인합니다" in app.hint.get()   # 4장에서 생겼다
    app.command.set("publish")
    app.on_selection()
    assert "아직 없는 명령입니다" in app.hint.get()
    app.run_button.configure.assert_called_with(state="disabled")


def test_dry_run_render_runs_three_scenes_without_asking(console, monkeypatch):
    module, messagebox = console
    app = _app(module)
    started = []

    def fake_popen(argv, **kwargs):
        started.append(argv[3:])
        return FakeProcess(["모델 gemini-omni-1.2-flash\n"])

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module.threading, "Thread",
                        lambda target, args, daemon: MagicMock(start=lambda: target(*args)))
    app.stage.set("4. 장면 생성")
    app.on_stage()
    assert app.command.get() == "render" and "요청만 확인합니다" in app.hint.get()
    app.run()
    for _ in range(3):
        try:
            app._drain()
        except RecursionError:      # root.after 는 가짜라 다시 부르지 않는다
            pass
    assert [a[:5] for a in started] == [["render", "--episode", "product_intro", "--scene", str(n)] for n in (1, 2, 3)]
    assert all(a[-1] == "--dry-run" for a in started)
    messagebox.askokcancel.assert_not_called()
    assert app.process is None and app.notice.get() == "끝났습니다"
    assert app.run_text.get().startswith("✔ 끝났습니다")      # 끝난 것이 실행 단추 옆에 보인다
    app.progress.pack_forget.assert_called()                 # 멈춘 막대는 감춘다


def test_paid_render_asks_first_and_cancel_means_no_call(console, monkeypatch):
    module, messagebox = console
    app = _app(module)
    popen = MagicMock()
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    app.stage.set("4. 장면 생성")
    app.on_stage()
    app.dry_run.set(False)
    app.scene.set("1")
    app.on_selection()
    assert "이번 실행 추정 $1.05" in app.hint.get()
    messagebox.askokcancel.return_value = False
    app.run()
    assert "추정 비용 $1.05" in messagebox.askokcancel.call_args.args[1]
    popen.assert_not_called()


def test_over_budget_run_is_refused_before_asking(console, monkeypatch):
    module, messagebox = console
    monkeypatch.setenv("ASS_RUN_BUDGET_USD", "2.00")
    app = _app(module)
    popen = MagicMock()
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    app.stage.set("4. 장면 생성")
    app.on_stage()
    app.dry_run.set(False)
    app.run()                                   # 전체 3장면 $3.15 > $2.00
    assert "예산 상한을 넘습니다" == messagebox.showwarning.call_args.args[0]
    messagebox.askokcancel.assert_not_called()
    popen.assert_not_called()


def test_guard_block_stops_remaining_runs(console, monkeypatch):
    module, _ = console
    app = _app(module)
    monkeypatch.setattr(module.subprocess, "Popen", lambda argv, **k: FakeProcess(["[막힘] ...\n"], code=4))
    monkeypatch.setattr(module.threading, "Thread",
                        lambda target, args, daemon: MagicMock(start=lambda: target(*args)))
    app.stage.set("4. 장면 생성")
    app.on_stage()
    app.run()
    app._drain()
    assert app.notice.get() == "가드가 막았습니다" and app.pending == []


def test_files_tab_lists_what_compile_reads_and_logs_it_on_run(console, monkeypatch):
    module, _ = console
    app = _app(module)
    assert len(app.file_rows) == 15 and app.file_rows[0].mark == "①"
    assert "파일 8개를 읽고 7개를 쓴다" in app.files_note.get()
    assert "파일 8개를 읽고 7개를 쓴다" in app.hint.get()
    logged = []
    monkeypatch.setattr(app, "_log", logged.append)
    monkeypatch.setattr(module.subprocess, "Popen", lambda argv, **k: FakeProcess([]))
    monkeypatch.setattr(module.threading, "Thread", lambda target, args, daemon: MagicMock(start=lambda: None))
    app.run()
    assert logged[0] == "읽는 파일 8개:"
    assert logged[1] == "  ① examples/moalab_skincare/episodes/product_intro/scene_01_problem.yaml"
    assert logged[9] == "$ ass compile --episode product_intro"


def test_files_tab_is_empty_with_explanation_for_missing_command(console):
    module, _ = console
    app = _app(module)
    app.stage.set("5. 오디오")
    app.on_stage()
    assert app.file_rows == [] and "이 명령이 생기면" in app.files_note.get()


def test_작업_메뉴는_명령을_그대로_실행한다(console, monkeypatch):
    module, messagebox = console
    app = _app(module)
    started = []
    monkeypatch.setattr(app, "_begin", started.append)
    app.run_doctor()
    app.run_cost()
    module.simpledialog.askfloat.return_value = 3.15
    module.simpledialog.askstring.return_value = "생성 전 10.00, 후 6.85"
    app.record_billed()
    module.simpledialog.askfloat.return_value = None         # 취소하면 아무 일도 하지 않는다
    app.record_billed()
    assert started == [
        [["doctor"]],
        [["cost", "--episode", "product_intro"]],
        [["cost", "--episode", "product_intro", "--billed", "3.15", "--note", "생성 전 10.00, 후 6.85"]],
    ]


def test_고른_영상은_assemble_의_pick_으로_간다(console, monkeypatch):
    module, messagebox = console
    app = _app(module)
    app.choose_renders()                                      # 성공한 생성이 없으면 창을 열지 않고 알려 준다
    messagebox.showinfo.assert_called_once()
    app.stage.set("6. 조립·업로드")
    app.on_stage()
    app.picks = {"2": "20261120-110200"}
    app.on_selection()
    assert "직접 고른 영상: 장면 2=20261120-110200" in app.hint.get()
    started = []
    monkeypatch.setattr(app, "_begin", started.append)
    app.run()
    assert started == [[["assemble", "--episode", "product_intro", "--pick", "2=20261120-110200", "--dry-run"]]]
    app.on_episode()                                          # 편을 바꾸면 고른 것을 버린다
    assert app.picks == {}


def test_글자_크기를_바꾸면_저장되고_다음에_그대로_열린다(console):
    module, _ = console
    from ass import console_model as m

    app = _app(module)
    assert app.font_size == m.DEFAULT_FONT_SIZE == 12
    app.change_font(1)
    app.change_font(1)
    assert app.font_size == 14 and "글자 크기 14" in app.notice.get()
    app.f_mono.configure.assert_called_with(size=14)
    assert _app(module).font_size == 14                       # 다시 열어도 그대로
    for _ in range(10):
        app.change_font(1)
    assert app.font_size == m.MAX_FONT_SIZE
    app.change_font(0)
    assert app.font_size == 12
    assert m.font_sizes(12) == {"ui": 12, "mono": 12, "badge": 16, "title": 20, "row": 28}


def test_레퍼런스_단계는_sheet_를_실행하고_비용을_먼저_묻는다(console, monkeypatch):
    module, messagebox = console
    app = _app(module)
    app.stage.set("3. 제품 레퍼런스")
    app.on_stage()
    assert app.command.get() == "sheet" and "요청만 확인합니다" in app.hint.get()
    started = []
    monkeypatch.setattr(app, "_begin", started.append)
    app.run()
    assert started == [[["sheet", "--product", "moalab_aqua_serum", "--dry-run"]]]
    messagebox.askokcancel.assert_not_called()
    app.dry_run.set(False)
    app.on_selection()
    assert "이번 실행 추정 $0.17" in app.hint.get()
    messagebox.askokcancel.return_value = False
    app.run()
    assert "레퍼런스 시트를 실제로 생성합니다" in messagebox.askokcancel.call_args[0][1] and len(started) == 1
    app.run_bible()
    assert started[-1] == [["bible"]]
    app.choose_references()                                   # 후보가 없으면 창을 열지 않는다
    assert "후보를 먼저 만드세요" in messagebox.showinfo.call_args[0][1]


# ---------------------------------------------------------------- 입력 화면
class FakeText:
    """여러 줄 칸의 가짜. 값을 기억한다."""

    def __init__(self, parent, height, width=80):
        self.widget, self.value = MagicMock(), ""

    def get(self):
        return self.value

    def set(self, value):
        self.value = value or ""


@pytest.fixture
def forms(console, monkeypatch, tmp_path):
    """가짜 화면 위에서 입력 화면을 연다. 내 프로젝트는 임시 폴더에 만든다."""
    from ass import authoring, console_forms, settings

    project = authoring.init_project("my_first", tmp_path / "projects")
    monkeypatch.setattr(settings, "PROJECT", "my_first")
    monkeypatch.setattr(settings, "PROJECT_DIR", project)
    monkeypatch.setattr(console_forms, "TextField", FakeText)
    monkeypatch.setattr(console_forms, "messagebox", MagicMock())
    return console_forms, MagicMock(), project


def test_견본을_보고_있으면_입력_화면_대신_프로젝트부터_만들게_한다(console, monkeypatch):
    module, _ = console
    from ass import console_forms, settings

    box = MagicMock()
    box.askokcancel.return_value = False
    monkeypatch.setattr(console_forms, "messagebox", box)
    assert settings.PROJECT == "sample" and console_forms.need_project(MagicMock()) is False
    assert "견본은 고치지 않습니다" in box.askokcancel.call_args[0][1]
    app = _app(module)
    app.open_form("ProductForm")                              # 창을 열지 않고 돌아온다
    assert "견본 (책의 예제)" in __import__("ass.console_model", fromlist=["x"]).project_line()


def test_제품_등록은_견본으로_채우고_저장하면_파일이_된다(forms):
    console_forms, app, project = forms
    from ass import authoring

    form = console_forms.ProductForm(app)
    form.open()
    form.fill_sample()
    assert form.product_id.get() == "moalab_aqua_serum" and form.vars["brand"].get() == "MOALAB"
    assert "serum_volume | 용량 30ml | 가상 제품 설정" in form.texts["facts"].get()
    assert form.save() is True
    app.reload.assert_called_once()
    assert authoring.product_ids(project) == ["moalab_aqua_serum"]
    form.texts["facts"].set("용량 30ml")                         # 칸을 잘못 적으면 저장하지 않고 이유를 보인다
    assert form.save() is False
    assert "세로줄" in console_forms.messagebox.showwarning.call_args[0][1]
    form.texts["facts"].set("")
    form.product_id.set("moalab_aqua_serum")
    form.load()                                               # 저장된 것을 다시 불러온다
    assert "serum_usage" in form.texts["facts"].get()
    assert form.save(check=True) is True
    app.run_bible.assert_called_once()


def test_소재_입력은_소유_확인_표시가_있어야_저장한다(forms):
    console_forms, app, project = forms
    from ass import authoring

    authoring.save_product(project, "moalab_aqua_serum", authoring.sample_product())
    form = console_forms.BriefForm(app)
    form.open()
    form.fill_sample()
    assert form.title.get().startswith("오후에 당기는 피부") and form.points[1][1].get() == "serum_texture, serum_fragrance"
    assert form.owner.get() is False and form.save() is False           # 견본이 대신 표시하지 않는다
    assert "네모 칸을 눌러 표시한 뒤 다시 저장" in console_forms.messagebox.showwarning.call_args[0][1]
    assert "직접 눌러 표시하세요" in form.owner_hint.get()
    form.owner.set(True)
    form.source.set("내 블로그 글")
    assert form.save() is True
    assert (project / "source_briefs" / "product_intro.yaml").is_file()
    assert (project / "sources" / "product_intro.txt").read_text(encoding="utf-8") == "내 블로그 글\n"


def test_장면_작성은_세_장면을_차례로_저장하고_검사로_넘어간다(forms):
    console_forms, app, project = forms
    from ass import authoring

    authoring.save_product(project, "moalab_aqua_serum", authoring.sample_product())
    authoring.save_brief(project, "product_intro", authoring.sample_brief("product_intro"))
    form = console_forms.SceneForm(app)
    form.open()                                               # 저장된 장면이 없으면 빈 장면을 보인다
    assert form.scene_id.get() == "product_intro_s01" and "문제 (problem)" in form.role.get()
    assert "serum_volume(용량 30ml)" in form.facts.get()
    assert form.save() is False                               # 빈 채로는 저장하지 않는다
    form.fill_sample()
    console_forms.messagebox.askyesno.return_value = True     # 장면 하나만 적고 검사를 누르면 다음 장면으로 데려간다
    assert form.save(check=True) is True and form.number.get() == "2"
    assert "장면 2, 3이(가) 아직 없습니다" in console_forms.messagebox.askyesno.call_args[0][1]
    assert "장면 1 ✔  장면 2 —  장면 3 —" in form.progress.get()
    app.run_compile.assert_not_called()
    form.number.set("1")
    form.load()
    for number in ("1", "2"):
        form.fill_sample()
        assert form.save(advance=True) is True and form.number.get() == str(int(number) + 1)
    assert form.is_last()                                     # 마지막 장면에서는 [저장하고 다음 장면]을 누를 수 없다
    form.next_button.configure.assert_called_with(state="disabled")
    form.fill_sample()
    assert form.beats[0]["caption_ko"].get() == "세안 후 두세 방울"
    assert form.save(check=True) is True
    app.run_compile.assert_called_once()
    app.select_episode.assert_called_with("product_intro")
    assert "세 장면이 모두 저장됐습니다" in form.progress.get()
    assert len(list((project / "episodes" / "product_intro").glob("scene_*.yaml"))) == 3
