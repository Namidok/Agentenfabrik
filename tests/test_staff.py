import asyncio

import pytest
from fastapi.testclient import TestClient

from factory import server
from factory.scheduler import ModelScheduler

SPEC = """name: demo-agent
goal: "Demo agent for the tests"
system_prompt: "You are careful and short."
mode: conversational
tools:
  - fs.list
permissions:
  fs_read: ["./sandbox"]
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "demo.yaml").write_text(SPEC)
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "SPECS_DIR", tmp_path / "specs")
    monkeypatch.setattr(server, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(server, "ollama_models", lambda: ["qwen3:8b"])
    monkeypatch.setattr(server, "SCHEDULER", ModelScheduler(1))
    monkeypatch.setattr(server, "loaded_models", lambda host=None: None)  # never call the real Ollama
    monkeypatch.setattr(server, "warm_up", lambda configs: None)
    return TestClient(server.app, base_url="http://127.0.0.1")


def test_staff_file_returns_the_agent_file_and_its_instructions(client):
    data = client.get("/api/agents/demo-agent/file").json()
    assert data["file"] == "demo.yaml" and data["path"] == "specs/demo.yaml"
    assert data["yaml"] == SPEC and data["system_prompt"] == "You are careful and short."


@pytest.mark.parametrize("name", ["nobody-here", "Bad_Name", "..%2F..%2Fetc%2Fpasswd"])
def test_staff_file_of_an_unknown_agent_is_404(client, name):
    assert client.get(f"/api/agents/{name}/file").status_code == 404


def test_staff_file_is_cut_off_at_a_sensible_size(client, tmp_path):
    (tmp_path / "specs" / "demo.yaml").write_text(SPEC + "# " + "x" * 30000 + "\n")
    assert len(client.get("/api/agents/demo-agent/file").json()["yaml"]) == 20000
