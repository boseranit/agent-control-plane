from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


DEFAULT_MATERIAL_CATEGORIES: tuple[str, ...] = (
    "target",
    "label",
    "universe",
    "data_source",
    "feature_family",
    "split",
    "primary_metric",
    "success_gate",
    "baseline_set",
    "transaction_cost_model",
    "holding_period",
    "rebalance_frequency",
    "neutralization_policy",
)


@dataclass(frozen=True)
class MaterialRevisionDecision:
    requires_fresh_critic: bool
    material_categories: list[str]
    controller_detected_categories: list[str]
    agent_declared_categories: list[str]


_CATEGORY_ALIASES: dict[str, str] = {
    "data_sources": "data_source",
    "source": "data_source",
    "signal_family": "feature_family",
    "splits": "split",
    "primary": "primary_metric",
    "success_gates": "success_gate",
    "baseline": "baseline_set",
    "baselines": "baseline_set",
    "baseline_sets": "baseline_set",
    "transaction_cost_assumption": "transaction_cost_model",
    "transaction_cost_assumptions": "transaction_cost_model",
    "transaction_costs": "transaction_cost_model",
    "cost_model": "transaction_cost_model",
    "prediction_horizon": "holding_period",
    "horizon": "holding_period",
    "rebalancing_frequency": "rebalance_frequency",
    "neutralisation_policy": "neutralization_policy",
}

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "target": ("target",),
    "label": ("label",),
    "universe": ("universe",),
    "data_source": ("data_source", "data_sources", "source"),
    "feature_family": ("feature_family", "signal_family"),
    "split": ("split", "splits"),
    "primary_metric": ("primary_metric", "primary"),
    "success_gate": ("success_gate", "success_gates"),
    "baseline_set": ("baseline_set", "baseline_sets", "baseline", "baselines"),
    "transaction_cost_model": (
        "transaction_cost_model",
        "transaction_cost_assumption",
        "transaction_cost_assumptions",
        "transaction_costs",
        "cost_model",
    ),
    "holding_period": ("holding_period", "prediction_horizon", "horizon"),
    "rebalance_frequency": ("rebalance_frequency", "rebalancing_frequency"),
    "neutralization_policy": (
        "neutralization_policy",
        "neutralisation_policy",
    ),
}

_MISSING = object()


def assess_material_revision(
    before: Any,
    after: Any,
    *,
    agent_declared_categories: Sequence[str] = (),
    material_fields: Sequence[str] | None = None,
) -> MaterialRevisionDecision:
    before_data = _normalized_mapping(before)
    after_data = _normalized_mapping(after)
    material_categories = _material_categories(material_fields)
    controller_detected = [
        category
        for category in material_categories
        if _material_value(before_data, category) != _material_value(
            after_data, category
        )
    ]
    agent_declared = _normalize_agent_categories(agent_declared_categories)
    categories = _ordered_unique([*controller_detected, *agent_declared])
    return MaterialRevisionDecision(
        requires_fresh_critic=bool(categories),
        material_categories=categories,
        controller_detected_categories=controller_detected,
        agent_declared_categories=agent_declared,
    )


def requires_fresh_critic(
    before: Any,
    after: Any,
    *,
    agent_declared_categories: Sequence[str] = (),
    material_fields: Sequence[str] | None = None,
) -> bool:
    return assess_material_revision(
        before,
        after,
        agent_declared_categories=agent_declared_categories,
        material_fields=material_fields,
    ).requires_fresh_critic


def _normalized_mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        raise TypeError("Material revision assessment requires mappings or models.")
    return {_normalize_category(str(key)): item for key, item in value.items()}


def _material_value(data: Mapping[str, Any], category: str) -> Any:
    for alias in _FIELD_ALIASES.get(category, (category,)):
        value = data.get(_normalize_category(alias), _MISSING)
        if value is not _MISSING:
            return value
    return _MISSING


def _material_categories(material_fields: Sequence[str] | None) -> list[str]:
    if material_fields is None:
        return list(DEFAULT_MATERIAL_CATEGORIES)
    return _ordered_unique(
        normalized
        for field in material_fields
        if (normalized := _normalize_category(str(field)))
    )


def _normalize_agent_categories(categories: Sequence[str]) -> list[str]:
    return _ordered_unique(
        normalized
        for category in categories
        if (normalized := _normalize_category(str(category)))
    )


def _normalize_category(value: str) -> str:
    normalized = "_".join(value.strip().lower().replace("-", " ").split())
    return _CATEGORY_ALIASES.get(normalized, normalized)


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
