"""File control: find / create / move / copy / rename / organize / undo, typing, and the safety rules."""
from pathlib import Path

import pytest

from assistant import Assistant
from conftest import FakeLLM
from executor import Executor
from files import FileError, FileManager, name_score
from keyboard_text import KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, VK_RETURN, key_events
from telemetry import TelemetryCollector


def intent(i, target="", reply="", conf=0.95, **extra):
    return {"intent": i, "target": target, "browser": "", "reply": reply, "confidence": conf, **extra}


@pytest.fixture
def pc(tmp_path):
    """A fake user folder: Desktop / Downloads / Documents / Pictures + something outside them."""
    roots = {}
    for name in ("Desktop", "Downloads", "Documents", "Pictures"):
        roots[name.lower()] = tmp_path / name
        roots[name.lower()].mkdir()
    (tmp_path / "Windows").mkdir()
    (tmp_path / "Windows" / "system.dll").write_text("x")
    d = roots["desktop"]
    for f in ("Screenshot 2026-11-01.png", "Screenshot 2026-11-02.png", "holiday.jpg", "CV 2026.pdf",
              "notes.txt", "song.mp3", "setup.exe", "Steam.lnk", "weird.xyz"):
        (d / f).write_text(f)
    (roots["downloads"] / "Screenshot old.png").write_text("s")
    (roots["documents"] / "Budget.xlsx").write_text("b")
    fm = FileManager(roots=roots, journal_path=tmp_path / "journal.json")
    return fm, roots, tmp_path


def test_name_matching():
    assert name_score("cv", "CV 2026.pdf") == 0.9
    assert name_score("budget", "Budget.xlsx") == 1.0
    assert name_score("my cv", "MyCV.docx") >= 0.8
    assert name_score("budget", "holiday.jpg") < 0.6


def test_find_and_folders(pc):
    fm, roots, _ = pc
    assert fm.find("cv")[0].name == "CV 2026.pdf"
    assert fm.best_match("budget").name == "Budget.xlsx"
    assert fm.resolve_folder("my downloads") == roots["downloads"].resolve()
    assert fm.resolve_folder("desktop") == roots["desktop"].resolve()
    assert fm.find("system") == []                       # outside the allowed folders: invisible


def test_never_outside_allowed_folders(pc):
    fm, roots, tmp = pc
    with pytest.raises(FileError):
        fm.plan_transfer("move", [tmp / "Windows" / "system.dll"], roots["desktop"])
    with pytest.raises(FileError):
        fm.plan_transfer("move", [roots["desktop"] / "notes.txt"], tmp / "Windows")
    with pytest.raises(FileError):
        fm.rename(roots["desktop"], "Desk")                # the allowed folder itself
    with pytest.raises(FileError):
        fm.create_folder("x", tmp / "Windows")


def test_select_kinds(pc):
    fm, roots, _ = pc
    shots = fm.select("my screenshots")
    assert sorted(p.name for p in shots) == ["Screenshot 2026-11-01.png", "Screenshot 2026-11-02.png",
                                             "Screenshot old.png"]
    assert [p.name for p in fm.select("screenshots", roots["downloads"])] == ["Screenshot old.png"]
    assert [p.name for p in fm.select("pdfs")] == ["CV 2026.pdf"]


def test_organize_then_undo(pc):
    fm, roots, _ = pc
    d = roots["desktop"]
    plan = fm.plan_organize(d)
    assert "Steam.lnk" not in [s.name for s, _ in plan.pairs]       # app icons stay
    assert "weird.xyz" not in [s.name for s, _ in plan.pairs]       # unknown kinds stay
    done, errors = fm.execute(plan)
    assert done == 7 and not errors
    assert (d / "Images" / "holiday.jpg").exists() and (d / "Documents" / "CV 2026.pdf").exists()
    assert (d / "Installers" / "setup.exe").exists() and (d / "Steam.lnk").exists()
    summary, restored, problems = FileManager(roots={k: v for k, v in roots.items()},
                                              journal_path=fm.journal_path).undo()   # survives a restart
    assert restored == 7 and not problems
    assert (d / "holiday.jpg").exists() and not (d / "Images").exists()            # empty folders removed


def test_move_never_overwrites(pc):
    fm, roots, _ = pc
    (roots["pictures"] / "holiday.jpg").write_text("older one")
    fm.execute(fm.plan_transfer("move", [roots["desktop"] / "holiday.jpg"], roots["pictures"]))
    assert (roots["pictures"] / "holiday.jpg").read_text() == "older one"
    assert (roots["pictures"] / "holiday (2).jpg").read_text() == "holiday.jpg"


