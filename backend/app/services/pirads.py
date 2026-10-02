from __future__ import annotations

from typing import Any


ZONES = {"peripheral_zone", "transition_zone"}


def _score(value: Any, field: str) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer from 1 to 5.") from exc
    if score not in {1, 2, 3, 4, 5}:
        raise ValueError(f"{field} must be an integer from 1 to 5.")
    return score


def _calculate_reference_category(zone: str, t2_score: int, dwi_score: int, dce: str) -> tuple[int, str]:
    """Apply the PI-RADS v2.1 peripheral/transition-zone combination tables.

    This is a transparent guideline-derived calculator, not an AI model and not
    a clinical diagnosis. The caller must supply the radiologist's sequence scores.
    """
    if zone == "peripheral_zone":
        if dwi_score == 1:
            return 1, "PZ: DWI 1 → PI-RADS 1."
        if dwi_score == 2:
            return 2, "PZ: DWI 2 → PI-RADS 2."
        if dwi_score == 3:
            if dce == "positive":
                return 4, "PZ: DWI 3 + positive DCE → PI-RADS 4."
            if dce == "negative":
                return 3, "PZ: DWI 3 + negative DCE → PI-RADS 3."
            raise ValueError("PZ DWI 3 requires DCE to derive the reference category.")
        if dwi_score == 4:
            return 4, "PZ: DWI 4 → PI-RADS 4."
        return 5, "PZ: DWI 5 → PI-RADS 5."

    if t2_score == 1:
        return 1, "TZ: T2 1 → PI-RADS 1."
    if t2_score == 2:
        if dwi_score <= 3:
            return 2, "TZ: T2 2 + DWI ≤3 → PI-RADS 2."
        return 3, "TZ: T2 2 + DWI ≥4 → PI-RADS 3."
    if t2_score == 3:
        if dwi_score <= 4:
            return 3, "TZ: T2 3 + DWI ≤4 → PI-RADS 3."
        return 4, "TZ: T2 3 + DWI 5 → PI-RADS 4."
    if t2_score == 4:
        return 4, "TZ: T2 4 → PI-RADS 4."
    return 5, "TZ: T2 5 → PI-RADS 5."


def validate_assessment(payload: dict[str, Any]) -> dict[str, Any]:
    zone = str(payload.get("zone", "")).strip().lower()
    aliases = {"pz": "peripheral_zone", "tz": "transition_zone"}
    zone = aliases.get(zone, zone)
    if zone not in ZONES:
        raise ValueError("zone must be peripheral_zone or transition_zone for the PI-RADS v2.1 combination calculator")
    t2_score = _score(payload.get("t2_score"), "t2_score")
    dwi_score = _score(payload.get("dwi_score"), "dwi_score")
    dce = str(payload.get("dce", "not_assessed")).strip().lower()
    if dce not in {"positive", "negative", "not_assessed"}:
        raise ValueError("dce must be positive, negative, or not_assessed")
    lesion_size = payload.get("lesion_size_mm")
    if lesion_size not in (None, ""):
        try:
            lesion_size = float(lesion_size)
        except (TypeError, ValueError) as exc:
            raise ValueError("lesion_size_mm must be numeric.") from exc
        if lesion_size <= 0:
            raise ValueError("lesion_size_mm must be greater than zero.")
    else:
        lesion_size = None

    reference_category, logic = _calculate_reference_category(zone, t2_score, dwi_score, dce)
    reader_category = payload.get("final_category")
    if reader_category not in (None, ""):
        reader_category = _score(reader_category, "final_category")
    else:
        reader_category = None

    return {
        "framework": "PI-RADS v2.1",
        "zone": zone,
        "lesion_size_mm": lesion_size,
        "t2_score": t2_score,
        "dwi_score": dwi_score,
        "dce": dce,
        "reference_category": reference_category,
        "reader_final_category": reader_category,
        "reader": str(payload.get("reader", "")).strip() or None,
        "calculation": logic,
        "assessment_status": "RADIOLOGIST-ENTERED" if reader_category is not None else "GUIDELINE-CALCULATED / REQUIRES RADIOLOGIST VERIFICATION",
        "clinical_claim": False,
        "note": "Transparent PI-RADS v2.1 combination-table calculation from reader-entered sequence scores. It is not an AI prediction, not a diagnosis, and not clinically validated by MedAxis.",
    }
