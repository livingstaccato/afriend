"""What a provider says it offers, asked rather than assumed.

The listing exists to be quoted back at an operator picking a replacement
for a provider that ran out of quota. A name afriend invented would be
accepted here and rejected at dispatch, so every path either reports what
the CLI actually printed or reports that it could not be asked.
"""

import subprocess

import pytest

from afriend.adapters import load_adapters
from afriend.errors import UsageError
from afriend.models import MAX_MODELS, list_models, resolve_provider
from afriend.paths import ADAPTER_DIR


def _adapter(tmp_path, name="lister", fmt="lines", argv='["models"]'):
    (tmp_path / f"{name}.toml").write_text(
        f'name = "{name}"\nbinary = "{name}"\nexternal_tools = "none"\n'
        f"models_argv = {argv}\n"
        f'models_format = "{fmt}"\n'
    )
    return load_adapters(tmp_path)[name]


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=["x"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_a_provider_with_no_listing_command_reports_that_it_has_none():
    """codex. Reporting "none" is the point: a guess would be worse than
    silence, because it would be acted on."""
    answer = list_models(load_adapters(ADAPTER_DIR)["codex"])

    assert answer.supported is False
    assert answer.models == ()
    assert answer.error is None


def test_line_format_takes_each_whole_line(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed("opencode/a\nopencode/b\n\n"))
    answer = list_models(_adapter(tmp_path))

    assert answer.models == ("opencode/a", "opencode/b")


def test_tsv_format_skips_the_clis_own_chatter(monkeypatch, tmp_path):
    """agy prints "Fetching available models..." before the table. It has no
    tab, which is exactly what distinguishes prose from a row."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _completed(
            "Fetching available models...\ngemini-a\tGemini A\ngemini-b\tGemini B\n"
        ),
    )
    answer = list_models(_adapter(tmp_path, fmt="tsv"))

    assert answer.models == ("gemini-a", "gemini-b")


def test_tsv_skips_a_tabless_line_even_when_it_looks_like_an_id(monkeypatch, tmp_path):
    """Isolates the tab rule from the whitespace rule. "Fetching available
    models..." is dropped by either one, so a single-token tabless line is
    what proves the format check is doing anything."""
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _completed("Loading...\ngemini-a\tGemini A\n")
    )
    answer = list_models(_adapter(tmp_path, fmt="tsv"))

    assert answer.models == ("gemini-a",)


def test_a_line_format_never_yields_an_id_with_whitespace_in_it(monkeypatch, tmp_path):
    """Prose that reached the parser is dropped rather than offered as a
    model id -- the whole risk being a name that fails at dispatch."""
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _completed("Fetching models...\nreal-model\n")
    )
    answer = list_models(_adapter(tmp_path))

    assert answer.models == ("real-model",)


def test_duplicates_are_reported_once(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed("a\nb\na\n"))

    assert list_models(_adapter(tmp_path)).models == ("a", "b")


def test_a_runaway_listing_is_capped(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _completed("\n".join(f"m{i}" for i in range(MAX_MODELS * 2))),
    )

    assert len(list_models(_adapter(tmp_path)).models) == MAX_MODELS


def test_a_missing_executable_is_reported_not_raised(monkeypatch, tmp_path):
    def boom(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", boom)
    answer = list_models(_adapter(tmp_path))

    assert answer.supported is True
    assert answer.models == ()
    assert answer.error is not None and "not installed" in answer.error


def test_a_hung_listing_times_out_rather_than_holding_the_answer(monkeypatch, tmp_path):
    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(subprocess, "run", boom)
    answer = list_models(_adapter(tmp_path), timeout_s=1)

    assert answer.error is not None and "timed out" in answer.error


def test_a_failing_listing_reports_the_clis_last_word(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _completed(stderr="not logged in\n", returncode=1)
    )
    answer = list_models(_adapter(tmp_path))

    assert answer.models == ()
    assert answer.error == "not logged in"


def test_output_with_nothing_recognizable_is_an_error_not_an_empty_success(monkeypatch, tmp_path):
    """An empty tuple with no error would read as "this provider offers no
    models", which is a different and false claim."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed("some prose here\n"))
    answer = list_models(_adapter(tmp_path))

    assert answer.models == ()
    assert answer.error is not None and "no recognizable" in answer.error


def test_an_unknown_provider_is_named_along_with_the_known_ones():
    registry = load_adapters(ADAPTER_DIR)
    with pytest.raises(UsageError, match="unknown provider 'nope'"):
        resolve_provider(registry, "nope")


def test_the_shipped_adapters_declare_only_supported_formats():
    for name, adapter in load_adapters(ADAPTER_DIR).items():
        assert adapter.models_format in {"lines", "tsv"}, name
        if adapter.models_argv:
            assert adapter.models_argv[0], name


def test_a_listing_gets_the_same_filtered_environment_a_friend_would(monkeypatch, tmp_path):
    """A listing is a convenience command, not an exemption. It used to
    inherit the parent's whole environment, handing a provider CLI every
    variable that adapter's `env.pass` deliberately withholds during a
    review -- and no run record mentioned it, because no run was involved."""
    captured: dict[str, object] = {}

    def fake_run(*_a, **kwargs):
        captured.update(kwargs)
        return _completed("model-a\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("A_PRIVATE_TOKEN", "secret")
    list_models(_adapter(tmp_path))

    assert "A_PRIVATE_TOKEN" not in captured["env"]


def test_a_listing_is_never_handed_the_operators_terminal(monkeypatch, tmp_path):
    """A CLI that decides to prompt would otherwise block for the whole
    timeout, or eat keystrokes meant for afriend."""
    captured: dict[str, object] = {}

    def fake_run(*_a, **kwargs):
        captured.update(kwargs)
        return _completed("model-a\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    list_models(_adapter(tmp_path))

    assert captured["stdin"] == subprocess.DEVNULL


def test_a_provider_with_no_executable_is_not_exec_ed(monkeypatch, tmp_path):
    """ollama is the HTTP transport and declares `binary = ""`. Declaring
    models_argv for it would exec the empty string."""
    calls: list[object] = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or _completed())
    (tmp_path / "http.toml").write_text(
        'name = "http"\nbinary = ""\nexternal_tools = "none"\nmodels_argv = ["models"]\n'
    )
    answer = list_models(load_adapters(tmp_path)["http"])

    assert calls == []
    assert answer.error is not None and "no executable" in answer.error
