import json
import os
from pathlib import Path
from typing import Any, Dict, List


REQUIRED_DIMENSION_FIELDS = {
    "id",
    "name",
    "target_artifact",
    "forensic_instruction",
    "success_pattern",
    "failure_pattern",
}
class RubricError(ValueError):
    """Raised when the audit constitution is missing or malformed."""


def load_rubric_config(
    path: str | Path | None = None,
) -> Dict[str, Any]:
    path = path or os.getenv("AUDITOR_RUBRIC")
    if not path:
        raise RubricError(
            "Rubric path is required; pass it to load_rubric or set AUDITOR_RUBRIC"
        )
    rubric_path = Path(path)
    try:
        with rubric_path.open("r", encoding="utf-8") as file:
            config = json.load(file)
    except FileNotFoundError as exc:
        raise RubricError(f"Rubric file not found: {rubric_path}") from exc
    except json.JSONDecodeError as exc:
        raise RubricError(
            f"Rubric file is not valid JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc

    if not isinstance(config, dict):
        raise RubricError("Rubric root must be a JSON object")
    dimensions = config.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise RubricError("Rubric must contain a non-empty 'dimensions' array")

    seen_ids: set[str] = set()
    for index, dimension in enumerate(dimensions):
        if not isinstance(dimension, dict):
            raise RubricError(f"Dimension {index} must be a JSON object")
        missing = REQUIRED_DIMENSION_FIELDS - dimension.keys()
        if missing:
            raise RubricError(
                f"Dimension {index} is missing required fields: {', '.join(sorted(missing))}"
            )
        for field in REQUIRED_DIMENSION_FIELDS:
            if not isinstance(dimension[field], str) or not dimension[field].strip():
                raise RubricError(
                    f"Dimension {index} field '{field}' must be a non-empty string"
                )
        if dimension["id"] in seen_ids:
            raise RubricError(f"Duplicate rubric dimension ID: {dimension['id']}")
        seen_ids.add(dimension["id"])
        if dimension["target_artifact"] not in {
            "github_repo",
            "pdf_report",
            "pdf_images",
        }:
            raise RubricError(
                f"Dimension '{dimension['id']}' has unsupported target_artifact "
                f"{dimension['target_artifact']!r}"
            )

    rules = config.get("synthesis_rules")
    if not isinstance(rules, dict) or not rules:
        raise RubricError("Rubric must contain a non-empty 'synthesis_rules' object")
    return {
        "metadata": config.get("rubric_metadata", {}),
        "dimensions": dimensions,
        "synthesis_rules": rules,
    }


def load_rubric(
    path: str | Path | None = None,
) -> Dict[str, Any]:
    return load_rubric_config(path)


def load_synthesis_rules(
    path: str | Path | None = None,
) -> Dict[str, str]:
    return load_rubric_config(path)["synthesis_rules"]
