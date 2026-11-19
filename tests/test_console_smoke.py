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
def console(monkeypatch):
    def widget(*args, **kwargs):      # 어떤 위젯이든 호출을 받아 주는 가짜
        return MagicMock()

    tk = types.ModuleType("tkinter")
    tk.Tk = tk.Menu = tk.Label = tk.Text = widget
    tk.StringVar = tk.BooleanVar = Var
    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "LabelFrame", "Entry", "Button", "Combobox", "Checkbutton",
                 "Progressbar", "Treeview", "Notebook", "Scrollbar"):
        setattr(ttk, name, widget)
    messagebox = MagicMock()
    tk.ttk, tk.messagebox = ttk, messagebox
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", messagebox)
    monkeypatch.delitem(sys.modules, "ass.console", raising=False)
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
    assert app.status.get().startswith("명령 12개 중 2개 있음")
    assert app.stage.get() == "2. 대본" and app.command.get() == "compile"
    assert app.episode.get() == "product_intro"
    assert "제품 설명 · 장면 3개 · 45초" in app.summary.get()
    assert app.hint.get().startswith("ass compile — 장면 사양을")


def test_missing_command_is_explained_and_not_runnable(console):
    module, _ = console
    app = _app(module)
    app.stage.set("6. 조립·업로드")
    app.on_stage()
    assert app.command.get() == "assemble"
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
