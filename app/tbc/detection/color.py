from __future__ import annotations

import numpy as np

# Fixed named palette for the dominant-color heuristic below. Deliberately coarse (no
# orange/purple/cyan buckets) since this is a best-effort attribute for filtering recordings,
# not a precise color-matching feature - low-saturation oranges/browns and high-saturation
# blue-violets are folded into their nearest neighbor. English tokens, same convention as the
# raw COCO sub_label ("truck", "cat", ...) stored alongside it - untranslated machine values,
# not UI copy, so they don't go through the i18n system.
COLOR_LABELS: tuple[str, ...] = ("black", "white", "gray", "silver", "red", "yellow", "green", "blue", "brown")


def dominant_color(image: np.ndarray) -> str | None:
    """Best-effort dominant-color name for a cropped BGR image (e.g. a vehicle detection box).

    Downsamples to reduce the influence of background bleed and reflections that leak in around
    a loosely-padded crop, then buckets the median HSV pixel into a small named palette. OpenCV's
    hue range is 0-179 (each unit = 2 degrees); grayscale buckets (black/white/gray/silver) are
    decided from value/saturation first since hue is meaningless for them.
    """
    if image is None or image.size == 0:
        return None
    import cv2

    small = cv2.resize(image, (32, 32), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hue = float(np.median(hsv[:, :, 0]))
    saturation = float(np.median(hsv[:, :, 1]))
    value = float(np.median(hsv[:, :, 2]))

    if value < 50:
        return "black"
    if saturation < 30:
        if value > 200:
            return "white"
        if value > 130:
            return "silver"
        return "gray"

    if hue < 10 or hue >= 165:
        return "red"
    if hue < 20:
        return "brown"
    if hue < 33:
        return "yellow"
    if hue < 85:
        return "green"
    return "blue"
