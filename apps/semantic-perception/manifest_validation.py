"""Preflight checks for manifests consumed by the offline SAM3 evaluator."""

from __future__ import annotations


def require_reviewed_rows(rows: list[dict]) -> None:
    """Refuse model scoring unless every selected mask has a completed review."""
    unreviewed = [
        row.get("capture_id", row.get("image", "<unknown>"))
        for row in rows
        if not (
            isinstance(row.get("review_status"), str)
            and (
                row["review_status"].strip() == "visually-reviewed"
                or "independently_reviewed_accepted" in row["review_status"].lower()
            )
        )
    ]
    if unreviewed:
        preview = ", ".join(str(item) for item in unreviewed[:5])
        suffix = "..." if len(unreviewed) > 5 else ""
        raise ValueError(
            f"refusing to score {len(unreviewed)} row(s) without completed label review: "
            f"{preview}{suffix}"
        )
