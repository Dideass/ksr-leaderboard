from __future__ import annotations

from ..models import Observation
from .base import AdapterError, FetchResult, SourceAdapter, parse_json_bytes


class NormalizedJsonAdapter(SourceAdapter):
    def parse(self, result: FetchResult):
        payload = parse_json_bytes(result.content)
        rows = payload.get("observations") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise AdapterError(f"{self.source_id}: expected an observations list")
        observations = []
        for row in rows:
            merged = {
                **row,
                "source_id": row.get("source_id", self.source_id),
                "source_url": row.get(
                    "source_url", self.source.get("public_url") or self.source.get("url")
                ),
                "retrieved_at": row.get("retrieved_at", result.retrieved_at),
                "raw_hash": row.get("raw_hash", result.sha256),
            }
            observations.append(Observation.from_mapping(merged))
        return observations

