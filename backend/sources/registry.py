from __future__ import annotations

from typing import Dict, Type

from .base import BaseJobSource
from .ilan_gov import IlanGovSource
from .iskur import IskurSource
from .kariyer_kapisi import KariyerKapisiSource
from .sbb import SBBSource
from .yerel_yonetimler import YerelYonetimlerSource


def get_source_registry() -> Dict[str, BaseJobSource]:
    return {
        "sbb": SBBSource(),
        "iskur": IskurSource(),
        "yerel-yonetimler": YerelYonetimlerSource(),
        "kariyer-kapisi": KariyerKapisiSource(),
        "ilan-gov": IlanGovSource(),
    }


def get_source_class_map() -> Dict[str, Type[BaseJobSource]]:
    return {
        "sbb": SBBSource,
        "iskur": IskurSource,
        "yerel-yonetimler": YerelYonetimlerSource,
        "kariyer-kapisi": KariyerKapisiSource,
        "ilan-gov": IlanGovSource,
    }
