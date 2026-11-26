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
    assert app.status.get().startswith("명령 12개 중 6개 있음")
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


def test_일부_방향만_다시_만들기_창은_고른_방향으로_sheet_를_실행한다(console, monkeypatch):
    from unittest.mock import MagicMock

    module, messagebox = console
    app = _app(module)
    buttons, checks = {}, {}

    def button(*args, **kwargs):
        buttons[kwargs.get("text")] = kwargs.get("command")
        return MagicMock()

    def check(*args, **kwargs):
        checks[kwargs.get("text")] = kwargs.get("variable")
        return MagicMock()

    monkeypatch.setattr(module.ttk, "Button", button)
    monkeypatch.setattr(module.ttk, "Checkbutton", check)
    started = []
    monkeypatch.setattr(app, "_begin", started.append)
    app.remake_views()
    buttons["실행"]()                                           # 아무 방향도 고르지 않았다
    assert started == [] and "고른 방향이 없습니다" in messagebox.showinfo.call_args[0][0]
    label = next(v for k, v in checks.items() if k.startswith("라벨 가까이"))
    label.set(True)
    buttons["실행"]()                                           # 요청만 확인: 묻지 않고 계획을 본다. 사진이 없어 정면이 붙는다
    assert started == [[["sheet", "--product", "moalab_aqua_serum", "--views", "front,label", "--dry-run"]]]
    messagebox.askokcancel.assert_not_called()
    app.dry_run.set(False)
    messagebox.askokcancel.return_value = False
    buttons["실행"]()                                           # 실제 생성은 비용을 먼저 묻는다
    asked = messagebox.askokcancel.call_args[0][1]
    assert "2장(front, label)" in asked and "$0.07" in asked and "기준 방향(front)" in asked and len(started) == 1


def test_소재_입력의_초안_만들기와_불러오기(forms):
    console_forms, app, project = forms
    from ass import authoring

    authoring.save_product(project, "moalab_aqua_serum", authoring.sample_product())
    form = console_forms.BriefForm(app)
    form.open()
    form.fill_sample()
    assert "오후 세 시쯤 볼이 당긴다" in form.source.get()             # 견본의 블로그 글이 원문 칸에 들어온다
    app.process, app.dry_run.get.return_value = None, True
    form.make_draft()                                          # 소유 확인 표시가 없으면 보내지 않는다
    app._begin.assert_not_called()
    assert "표시해야 초안을 만든다" in console_forms.messagebox.showwarning.call_args[0][1]
    form.owner.set(True)
    form.make_draft()
    assert app._begin.call_args[0][0][0][:3] == ["brief", "--episode", "product_intro"]
    assert app._begin.call_args[0][0][0][-2:] == ["--owner-confirmed", "--dry-run"]
    assert (project / "sources" / "product_intro.txt").is_file()
    form.load_draft()                                          # 초안이 없으면 알려 준다
    assert console_forms.messagebox.showinfo.call_args[0][0] == "초안이 없습니다"
    draft = project / "drafts" / "product_intro"
    draft.mkdir(parents=True)
    (draft / "brief.yaml").write_text(
        "title_ko: 초안 제목\npromise_ko: 초안 약속\nformat: product_intro\nsource_type: own_blog\nowner_confirmed: false\n"
        "products: [moalab_aqua_serum]\nkey_points:\n  - {text_ko: 요점 하나, evidence: [serum_usage]}\n"
        "draft: {check: ['요점 1: 인용이 원문에 없다']}\n", encoding="utf-8")
    form.load_draft()
    assert form.title.get() == "초안 제목" and form.points[0][1].get() == "serum_usage"
    assert form.owner.get() is True                            # 초안이 소유 확인 표시를 끄거나 켜지 않는다
    assert "확인할 것 1개" in console_forms.messagebox.showinfo.call_args[0][1]
    assert "제목과 약속: 프로그램이 대조하지 않는 칸입니다" in console_forms.messagebox.showinfo.call_args[0][1]
    (draft / "scene_01.yaml").write_text(
        "scene_id: product_intro_s01\nepisode_id: product_intro\nformat: product_intro\nrole: problem\nduration_s: 15\n"
        "products: [moalab_aqua_serum]\nsetting_en: A desk\nbeats:\n  - {start_s: 0, end_s: 15, visual_ko: 초안 화면, visual_en: A desk}\n",
        encoding="utf-8")
    (draft / "script_check.yaml").write_text("check: ['장면 1 구간 1: x', '장면 2 구간 1: y', '문법: z']\n", encoding="utf-8")
    scene = console_forms.SceneForm(app)
    scene.open()
    scene.number.set("2")
    scene.load_draft()                                         # 장면 2의 초안은 없다. 어떻게 만드는지 알려 준다
    assert console_forms.messagebox.showinfo.call_args[0][0] == "장면 초안이 없습니다"
    app.dry_run.get.return_value = False
    scene.make_draft()                                         # 창 안에서 이 편의 장면 초안을 만든다
    assert app.run_script.call_args.kwargs["episode"] == "product_intro"
    assert app.after_run == scene._draft_done                  # 끝나면 초안을 대신 불러온다
    scene.number.set("1")
    scene.win = scene.win or __import__("unittest.mock").mock.MagicMock()      # 이 시험에는 편 폴더가 없어 창을 만들지 않았다
    scene._draft_done(1)                                       # 실패하면 칸을 건드리지 않는다
    assert scene.beats[0]["visual_ko"].get() == "" and "만들지 못했습니다" in scene.draft_note.get()
    scene._draft_done(0)
    assert scene.beats[0]["visual_ko"].get() == "초안 화면"
    scene.beats[0]["visual_ko"].set("내가 적은 화면")
    console_forms.messagebox.askyesno.return_value = False
    scene._draft_done(0)                                       # 적어 둔 것이 있으면 묻는다
    assert scene.beats[0]["visual_ko"].get() == "내가 적은 화면"
    scene.beats[0]["visual_ko"].set("")
    scene.number.set("1")
    scene.load_draft()
    assert scene.beats[0]["visual_ko"].get() == "초안 화면" and scene.setting.get() == "A desk"
    assert "확인할 것 2개" in console_forms.messagebox.showinfo.call_args[0][1]


