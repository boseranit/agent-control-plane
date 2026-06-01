from __future__ import annotations

import runpy
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from agent_control_plane.research_experiment_controller import cli
from agent_control_plane.research_experiment_controller.cli import main
from agent_control_plane.research_experiment_controller.durable_shell import (
    ResearchRunInput,
)


def write_research_run_spec(tmp_path: Path, repo: Path) -> Path:
    init_repo(repo)
    data_root = tmp_path / "data"
    data_root.mkdir()
    spec_path = tmp_path / "research-run.yaml"
    spec_path.write_text(
        f"""
research_run_id: cli-run
target_repository: {repo}
max_experiments: 1
research_brief: |
  Test CLI start path.
budget: smoke
budgets:
  smoke:
    month_start: "2026-01"
    month_end: "2026-01"
    max_runtime_minutes: 5
data_root: {data_root}
""",
        encoding="utf-8",
    )
    return spec_path


def init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)


def test_cli_run_starts_research_run_under_runtime_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    spec_path = write_research_run_spec(tmp_path, repo)
    runtime_root = tmp_path / "runs"

    exit_code = main(["run", str(spec_path), "--runtime-root", str(runtime_root)])

    assert exit_code == 0
    run_directory = runtime_root / "cli-run"
    assert (run_directory / "research_run_spec.yaml").exists()
    assert (run_directory / "state.json").exists()
    assert "Started Research Run: cli-run" in capsys.readouterr().out


def test_cli_resume_delegates_to_durable_shell_with_runtime_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[ResearchRunInput] = []

    async def fake_shell(input: ResearchRunInput) -> dict[str, object]:
        seen.append(input)
        return {"status": "completed", "research_run_id": input.research_run_id}

    monkeypatch.setattr(cli, "run_research_shell", fake_shell)

    exit_code = main(
        ["resume", "existing-run", "--runtime-root", str(tmp_path / "runs")]
    )

    assert exit_code == 0
    assert seen == [
        ResearchRunInput(
            research_run_id="existing-run",
            runtime_root=str(tmp_path / "runs"),
        )
    ]
    assert "Resumed Research Run: existing-run" in capsys.readouterr().out


def test_cli_run_requires_spec_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["run"])

    assert exc_info.value.code == 2
    assert "research_run_spec_path" in capsys.readouterr().err


def test_cli_resume_requires_research_run_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["resume"])

    assert exc_info.value.code == 2
    assert "research_run_id" in capsys.readouterr().err


def test_cli_resume_rejects_extra_args(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["resume", "cli-run", "replacement.yaml"])

    assert exc_info.value.code == 2
    assert "unrecognized arguments: replacement.yaml" in capsys.readouterr().err


def test_cli_run_spec_errors_return_1_with_stderr(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "run",
            str(tmp_path / "missing.yaml"),
            "--runtime-root",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "error:" in captured.err
    assert "missing.yaml" in captured.err


def test_module_entrypoint_delegates_to_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[object] = []

    def fake_main(argv: object = None) -> int:
        called.append(argv)
        return 23

    monkeypatch.setattr(cli, "main", fake_main)
    monkeypatch.setattr(sys, "argv", ["python", "resume", "cli-run"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module(
            "agent_control_plane.research_experiment_controller",
            run_name="__main__",
        )

    assert exc_info.value.code == 23
    assert called == [None]


def test_cli_imports_no_hatchet_or_mlflow_and_pixi_worker_task_exists() -> None:
    cli_source = Path(cli.__file__).read_text(encoding="utf-8")
    assert "hatchet_sdk" not in cli_source
    assert "mlflow" not in cli_source

    pixi = tomllib.loads(Path("pixi.toml").read_text(encoding="utf-8"))
    tasks = pixi["feature"]["dev"]["tasks"]
    assert tasks["research-experiment-worker"] == (
        "python -m agent_control_plane.research_experiment_controller.hatchet_worker"
    )
