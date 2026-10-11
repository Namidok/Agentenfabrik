import asyncio
import shutil

import pytest
from fastapi.testclient import TestClient

from factory import server
from factory.scheduler import ModelScheduler

SPEC = """name: demo-agent
goal: "Demo agent for the tests"
mode: conversational
tools:
  - fs.list
permissions:
  fs_read: ["./sandbox"]
memory:
  notes: true
"""
HEADERS = {"x-agentfactory": "1"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "demo.yaml").write_text(SPEC)
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "SPECS_DIR", tmp_path / "specs")
    monkeypatch.setattr(server, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(server, "ollama_models", lambda: ["qwen3:8b"])
    monkeypatch.setattr(server, "SCHEDULER", ModelScheduler(1))
    monkeypatch.setattr(server, "loaded_models", lambda host=None: None)  # never call the real Ollama
    monkeypatch.setattr(server, "warm_up", lambda configs: None)
    return tmp_path


@pytest.fixture
def client(world):
    return TestClient(server.app, base_url="http://127.0.0.1")


@pytest.fixture
def trash(world, monkeypatch):
    """A stand-in Trash: a folder inside the test directory."""
    folder = world / "fake-trash"
    folder.mkdir()
    moved = []

    def fake(path):
        moved.append(path.name)
        shutil.move(str(path), str(folder / path.name))

    monkeypatch.setattr(server, "move_to_trash", fake)
    return folder, moved


def test_agent_list_names_the_spec_file(client):
    assert client.get("/api/agents").json()["agents"][0]["file"] == "demo.yaml"


def test_removing_an_agent_moves_its_spec_to_the_trash(client, world, trash):
    folder, moved = trash
    r = client.delete("/api/agents/demo-agent", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == {"removed": "demo-agent", "file": "demo.yaml", "notes_moved": False}
    assert moved == ["demo.yaml"]
    assert not (world / "specs" / "demo.yaml").exists()
    assert (folder / "demo.yaml").exists()  # recoverable, not destroyed
    assert client.get("/api/agents").json()["agents"] == []


def test_notes_stay_unless_asked_for(client, world, trash):
    folder, moved = trash
    notes = world / "data" / "demo-agent"
    notes.mkdir(parents=True)
    (notes / "notes.md").write_text("Project: Atlas\n")
    client.delete("/api/agents/demo-agent", headers=HEADERS)
    assert (notes / "notes.md").exists()
    assert moved == ["demo.yaml"]


def test_notes_move_too_when_requested(client, world, trash):
    folder, moved = trash
    notes = world / "data" / "demo-agent"
    notes.mkdir(parents=True)
    (notes / "notes.md").write_text("Project: Atlas\n")
    r = client.delete("/api/agents/demo-agent?notes=true", headers=HEADERS)
    assert r.json()["notes_moved"] is True
    assert moved == ["demo.yaml", "notes.md"]
    assert not (notes / "notes.md").exists()


def test_failed_notes_move_does_not_undo_the_removal(client, world, monkeypatch):
    notes = world / "data" / "demo-agent"
    notes.mkdir(parents=True)
    (notes / "notes.md").write_text("x")
    calls = []

    def flaky(path):
        calls.append(path.name)
        if path.name == "notes.md":
            raise OSError("nope")

    monkeypatch.setattr(server, "move_to_trash", flaky)
    r = client.delete("/api/agents/demo-agent?notes=true", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["notes_moved"] is False and "could not be moved" in r.json()["notes_error"]


def test_request_must_come_from_the_page(client, world, trash):
    folder, moved = trash
    assert client.delete("/api/agents/demo-agent").status_code == 403  # no marker header
    foreign = client.delete("/api/agents/demo-agent", headers={**HEADERS, "origin": "http://evil.example"})
    assert foreign.status_code == 403
    same = client.delete("/api/agents/demo-agent", headers={**HEADERS, "origin": "http://127.0.0.1"})
    assert same.status_code == 200  # allowed from this very page
    assert (world / "fake-trash" / "demo.yaml").exists()


@pytest.mark.parametrize("name", ["nobody-here", "Bad_Name", "..%2F..%2Fetc"])
def test_removing_an_unknown_agent_is_404(client, trash, name):
    assert client.delete(f"/api/agents/{name}", headers=HEADERS).status_code == 404
    assert trash[1] == []


def test_trash_failure_is_reported_and_the_file_stays(client, world, monkeypatch):
    def broken(path):
        raise PermissionError("no access")

    monkeypatch.setattr(server, "move_to_trash", broken)
    r = client.delete("/api/agents/demo-agent", headers=HEADERS)
    assert r.status_code == 500 and "PermissionError" in r.json()["detail"]
    assert (world / "specs" / "demo.yaml").exists()


def test_missing_trash_library_gives_a_clear_message(client, world, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_send2trash(name, *args, **kwargs):
        if name == "send2trash":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_send2trash)
    r = client.delete("/api/agents/demo-agent", headers=HEADERS)
    assert r.status_code == 501 and "pip install send2trash" in r.json()["detail"]
    assert (world / "specs" / "demo.yaml").exists()
