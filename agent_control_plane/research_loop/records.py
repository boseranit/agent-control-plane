from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

GateDirection = Literal["above", "below"]
HypothesisStatus = Literal[
    "ready-to-run",
    "needs-data",
    "survived",
    "killed",
    "inconclusive",
]
Verdict = Literal["survived", "killed", "inconclusive"]

_EXP_RE = re.compile(r"EXP-(\d{4})")


class SliceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    baseline_choice: str
    alternative: str


class GateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: str
    threshold: float
    direction: GateDirection


class ExperimentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    exp_id: str
    hypothesis_id: str
    slice: SliceSpec
    gate: GateSpec
    control_null: str
    power_note: str
    seed: int
    data_range: dict[str, Any]
    allowed_write_paths: list[str] = Field(default_factory=list)


class Scorecard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ic: float
    rank_ic: float
    sharpe: float
    coverage: float


class AdversaryFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lens: str
    killed: bool
    reason: str
    evidence: Optional[str] = None


class ExperimentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exp_id: str
    hypothesis_id: str
    ran_ok: bool
    gate_metric: str
    gate_value: float
    gate_threshold: float
    gate_direction: GateDirection
    n_units: int
    null_p: float = Field(ge=0, le=1)
    null_method: str
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None
    metrics: Scorecard
    seed: int
    data_range: dict[str, Any]
    artifacts: dict[str, str] = Field(default_factory=dict)
    error: Optional[str] = None
    notes: Optional[str] = None
    looks_positive: Optional[bool] = None
    adversary: list[AdversaryFinding] = Field(default_factory=list)
    bh_adjusted_p: Optional[float] = None
    verdict: Optional[Verdict] = None


class HypothesisFrontmatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    slug: str
    status: HypothesisStatus
    experiments: list[str] = Field(default_factory=list)


class HypothesisDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frontmatter: HypothesisFrontmatter
    body: str


def record_root(repo: Path, slug: str) -> Path:
    return Path(repo) / "eda" / slug


def ensure_record_tree(repo: Path, slug: str) -> Path:
    root = record_root(repo, slug)
    for name in ("hypotheses", "experiments", "results"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def experiment_spec_path(root: Path, exp_id: str) -> Path:
    return Path(root) / "experiments" / f"{exp_id}-spec.json"


def experiment_run_path(root: Path, exp_id: str) -> Path:
    return Path(root) / "experiments" / f"{exp_id}-run.py"


def experiment_result_path(root: Path, exp_id: str) -> Path:
    return Path(root) / "results" / f"{exp_id}-result.json"


def hypothesis_path(root: Path, doc: HypothesisDoc) -> Path:
    frontmatter = doc.frontmatter
    return Path(root) / "hypotheses" / f"{frontmatter.id}-{frontmatter.slug}.md"


def write_experiment_spec(root: Path, spec: ExperimentSpec) -> Path:
    path = experiment_spec_path(root, spec.exp_id)
    _write_model_json(path, spec)
    return path


def read_experiment_spec(root: Path, exp_id: str) -> ExperimentSpec:
    return ExperimentSpec.model_validate_json(
        experiment_spec_path(root, exp_id).read_text(encoding="utf-8")
    )


def write_experiment_result(root: Path, result: ExperimentResult) -> Path:
    path = experiment_result_path(root, result.exp_id)
    _write_model_json(path, result)
    return path


def read_experiment_result(root: Path, exp_id: str) -> ExperimentResult:
    return ExperimentResult.model_validate_json(
        experiment_result_path(root, exp_id).read_text(encoding="utf-8")
    )


def read_experiment_results(root: Path) -> list[ExperimentResult]:
    results: list[ExperimentResult] = []
    for path in sorted((Path(root) / "results").glob("EXP-*-result.json")):
        exp_id = path.name.removesuffix("-result.json")
        results.append(read_experiment_result(root, exp_id))
    return results


def write_hypothesis(root: Path, doc: HypothesisDoc) -> Path:
    path = hypothesis_path(root, doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = yaml.safe_dump(
        doc.frontmatter.model_dump(mode="json"),
        sort_keys=False,
    )
    path.write_text(f"---\n{frontmatter}---\n{doc.body}", encoding="utf-8")
    return path


def read_hypothesis(path: Path) -> HypothesisDoc:
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"hypothesis file is missing frontmatter: {path}")
    _, frontmatter_text, body = text.split("---", 2)
    frontmatter = HypothesisFrontmatter.model_validate(
        yaml.safe_load(frontmatter_text) or {}
    )
    return HypothesisDoc(frontmatter=frontmatter, body=body.lstrip("\n"))


def find_hypothesis(root: Path, hypothesis_id: str) -> tuple[Path, HypothesisDoc]:
    for path in sorted((Path(root) / "hypotheses").glob(f"{hypothesis_id}-*.md")):
        return path, read_hypothesis(path)
    raise FileNotFoundError(f"no hypothesis record for {hypothesis_id}")


def iter_experiment_ids(root: Path) -> list[str]:
    ids: set[str] = set()
    for directory in (Path(root) / "experiments", Path(root) / "results"):
        if not directory.exists():
            continue
        for path in directory.iterdir():
            exp_id = _exp_id_from_name(path.name)
            if exp_id is not None:
                ids.add(exp_id)
    return sorted(ids)


def next_experiment_id(root: Path) -> str:
    max_seen = 0
    for exp_id in iter_experiment_ids(root):
        match = _EXP_RE.fullmatch(exp_id)
        if match:
            max_seen = max(max_seen, int(match.group(1)))
    return f"EXP-{max_seen + 1:04d}"


def ready_hypotheses(root: Path) -> list[HypothesisDoc]:
    hypothesis_dir = Path(root) / "hypotheses"
    if not hypothesis_dir.exists():
        return []
    docs = [read_hypothesis(path) for path in sorted(hypothesis_dir.glob("H*.md"))]
    return [doc for doc in docs if doc.frontmatter.status == "ready-to-run"]


def _write_model_json(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump(mode="json", exclude_none=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _exp_id_from_name(name: str) -> Optional[str]:
    match = _EXP_RE.search(name)
    if match is None:
        return None
    return f"EXP-{int(match.group(1)):04d}"
