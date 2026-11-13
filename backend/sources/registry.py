from __future__ import annotations

from typing import Dict, Type

from .base import BaseJobSource
from .iskur import IskurSource
from .sbb import SBBSource
from .yerel_yonetimler import YerelYonetimlerSource


def get_source_registry() -> Dict[str, BaseJobSource]:
    return {
        "sbb": SBBSource(),
        "iskur": IskurSource(),
        "yerel-yonetimler": YerelYonetimlerSource(),
    }


def get_source_class_map() -> Dict[str, Type[BaseJobSource]]:
    return {
        "sbb": SBBSource,
        "iskur": IskurSource,
        "yerel-yonetimler": YerelYonetimlerSource,
    }