def test_copy_undo_uses_recycle_bin(pc, monkeypatch):
    fm, roots, _ = pc
    trashed = []
    monkeypatch.setattr("send2trash.send2trash", lambda p: (trashed.append(p), Path(p).unlink()))
    fm.execute(fm.plan_transfer("copy", [roots["documents"] / "Budget.xlsx"], roots["desktop"]))
    assert (roots["desktop"] / "Budget.xlsx").exists() and (roots["documents"] / "Budget.xlsx").exists()
    fm.undo()
    assert [Path(t).name for t in trashed] == ["Budget.xlsx"] and (roots["documents"] / "Budget.xlsx").exists()


def test_rename_keeps_extension_and_undo(pc):
    fm, roots, _ = pc
    new = fm.rename(roots["documents"] / "Budget.xlsx", "Budget 2026")
    assert new.name == "Budget 2026.xlsx"
    fm.undo()
    assert (roots["documents"] / "Budget.xlsx").exists()


def test_typing_events_cover_any_text():
    ev = key_events("Hi😀\n")
    assert ev[0] == (0, ord("H"), KEYEVENTF_UNICODE)
    assert sum(1 for e in ev if e[2] & KEYEVENTF_UNICODE) == 2 * 4          # H, i, and the emoji's 2 halves
    assert ev[-2:] == [(VK_RETURN, 0, 0), (VK_RETURN, 0, KEYEVENTF_KEYUP)]


# ------------------------------------------------------------------ through the assistant

@pytest.fixture
def kageon(pc, fake_index):
    fm, roots, tmp = pc
    ex = Executor(dry_run=True, app_index=fake_index, files=fm)     # apps don't launch, files really move
    llm = FakeLLM({"stuff on the desktop": intent("organize_folder", "desktop")})
    return Assistant(llm, ex, TelemetryCollector(), confirm_timeout=60), llm, roots


async def test_organize_desktop_by_voice(kageon):
    a, llm, roots = kageon
    r = await a.handle_text("Hey Kageon, clean up my desktop")
    assert r["status"] == "needs_confirmation" and "move 7 files into" in r["reply"] and llm.calls == []
    r = await a.handle_text("yes")
    assert r["status"] == "done" and (roots["desktop"] / "Images" / "holiday.jpg").exists()
    r = await a.handle_text("undo that")
    assert r["status"] == "done" and (roots["desktop"] / "holiday.jpg").exists()


async def test_move_screenshots_asks_first(kageon):
    a, _, roots = kageon
    r = await a.handle_text("move my screenshots from downloads to pictures")
    assert r["status"] == "done" and (roots["pictures"] / "Screenshot old.png").exists()   # one file: just do it
    r = await a.handle_text("move my screenshots to pictures")
    assert r["status"] == "needs_confirmation" and r["reply"] == "Move 2 items to Pictures?"
    r = await a.handle_text("no")
    assert r["status"] == "cancelled" and (roots["desktop"] / "Screenshot 2026-11-01.png").exists()


async def test_create_folder_keeps_capitals(kageon):
    a, _, roots = kageon
    r = await a.handle_text("Hey Kageon, create a folder called Game Clips in documents.")
    assert r["status"] == "done" and (roots["documents"] / "Game Clips").is_dir()


async def test_rename_and_find(kageon):
    a, _, roots = kageon
    r = await a.handle_text("rename notes to Ideas")
    assert r["reply"] == "Renamed notes.txt to Ideas.txt." and (roots["desktop"] / "Ideas.txt").exists()
    r = await a.handle_text("where is my cv")
    assert r["status"] == "needs_confirmation" and "CV 2026.pdf" in r["reply"]
    r = await a.handle_text("yes")
    assert r["status"] == "done" and r["reply"] == "Opening CV 2026.pdf."


async def test_open_folder_or_file_by_name(kageon):
    a, llm, _ = kageon
    r = await a.handle_text("open my downloads")
    assert r["status"] == "done" and "Downloads" in r["reply"] and llm.calls == []
    r = await a.handle_text("open budget")
    assert r["status"] == "done" and "Budget.xlsx" in r["reply"]


async def test_type_text_keeps_exact_words(kageon):
    a, _, _ = kageon
    r = await a.handle_text("Hey Kageon, type Hello Sara, see you at 5! in Notepad")
    assert r["intent"] == "type_text" and r["target"] == "Hello Sara, see you at 5!"
    assert r["status"] == "done" and r["reply"] == "Typed it in Notepad."
    r = await a.handle_text("type I'm in love with this")      # "in love" is not an app
    assert r["target"] == "I'm in love with this"


async def test_llm_file_intent_and_unknown_folder(kageon):
    a, llm, _ = kageon
    llm.rules["somewhere"] = intent("move_files", "cv", dest="Narnia")
    r = await a.handle_text("put the cv somewhere")
    assert r["status"] == "failed" and "Narnia" in r["reply"]
