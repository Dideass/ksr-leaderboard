from __future__ import annotations

from dataclasses import dataclass

from .models import BenchmarkSpec, Observation


@dataclass(slots=True, frozen=True)
class NormalizedObservation:
    observation: Observation
    score: float
    ci_low: float | None
    ci_high: float | None


def _as_proportion(value: float) -> float:
    if -1.0 <= value <= 1.0:
        return value
    return value / 100.0


def fixed_endpoint_score(raw_score: float, baseline: float = 0.0) -> float:
    score = _as_proportion(raw_score)
    if baseline >= 1:
        raise ValueError("chance baseline must be below 1")
    normalized = 100.0 * (score - baseline) / (1.0 - baseline)
    return max(0.0, min(100.0, normalized))


def normalize_value(value: float, spec: BenchmarkSpec) -> float:
    if spec.special_transform == "omniscience_floor_zero":
        published = value * 100.0 if -1.0 <= value <= 1.0 else value
        return max(0.0, min(100.0, published))
    return fixed_endpoint_score(value, spec.chance_baseline)


def normalize_observation(
    observation: Observation, spec: BenchmarkSpec
) -> NormalizedObservation:
    score = normalize_value(observation.raw_score, spec)
    low = (
        normalize_value(observation.ci_low, spec)
        if observation.ci_low is not None
        else None
    )
    high = (
        normalize_value(observation.ci_high, spec)
        if observation.ci_high is not None
        else None
    )
    if low is not None and high is not None and low > high:
        raise ValueError(f"invalid interval for {observation.model_id}/{spec.id}")
    return NormalizedObservation(observation, score, low, high)

