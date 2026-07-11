from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MirrorRequest:
    research_run_id: str
    exp_id: str
    record_root: Path
    result_path: Path
    spec_path: Path
    run_path: Path
    hypothesis_path: Path
    tracking_uri: Optional[str] = None
    experiment_name: Optional[str] = None
    git_sha: Optional[str] = None


@runtime_checkable
class Mirror(Protocol):
    def mirror(self, request: MirrorRequest) -> None: ...


class NoOpMirror:
    def mirror(self, request: MirrorRequest) -> None:
        return None


def mirror_experiment(
    mirror: Mirror,
    request: MirrorRequest,
    *,
    logger: logging.Logger = LOGGER,
) -> None:
    try:
        mirror.mirror(request)
    except Exception as exc:  # noqa: BLE001 - external reflection must not fail the run
        logger.warning("mirror failed for %s: %s", request.exp_id, exc)
