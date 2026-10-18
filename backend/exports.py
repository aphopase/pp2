"""Stable JSON and CSV campaign exports."""
from __future__ import annotations

import csv
import io
import json
from typing import Any


def campaign_json(report: dict[str, Any]) -> str:
    return json.dumps(report, sort_keys=True, indent=2)


def campaign_csv(report: dict[str, Any]) -> str:
    output = io.StringIO()
    fields = ["campaign_id", "sensor_id", "observed_value", "reference_value", "offset", "status", "error", "simulation_only"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for attempt in report.get("attempts", []):
        writer.writerow({
            "campaign_id": report.get("campaign_id", ""),
            "sensor_id": attempt.get("sensor_id", ""),
            "observed_value": attempt.get("observed_value", ""),
            "reference_value": attempt.get("reference_value", ""),
            "offset": attempt.get("offset", ""),
            "status": attempt.get("status", ""),
            "error": attempt.get("error", ""),
            "simulation_only": "true",
        })
    return output.getvalue()
