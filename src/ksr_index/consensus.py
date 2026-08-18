from __future__ import annotations

import math
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from .config import IndexConfig
from .identity import _is_product_max_tier
from .models import Observation, ScoreRow
from .normalization import NormalizedObservation, normalize_observation


@dataclass(slots=True, frozen=True)
class PairwiseResult:
    rows: list[ScoreRow]
    diagnostics: dict[str, object]


def _selection_key(item: NormalizedObservation) -> tuple[object, ...]:
    observation = item.observation
    return (
        observation.reasoning_priority,
        observation.source_priority,
        observation.date_key,
        observation.retrieved_at,
        observation.source_id,
    )


def select_model_observations(
    observations: Iterable[Observation], config: IndexConfig
) -> dict[str, dict[str, NormalizedObservation]]:
    """Select one row per model and benchmark without looking at its score.

    The model entity is the frozen family ID.  Reasoning effort has first priority,
    then source authority and date.  This implements the public rule that a model
    appears once and that the highest available native no-tool effort is used.
    """

    active = {spec.id: spec for spec in config.active()}
    grouped: dict[tuple[str, str], list[NormalizedObservation]] = defaultdict(list)
    for observation in observations:
        spec = active.get(observation.benchmark_id)
        if spec is None or not observation.is_eligible_native_no_tool():
            continue
        grouped[(observation.family_id, observation.benchmark_id)].append(
            normalize_observation(observation, spec)
        )
    selected: dict[str, dict[str, NormalizedObservation]] = defaultdict(dict)
    for (family_id, benchmark_id), candidates in grouped.items():
        selected[family_id][benchmark_id] = max(candidates, key=_selection_key)
    return dict(selected)


def _clean_display_name(value: str) -> str:
    name = re.sub(r"\s*\(snapshot\s+\d{4}-\d{2}-\d{2}\).*", "", value).strip()
    name = re.sub(r"\s*\[[^\]]+\]\s*$", "", name).strip()
    keep_product_max = _is_product_max_tier(name)
    if keep_product_max:
        name = re.sub(
            r"\s+(default|low|medium|high|xhigh)(?:\s+effort)?$",
            "",
            name,
            flags=re.IGNORECASE,
        ).strip()
        name = re.sub(r"\s+max\s+effort$", "", name, flags=re.IGNORECASE).strip()
    else:
        name = re.sub(
            r"\s+(default|low|medium|high|xhigh|max)(?:\s+effort)?$",
            "",
            name,
            flags=re.IGNORECASE,
        ).strip()
    return name or value


def _model_metadata(
    family_id: str, by_benchmark: dict[str, NormalizedObservation]
) -> tuple[str, str, str, Observation]:
    observations = [item.observation for item in by_benchmark.values()]
    provider = Counter(item.provider for item in observations).most_common(1)[0][0]
    names = [_clean_display_name(item.display_name or item.model_id) for item in observations]
    display_name = sorted(
        Counter(names).items(), key=lambda item: (-item[1], len(item[0]), item[0])
    )[0][0]
    stable_dates = [
        item.endpoint_date[:10]
        for item in observations
        if item.endpoint_date and not item.mutable_alias
    ]
    if stable_dates:
        release_date = sorted(
            Counter(stable_dates).items(), key=lambda item: (-item[1], item[0])
        )[0][0]
    else:
        release_date = max(
            (item.endpoint_date[:10] for item in observations if item.endpoint_date),
            default="",
        )
    representative = max(
        observations,
        key=lambda item: (
            item.reasoning_priority,
            item.date_key,
            item.source_priority,
            item.retrieved_at,
        ),
    )
    return display_name, provider, release_date, representative


def _intervals_overlap(
    first: NormalizedObservation, second: NormalizedObservation
) -> bool:
    if math.isclose(first.score, second.score, abs_tol=1e-12):
        return True
    return bool(
        first.ci_low is not None
        and first.ci_high is not None
        and second.ci_low is not None
        and second.ci_high is not None
        and first.ci_low <= second.ci_high
        and second.ci_low <= first.ci_high
    )


def _entry_profile(
    by_benchmark: dict[str, NormalizedObservation], config: IndexConfig
) -> dict[str, object]:
    specs = {spec.id: spec for spec in config.active()}
    benchmark_ids = set(by_benchmark)
    coverage = sum(specs[benchmark_id].weight_index for benchmark_id in benchmark_ids)
    dimensions = {specs[benchmark_id].dimension for benchmark_id in benchmark_ids}
    evidence_families = {
        specs[benchmark_id].source_platform for benchmark_id in benchmark_ids
    }
    groups = {
        group["id"]: bool(benchmark_ids.intersection(group["benchmarks"]))
        for group in config.settings.get("entry_groups", [])
    }
    return {
        "coverage": coverage,
        "benchmarks": len(benchmark_ids),
        "dimensions": len(dimensions),
        "evidence_families": len(evidence_families),
        "groups": groups,
    }


