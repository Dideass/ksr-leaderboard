from __future__ import annotations

import csv
from pathlib import Path

from ..models import Observation, utc_now_iso
from .base import AdapterError, FetchResult, SourceAdapter


class ManualCsvAdapter(SourceAdapter):
    def fetch(self) -> FetchResult:
        path = Path(self.source["path"])
        if not path.exists():
            raise AdapterError(f"{self.source_id}: manual CSV not found: {path}")
        return FetchResult(
            source_id=self.source_id,
            content=path.read_bytes(),
            content_type="text/csv",
            retrieved_at=utc_now_iso(),
            status_code=200,
        )

    def parse(self, result: FetchResult) -> list[Observation]:
        text = result.content.decode("utf-8-sig")
        rows = list(csv.DictReader(text.splitlines()))
        observations: list[Observation] = []
        for line_number, row in enumerate(rows, 2):
            if not any(value not in (None, "") for value in row.values()):
                continue
            try:
                observation = Observation.from_mapping(row)
            except (TypeError, ValueError) as exc:
                raise AdapterError(
                    f"{self.source_id}: invalid manual row {line_number}: {exc}"
                ) from exc
            if not observation.protocol_hash:
                observation.protocol_compatible = False
                observation.notes = (
                    observation.notes + " Missing protocol_hash; excluded from scoring."
                ).strip()
            if not observation.raw_hash:
                observation.raw_hash = result.sha256
            observations.append(observation)
        return observations

    def validate(self, observations: list[Observation]) -> None:
        # Empty manual files are valid; they are the expected initial state.
        if observations:
            original = self.source.get("minimum_rows", 1)
            self.source["minimum_rows"] = 1
            try:
                super().validate(observations)
            finally:
                self.source["minimum_rows"] = original

