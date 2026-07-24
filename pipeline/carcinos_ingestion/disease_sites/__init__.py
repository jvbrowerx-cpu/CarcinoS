"""
Disease-site registry. Each site exposes a CONFIG of type DiseaseSiteConfig.

Codes match the disease_site_code enum in 01_schema.sql so the orchestrator
can write directly to the alerts.disease_site_id column.
"""

from .base import DiseaseSiteConfig
from . import gynecologic, thoracic, breast, head_neck, cns, sarcoma, gu, hematologic, cutaneous, gastrointestinal

ALL_SITES: dict[str, DiseaseSiteConfig] = {
    gynecologic.CONFIG.code:      gynecologic.CONFIG,
    thoracic.CONFIG.code:         thoracic.CONFIG,
    breast.CONFIG.code:           breast.CONFIG,
    head_neck.CONFIG.code:        head_neck.CONFIG,
    cns.CONFIG.code:              cns.CONFIG,
    sarcoma.CONFIG.code:          sarcoma.CONFIG,
    gu.CONFIG.code:               gu.CONFIG,
    hematologic.CONFIG.code:      hematologic.CONFIG,
    cutaneous.CONFIG.code:        cutaneous.CONFIG,
    gastrointestinal.CONFIG.code: gastrointestinal.CONFIG,
}


def get(code: str) -> DiseaseSiteConfig:
    if code not in ALL_SITES:
        raise KeyError(
            f"Unknown disease site code: {code!r}. "
            f"Valid: {sorted(ALL_SITES.keys())}"
        )
    return ALL_SITES[code]
