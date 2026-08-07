import unittest

import numpy as np

from app.tbc.detection.color import dominant_color


def _solid_bgr(b: int, g: int, r: int, size: int = 20) -> np.ndarray:
    image = np.zeros((size, size, 3), dtype=np.uint8)
    image[:, :] = (b, g, r)
    return image


class DominantColorTests(unittest.TestCase):
    def test_none_for_empty_image(self):
        self.assertIsNone(dominant_color(None))
        self.assertIsNone(dominant_color(np.zeros((0, 0, 3), dtype=np.uint8)))

    def test_black(self):
        self.assertEqual(dominant_color(_solid_bgr(10, 10, 10)), "black")

    def test_white(self):
        self.assertEqual(dominant_color(_solid_bgr(250, 250, 250)), "white")

    def test_gray(self):
        self.assertEqual(dominant_color(_solid_bgr(110, 110, 110)), "gray")

    def test_silver(self):
        self.assertEqual(dominant_color(_solid_bgr(190, 190, 190)), "silver")

    def test_red(self):
        self.assertEqual(dominant_color(_solid_bgr(20, 20, 220)), "red")

    def test_blue(self):
        self.assertEqual(dominant_color(_solid_bgr(220, 20, 20)), "blue")

    def test_green(self):
        self.assertEqual(dominant_color(_solid_bgr(20, 200, 20)), "green")

    def test_yellow(self):
        self.assertEqual(dominant_color(_solid_bgr(20, 220, 220)), "yellow")


if __name__ == "__main__":
    unittest.main()
