from __future__ import annotations

from pathlib import Path


def research_command_env(
    *,
    data_root: str | Path | None,
    experiment_data_root: str | Path | None,
    run_dir: str | Path,
    repo_root: str | Path | None,
) -> dict[str, str]:
    env: dict[str, str] = {"RESEARCH_RUN_DIR": str(Path(run_dir).resolve())}
    if data_root is not None:
        resolved_data_root = str(Path(data_root).expanduser().resolve())
        env["RESEARCH_DATA_ROOT"] = resolved_data_root
        env["HLM_DATA_ROOT"] = resolved_data_root
    if experiment_data_root is not None:
        path = Path(experiment_data_root).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        env["RESEARCH_EXPERIMENT_DATA_ROOT"] = str(path)
    if repo_root is not None:
        env["RESEARCH_REPO_ROOT"] = str(Path(repo_root).resolve())
    return env
