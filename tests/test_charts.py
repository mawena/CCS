import unittest

from ccs_app.gui.geometry import ideal_weekly_series, series_to_points


class ChartsTest(unittest.TestCase):
    def test_series_to_points_scales_and_clamps(self):
        pts = series_to_points([(0, 0), (50, 50), (100, 120), (150, -5)], 0, 100, 200, 100)
        self.assertEqual(pts[0], (0.0, 100.0))
        self.assertEqual(pts[1], (100.0, 50.0))
        self.assertEqual(pts[2], (200.0, 0.0))     # 120 % borné à 100
        self.assertEqual(len(pts), 3)               # hors plage temporelle ignoré

    def test_series_to_points_empty_range(self):
        self.assertEqual(series_to_points([(5, 10)], 5, 5, 100, 100), [])

    def test_ideal_weekly_series(self):
        week = 7 * 86400
        reset = 10 * 86400
        pts = ideal_weekly_series([(reset - week, 0, reset), (reset - week / 2, 30, reset)])
        self.assertEqual(pts, [(reset - week, 0.0), (reset - week / 2, 50.0)])
        self.assertEqual(ideal_weekly_series([(1, 5, None)]), [])


class TimelineTest(unittest.TestCase):
    def test_span_to_x_clamps(self):
        from ccs_app.gui.geometry import span_to_x
        self.assertEqual(span_to_x(50, 0, 100, 200), 100.0)
        self.assertEqual(span_to_x(-10, 0, 100, 200), 0.0)
        self.assertEqual(span_to_x(150, 0, 100, 200), 200.0)
        self.assertEqual(span_to_x(5, 5, 5, 200), 0.0)
