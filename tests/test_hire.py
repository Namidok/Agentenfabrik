import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from factory import server
from factory.llm import LLMResponse, MockProvider, ProviderError

HEADERS = {"x-agentfactory": "1"}
FORM = {
    "name": "note-helper",
    "display_name": "Note Helper",
    "goal": "Help me keep my notes tidy and findable.",
    "mode": "conversational",
    "tools": ["fs.list", "fs.read"],
    "fs_read": ["./sandbox"],
    "color": "#2ec4a0",
    "hair": "#a03a6a",
}


@pytest.fixture
def world(tmp_path, monkeypatch):
    (tmp_path / "specs").mkdir()
    (tmp_path / "sandbox").mkdir()
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "SPECS_DIR", tmp_path / "specs")
    monkeypatch.setattr(server, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(server, "ollama_models", lambda: ["qwen3:8b"])
    monkeypatch.setattr(server, "MODEL_LOCK", asyncio.Lock())
    return tmp_path


@pytest.fixture
def client(world):
    return TestClient(server.app, base_url="http://127.0.0.1")


def post(client, url, body, **kw):
    return client.post(url, json=body, headers={**HEADERS, **kw.pop("headers", {})}, **kw)


def test_options_list_the_tools_and_what_each_needs(client):
    data = client.get("/api/hire/options").json()
    by_id = {t["id"]: t for t in data["tools"]}
    assert by_id["fs.read"]["needs"] == "fs_read"
    assert by_id["notes.append"]["needs"] == ""
    assert data["max_tools"] == 6


def test_preview_shows_the_blueprint_and_writes_nothing(client, world):
    r = post(client, "/api/hire/preview", FORM)
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "note-helper" and data["file"] == "note-helper.yaml"
    assert "name: note-helper" in data["yaml"] and "display_name: Note Helper" in data["yaml"]
    assert data["exists"] is False
    assert not list((world / "specs").iterdir())


def test_preview_gives_the_agent_a_default_prompt_when_left_empty(client):
    yaml_text = post(client, "/api/hire/preview", FORM).json()["yaml"]
    assert "Help me keep my notes tidy" in yaml_text and "If you are not sure" in yaml_text


def test_a_missing_folder_is_a_heads_up(client):
    notes = post(client, "/api/hire/preview", {**FORM, "fs_read": ["./nowhere"]}).json()["notes"]
    assert any("'./nowhere' does not exist" in n for n in notes)


def test_requests_must_come_from_the_page(client):
    for url in ("/api/hire/preview", "/api/hire", "/api/hire/draft"):
        assert client.post(url, json=FORM).status_code == 403
        foreign = client.post(url, json=FORM, headers={**HEADERS, "origin": "http://evil.example"})
        assert foreign.status_code == 403


@pytest.mark.parametrize("change, field", [
    ({"name": "Bad Name"}, "name"),
    ({"name": ""}, "name"),
    ({"goal": "short"}, "goal"),
    ({"color": "red"}, "color"),
    ({"tools": ["nonexistent.tool"]}, "tools"),
    ({"mode": "chaos"}, "mode"),
])
def test_invalid_forms_name_the_field(client, change, field):
    r = post(client, "/api/hire/preview", {**FORM, **change})
    assert r.status_code == 422
    body = r.json()
    assert isinstance(body["detail"], str) and body["errors"][0]["field"] == field


def test_unknown_form_fields_are_refused(client):
    assert post(client, "/api/hire/preview", {**FORM, "shell": True}).status_code == 422


def test_a_tool_without_its_folder_is_refused(client):
    r = post(client, "/api/hire/preview", {**FORM, "fs_read": []})
    assert r.status_code == 422 and "fs_read" in r.json()["detail"]


def test_folders_without_a_tool_that_needs_them_are_dropped(client):
    form = {**FORM, "tools": [], "fs_read": ["./sandbox"], "fs_write": ["./out"], "network": ["example.com"]}
    data = post(client, "/api/hire/preview", form).json()
    assert "fs_read: []" in data["yaml"] and "fs_write: []" in data["yaml"] and "network: []" in data["yaml"]
    assert data["warnings"] == []


def test_hiring_saves_the_spec_and_the_agent_appears(client, world):
    r = post(client, "/api/hire", FORM)
    assert r.status_code == 200
    assert r.json()["name"] == "note-helper" and r.json()["file"] == "note-helper.yaml"
    assert (world / "specs" / "note-helper.yaml").is_file()
    listed = client.get("/api/agents").json()["agents"][0]
    assert listed["display_name"] == "Note Helper" and listed["color"] == "#2ec4a0" and listed["hair"] == "#a03a6a"


def test_hiring_never_overwrites_an_existing_agent(client, world):
    assert post(client, "/api/hire", FORM).status_code == 200
    before = (world / "specs" / "note-helper.yaml").read_text()
    again = post(client, "/api/hire", {**FORM, "goal": "A completely different goal here."})
    assert again.status_code == 409 and "already exists" in again.json()["detail"]
    assert (world / "specs" / "note-helper.yaml").read_text() == before
    assert post(client, "/api/hire/preview", FORM).json()["exists"] is True


def test_a_name_used_by_another_file_is_also_taken(client, world):
    spec = (world / "specs" / "other.yaml")
    spec.write_text('name: note-helper\ngoal: "Some other agent in some other file"\n')
    assert post(client, "/api/hire", FORM).status_code == 409
    assert not (world / "specs" / "note-helper.yaml").exists()


def test_agents_without_an_appearance_still_load(client, world):
    (world / "specs" / "old.yaml").write_text('name: old-timer\ngoal: "An agent from before the hiring form"\n')
    agent = client.get("/api/agents").json()["agents"][0]
    assert agent["display_name"] == "" and agent["color"] == "" and agent["hair"] == ""


DRAFT = {
    "name": "cpp-tutor", "goal": "Teach me C++ memory management.", "system_prompt": "You teach C++ patiently.",
    "mode": "conversational", "tools": ["fs.list"], "fs_read": ["./sandbox"], "fs_write": [], "network": [],
    "trigger_type": "manual",
}


def test_draft_fills_the_form_from_a_description(client, monkeypatch):
    provider = MockProvider([LLMResponse(content=json.dumps(DRAFT))])
    monkeypatch.setattr(server, "make_provider", lambda cfg: provider)
    r = post(client, "/api/hire/draft", {"description": "Teach me C++ memory management."})
    assert r.status_code == 200
    fields = r.json()["fields"]
    assert fields["name"] == "cpp-tutor" and fields["tools"] == ["fs.list"] and fields["fs_read"] == ["./sandbox"]
    assert "Teach me C++" in provider.calls[0]["messages"][1]["content"]


def test_draft_needs_a_real_description(client):
    assert post(client, "/api/hire/draft", {"description": "hi"}).status_code == 422
    assert post(client, "/api/hire/draft", {"description": "x" * 2001}).status_code == 422


def test_draft_reports_a_model_that_is_down(client, monkeypatch):
    def broken(cfg):
        raise ProviderError("Ollama is not running")

    monkeypatch.setattr(server, "make_provider", broken)
    r = post(client, "/api/hire/draft", {"description": "Teach me C++ memory management."})
    assert r.status_code == 503 and "Ollama is not running" in r.json()["detail"]


def test_draft_gives_up_politely_on_junk(client, monkeypatch):
    provider = MockProvider([LLMResponse(content="not json")] * 3)
    monkeypatch.setattr(server, "make_provider", lambda cfg: provider)
    r = post(client, "/api/hire/draft", {"description": "Teach me C++ memory management."})
    assert r.status_code == 422 and "could not turn that" in r.json()["detail"]
