from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Detection:
    label: str
    detection_key: str
    confidence: float
    box: tuple[float, float, float, float]  # xmin, ymin, xmax, ymax, normalized 0..1


class DetectionBackend(ABC):
    key: str = "backend"

    @classmethod
    def available(cls) -> tuple[bool, str]:
        return False, "nicht implementiert"

    @abstractmethod
    def infer(self, frame: np.ndarray) -> list[Detection]:
        raise NotImplementedError
