"""settings.yaml: the default model and how many agents may think at once."""
import pytest

from factory.schema import AgentSpec
from factory.settings import Settings, load_settings, memory_warnings, model_for


def test_no_file_means_the_defaults(tmp_path):
    settings, error = load_settings(tmp_path / "settings.yaml", env={})
    assert (settings.default_model, settings.max_parallel, settings.keep_alive, error) == ("qwen3:8b", 2, "30m", "")


def test_a_valid_file_is_used(tmp_path):
    (tmp_path / "settings.yaml").write_text("default_model: qwen3:4b-instruct\nmax_parallel: 2\n")
    settings, error = load_settings(tmp_path / "settings.yaml", env={})
    assert (settings.default_model, settings.max_parallel, error) == ("qwen3:4b-instruct", 2, "")


@pytest.mark.parametrize("text, where", [
    ("max_parallel: 4\n", "max_parallel"), ("max_parallel: 0\n", "max_parallel"),
    ("max_paralel: 2\n", "max_paralel"), ("default_model: ''\n", "default_model"), (": : :\n", "could not be read"),
])
def test_a_broken_file_falls_back_to_the_defaults_and_says_why(tmp_path, text, where):
    (tmp_path / "settings.yaml").write_text(text)
    settings, error = load_settings(tmp_path / "settings.yaml", env={})
    assert settings == Settings() and where in error


def test_a_spec_that_names_a_model_keeps_it_and_one_that_does_not_gets_the_default():
    settings = Settings(default_model="qwen3:4b-instruct")
    named = AgentSpec.model_validate({"name": "light-agent", "goal": "Answer short questions", "model": {"name": "llama3.2"}})
    plain = AgentSpec.model_validate({"name": "plain-agent", "goal": "Answer short questions", "model": {"temperature": 0.5}})
    bare = AgentSpec.model_validate({"name": "bare-agent", "goal": "Answer short questions"})
    assert model_for(named.model, settings)[0].name == "llama3.2" and model_for(named.model, settings)[1] == "spec"
    cfg, source = model_for(plain.model, settings)
    assert (cfg.name, cfg.temperature, source) == ("qwen3:4b-instruct", 0.5, "default")
    assert model_for(bare.model, settings) [0].name == "qwen3:4b-instruct"


def test_the_settings_file_that_ships_is_valid():
    from pathlib import Path
    path = Path(__file__).parent.parent / "settings.yaml"
    if not path.exists():
        pytest.skip("settings.yaml was removed by the user")
    settings, error = load_settings(path, env={})
    assert error == "" and 1 <= settings.max_parallel <= 3


def test_the_environment_variable_overrides_the_file(tmp_path):
    (tmp_path / "settings.yaml").write_text("max_parallel: 1\n")
    settings, error = load_settings(tmp_path / "settings.yaml", env={"AGENTFACTORY_MAX_PARALLEL": "3"})
    assert settings.max_parallel == 3 and error == ""


@pytest.mark.parametrize("value", ["4", "0", "two"])
def test_a_bad_environment_variable_is_refused(tmp_path, value):
    settings, error = load_settings(tmp_path / "settings.yaml", env={"AGENTFACTORY_MAX_PARALLEL": value})
    assert settings.max_parallel == 2 and "max_parallel" in error


def test_too_much_context_for_a_16gb_mac_is_warned_about():
    assert memory_warnings(Settings(max_parallel=2), {"qwen3:8b": 8192}) == []
    warning = memory_warnings(Settings(max_parallel=3), {"qwen3:8b": 8192})
    assert len(warning) == 1 and "24,576" in warning[0]
    assert memory_warnings(Settings(max_parallel=1), {"qwen3:8b": 32768}) == []  # one slot: just a big context