def _anchor_match_count(
    family_id: str,
    selected: dict[str, dict[str, NormalizedObservation]],
    anchors: list[str],
) -> int:
    own = set(selected[family_id])
    return sum(
        1
        for anchor in anchors
        if anchor != family_id
        and anchor in selected
        and own.intersection(selected[anchor])
    )


def _base_eligible(profile: dict[str, object], config: IndexConfig) -> bool:
    settings = config.settings
    return bool(
        float(profile["coverage"]) + 1e-12
        >= float(settings["entry_min_coverage"])
        and int(profile["benchmarks"]) >= int(settings["entry_min_benchmarks"])
        and int(profile["dimensions"]) >= int(settings["entry_min_dimensions"])
        and all(bool(value) for value in dict(profile["groups"]).values())
    )


def _connected_to_anchor(
    family_id: str,
    adjacency: dict[str, set[str]],
    anchors: set[str],
) -> bool:
    queue: deque[str] = deque([family_id])
    seen = {family_id}
    while queue:
        current = queue.popleft()
        if current in anchors:
            return True
        for neighbor in adjacency.get(current, set()):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return False


def _fit_bradley_terry(
    entity_ids: list[str], comparisons: list[tuple[int, int, float, float]], sigma: float
) -> tuple[np.ndarray, np.ndarray]:
    count = len(entity_ids)

    def objective(values: np.ndarray) -> tuple[float, np.ndarray]:
        loss = 0.5 * float(np.dot(values, values)) / (sigma * sigma)
        gradient = values / (sigma * sigma)
        for first, second, outcome, weight in comparisons:
            difference = values[first] - values[second]
            probability = float(expit(difference))
            loss += weight * (float(np.logaddexp(0.0, difference)) - outcome * difference)
            residual = weight * (probability - outcome)
            gradient[first] += residual
            gradient[second] -= residual
        return loss, gradient

    fitted = minimize(
        fun=lambda values: objective(values)[0],
        x0=np.zeros(count, dtype=float),
        jac=lambda values: objective(values)[1],
        method="L-BFGS-B",
        options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-9},
    )
    if not fitted.success or not np.all(np.isfinite(fitted.x)):
        raise RuntimeError(f"Bradley–Terry fit failed: {fitted.message}")
    values = np.asarray(fitted.x, dtype=float)
    hessian = np.eye(count, dtype=float) / (sigma * sigma)
    for first, second, _outcome, weight in comparisons:
        probability = float(expit(values[first] - values[second]))
        curvature = weight * probability * (1.0 - probability)
        hessian[first, first] += curvature
        hessian[second, second] += curvature
        hessian[first, second] -= curvature
        hessian[second, first] -= curvature
    covariance = np.linalg.pinv(hessian, hermitian=True)
    return values, covariance


def _confidence_label(profile: dict[str, object], config: IndexConfig) -> str:
    """Label evidence completeness, not the width of a saturated BT interval.

    The 0–100 score standard error inflates for complete, dominant models
    because decisive wins add almost no Hessian curvature. Coverage is the
    quantity the page means by completeness.
    """
    settings = config.settings
    coverage = float(profile["coverage"])
    benches = int(profile["benchmarks"])
    if (
        coverage + 1e-12 >= float(settings.get("confidence_high_min_coverage", 0.80))
        and benches >= int(settings.get("confidence_high_min_benchmarks", 7))
    ):
        return "high"
    if coverage + 1e-12 >= float(settings.get("confidence_medium_min_coverage", 0.50)):
        return "medium"
    return "low"


def _score_against_anchors(
    entity_index: int,
    anchor_indices: list[int],
    ability: np.ndarray,
    covariance: np.ndarray,
) -> tuple[float, float]:
    others = [anchor for anchor in anchor_indices if anchor != entity_index]
    if not others:
        others = list(anchor_indices)
    probabilities = [
        float(expit(ability[entity_index] - ability[anchor]))
        for anchor in others
    ]
    score = 100.0 * float(np.mean(probabilities))
    gradient = np.zeros(len(ability), dtype=float)
    for anchor, probability in zip(others, probabilities, strict=True):
        derivative = 100.0 * probability * (1.0 - probability) / len(others)
        gradient[entity_index] += derivative
        gradient[anchor] -= derivative
    variance = max(0.0, float(gradient @ covariance @ gradient))
    return score, math.sqrt(variance)


