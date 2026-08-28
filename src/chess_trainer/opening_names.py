"""Tiny helper shared by ingestion and analysis."""


def family_of(opening_name: str | None) -> str | None:
    """'Sicilian Defense: Najdorf Variation' -> 'Sicilian Defense'."""
    if not opening_name:
        return None
    return opening_name.split(":", 1)[0].strip() or None