def test_소재_입력의_견본은_형식을_따른다(forms):
    console_forms, app, project = forms
    from ass import authoring

    form = console_forms.BriefForm(app)
    form.open()
    names = {v: k for k, v in form.formats.items()}
    assert form.kinds[form.kind.get()] == "own_blog" and form.formats[form.format.get()] == "product_intro"
    form.fill_sample()                                         # 처음 그대로 누르면 수분 세럼. 3장의 흐름이다
    assert form.episode.get() == "product_intro" and "수분 세럼" in form.title.get() and "오후 세 시쯤" in form.source.get()
    form.format.set(names["info"])
    form.fill_sample()                                         # 정보 전달: 화분에 물 주는 법 (블로그 글)
    assert form.episode.get() == "watering_plants" and form.products.get() == "" and "손가락" in form.points[0][0].get()
    assert form.points[0][1].get() == "본인 블로그 글 2문단" and "베란다에 화분 셋" in form.source.get()
    assert form.collect()["key_points"][0]["evidence"] == ["본인 블로그 글 2문단"]      # 글로 적은 출처가 띄어쓰기에서 쪼개지지 않는다
    form.kind.set(authoring.SOURCE_TYPES["idea"])
    form.fill_sample()                                         # 정보 전달 + 아이디어 한 줄: 냉장고 냄새. 요점과 근거까지
    assert form.episode.get() == "fridge_smell" and form.source.get().strip() == authoring.IDEA_TEXT
    assert form.title.get() and all(t.get() and "FSIS" in e.get() for t, e in form.points) and form.owner.get() is False
    data = form.collect()                                      # 근거의 출처가 쉼표로 쪼개지지 않는다
    assert [len(p["evidence"]) for p in data["key_points"]] == [1, 1, 1]
    assert authoring.save_brief(project, "fridge_smell", {**data, "owner_confirmed": True}).format == "info"
    form.format.set(names["comparison"])
    form.fill_sample()                                         # 제품 비교: 선크림 둘. 등록할 제품을 알려 준다
    assert form.episode.get() == "sunscreen_compare" and form.products.get() == "moalab_gel_sunscreen, haruon_cream_sunscreen"
    assert form.points[1][1].get() == "gel_sun_texture, cream_sun_texture"
    assert "moalab_gel_sunscreen, haruon_cream_sunscreen" in console_forms.messagebox.showinfo.call_args[0][1]
    form.format.set(names["product_intro"])
    form.fill_sample()                                         # 되돌아오면 세럼 편과 그 블로그 글
    assert form.episode.get() == "product_intro" and "오후 세 시쯤" in form.source.get()
    form.episode.set("my_serum")
    form.source.set("내가 붙여 넣은 글")
    form.fill_sample()                                         # 내가 정한 편 이름과 내 글은 바꾸지 않는다
    assert form.episode.get() == "my_serum" and form.source.get().strip() == "내가 붙여 넣은 글"


def test_장면_작성의_견본도_편을_따른다(forms):
    console_forms, app, project = forms
    from ass import authoring

    assert authoring.sample_scene_for(project, "watering_plants", 2)["role"] == "methods"
    assert authoring.sample_scene_for(project, "product_intro", 2)["role"] == "solution"
    assert authoring.sample_scene_for(project, "my_new_episode", 1)["role"] == "problem"     # 소재 요약이 없으면 세럼
    assert authoring.sample_scene_for(project, "sunscreen_compare", 2)["role"] == "side_by_side"   # 비교 편의 장면 견본 (7장)
    (project / "source_briefs").mkdir(parents=True, exist_ok=True)
    (project / "source_briefs" / "fridge_smell.yaml").write_text("format: info\n", encoding="utf-8")
    assert authoring.sample_scene_for(project, "fridge_smell", 1) is None                     # 냉장고 편의 장면 견본은 없다


def test_아이디어_한_줄에서_시작한_편은_근거가_비면_저장하지_않는다(forms):
    console_forms, app, project = forms
    from ass import authoring

    data = {**authoring.sample_idea_brief(), "owner_confirmed": True,
            "key_points": [{"text_ko": "상한 음식부터 버린다", "evidence": []}]}
    with pytest.raises(authoring.InputError, match="요점 1의 근거가 비어 있다"):
        authoring.save_brief(project, "fridge_smell", data)
    data["key_points"][0]["evidence"] = ["직접 해 봄, 2026-11"]
    assert authoring.save_brief(project, "fridge_smell", data).format == "info"