def _component_payload(
    config: IndexConfig, by_benchmark: dict[str, NormalizedObservation]
) -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    for spec in config.active():
        item = by_benchmark.get(spec.id)
        if item is None:
            payload[spec.id] = {
                "title": spec.title,
                "dimension": spec.dimension,
                "weight": spec.weight_index,
                "observed": False,
                "score": None,
            }
            continue
        observation = item.observation
        payload[spec.id] = {
            "title": spec.title,
            "dimension": spec.dimension,
            "weight": spec.weight_index,
            "observed": True,
            "score": round(item.score, 6),
            "ci_low": item.ci_low,
            "ci_high": item.ci_high,
            "model_id": observation.model_id,
            "reasoning_effort": observation.reasoning_effort,
            "benchmark_version": observation.benchmark_version,
            "source_id": observation.source_id,
            "source_url": observation.source_url,
            "eval_date": observation.eval_date,
            "endpoint_date": observation.endpoint_date,
            "modality": observation.modality,
            "tool_mode": observation.tool_mode,
            "source_tier": observation.source_tier,
            "protocol_hash": observation.protocol_hash,
            "notes": observation.notes,
        }
    return payload


def score_consensus(
    observations: Iterable[Observation], config: IndexConfig
) -> PairwiseResult:
    selected = select_model_observations(observations, config)
    specs = {spec.id: spec for spec in config.active()}
    profiles = {
        family_id: _entry_profile(by_benchmark, config)
        for family_id, by_benchmark in selected.items()
    }
    requested_anchors = list(config.settings["anchors"])
    available_anchors = [anchor for anchor in requested_anchors if anchor in selected]
    minimum_anchors = int(config.settings["minimum_available_anchors"])
    anchors_ready = len(available_anchors) >= minimum_anchors

    preliminary = {
        family_id
        for family_id, profile in profiles.items()
        if _base_eligible(profile, config)
    }
    anchor_matches = {
        family_id: _anchor_match_count(family_id, selected, available_anchors)
        for family_id in selected
    }
    minimum_matches = int(config.settings["entry_min_anchor_matches"])
    rankable = {
        family_id
        for family_id in preliminary
        if family_id in available_anchors or anchor_matches[family_id] >= minimum_matches
    }
    if not anchors_ready:
        rankable.clear()
    circle = sorted(rankable.union(available_anchors))
    entity_index = {family_id: index for index, family_id in enumerate(circle)}
    comparisons: list[tuple[int, int, float, float]] = []
    adjacency: dict[str, set[str]] = defaultdict(set)
    benchmark_participants: dict[str, int] = {}
    evidence_units = float(config.settings["pairwise_budget_units"])
    for spec in config.active():
        participants = [
            family_id for family_id in circle if spec.id in selected[family_id]
        ]
        benchmark_participants[spec.id] = len(participants)
        if len(participants) < 2:
            continue
        pair_weight = evidence_units * spec.weight_index / (len(participants) - 1)
        for first_position, first_id in enumerate(participants):
            first = selected[first_id][spec.id]
            for second_id in participants[first_position + 1 :]:
                second = selected[second_id][spec.id]
                if _intervals_overlap(first, second):
                    outcome = 0.5
                else:
                    outcome = 1.0 if first.score > second.score else 0.0
                comparisons.append(
                    (
                        entity_index[first_id],
                        entity_index[second_id],
                        outcome,
                        pair_weight,
                    )
                )
                adjacency[first_id].add(second_id)
                adjacency[second_id].add(first_id)

    anchor_set = set(available_anchors)
    rankable = {
        family_id
        for family_id in rankable
        if _connected_to_anchor(family_id, adjacency, anchor_set)
    }
    ability: np.ndarray | None = None
    covariance: np.ndarray | None = None
    if comparisons and anchors_ready:
        ability, covariance = _fit_bradley_terry(
            circle, comparisons, float(config.settings["prior_sigma"])
        )
    else:
        rankable.clear()
    anchor_indices = [entity_index[anchor] for anchor in available_anchors]

    rows: list[ScoreRow] = []
    for family_id, by_benchmark in selected.items():
        profile = profiles[family_id]
        display_name, provider, release_date, representative = _model_metadata(
            family_id, by_benchmark
        )
        is_ranked = family_id in rankable
        point = standard_error = ci_low = ci_high = latent = None
        confidence = "insufficient"
        if is_ranked:
            assert ability is not None and covariance is not None
            index = entity_index[family_id]
            latent = float(ability[index])
            point, standard_error = _score_against_anchors(
                index, anchor_indices, ability, covariance
            )
            ci_low = max(0.0, point - 1.96 * standard_error)
            ci_high = min(100.0, point + 1.96 * standard_error)
            confidence = _confidence_label(profile, config)
        missing_reasons: list[str] = []
        if not is_ranked:
            if not anchors_ready:
                missing_reasons.append("too few frozen anchors")
            if float(profile["coverage"]) < float(config.settings["entry_min_coverage"]):
                missing_reasons.append("coverage below the entry floor")
            if int(profile["benchmarks"]) < int(config.settings["entry_min_benchmarks"]):
                missing_reasons.append("too few benchmarks")
            if int(profile["dimensions"]) < int(config.settings["entry_min_dimensions"]):
                missing_reasons.append("too few dimensions")
            absent_groups = [
                group_id
                for group_id, present in dict(profile["groups"]).items()
                if not present
            ]
            if absent_groups:
                missing_reasons.append("missing " + " / ".join(absent_groups) + " evidence")
            if (
                family_id not in available_anchors
                and anchor_matches[family_id] < minimum_matches
            ):
                missing_reasons.append("too few shared anchors")
        rows.append(
            ScoreRow(
                entity_id=family_id,
                display_name=display_name,
                provider=provider,
                index_id="KSR",
                index_version=config.version,
                status="ranked" if is_ranked else "insufficient",
                point=point,
                lower=ci_low if ci_low is not None else 0.0,
                upper=ci_high if ci_high is not None else 100.0,
                coverage=float(profile["coverage"]),
                imputed_weight=0.0,
                ci_low=ci_low,
                ci_high=ci_high,
                components=_component_payload(config, by_benchmark),
                warning=(
                    "" if is_ranked else "Insufficient evidence: " + "; ".join(missing_reasons)
                ),
                release_date=release_date,
                standard_error=standard_error,
                confidence=confidence,
                observed_benchmarks=int(profile["benchmarks"]),
                observed_dimensions=int(profile["dimensions"]),
                evidence_families=int(profile["evidence_families"]),
                anchor_comparisons=anchor_matches[family_id],
                latent_ability=latent,
                input_cost_per_million=representative.input_cost_per_million,
                output_cost_per_million=representative.output_cost_per_million,
                speed_tokens_per_second=representative.speed_tokens_per_second,
                context_window_tokens=representative.context_window_tokens,
            )
        )

    ranked = sorted(
        (row for row in rows if row.status == "ranked"),
        key=lambda row: (
            -(row.latent_ability if row.latent_ability is not None else -1e9),
            row.entity_id,
        ),
    )
    for rank, row in enumerate(ranked, 1):
        row.rank = rank
    for index, row in enumerate(ranked):
        neighbors = []
        if index:
            neighbors.append(ranked[index - 1])
        if index + 1 < len(ranked):
            neighbors.append(ranked[index + 1])
        if any(
            row.ci_low is not None
            and row.ci_high is not None
            and neighbor.ci_low is not None
            and neighbor.ci_high is not None
            and row.ci_low <= neighbor.ci_high
            and neighbor.ci_low <= row.ci_high
            for neighbor in neighbors
        ):
            row.warning = (
                "95% intervals overlap the adjacent rank; "
                "the strict order is not a significant difference."
            )
    rows.sort(
        key=lambda row: (
            row.status != "ranked",
            row.rank or 100_000,
            -row.coverage,
            -row.observed_benchmarks,
            row.entity_id,
        )
    )
    diagnostics: dict[str, object] = {
        "method": "weighted_bradley_terry",
        "anchor_version": config.settings["anchor_version"],
        "requested_anchors": requested_anchors,
        "available_anchors": available_anchors,
        "method_ready": bool(comparisons and anchors_ready),
        "candidate_models": len(selected),
        "ranked_models": len(ranked),
        "comparison_circle_models": len(circle),
        "pairwise_comparisons": len(comparisons),
        "benchmark_participants": benchmark_participants,
        "missing_policy": "no_imputation_no_penalty_no_weight_transfer",
        "representative_policy": "highest_reasoning_effort_then_source_then_date",
    }
    return PairwiseResult(rows, diagnostics)
