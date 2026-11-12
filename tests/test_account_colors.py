import unittest

from ccs_app import account_colors as ac


class AccountColorsTest(unittest.TestCase):
    def test_stable_assignment(self):
        profs = ["pro", "perso", "autre"]
        a = [ac.color_for(p, profs, {}) for p in sorted(profs)]
        self.assertEqual(a, list(ac.PALETTE[:3]))
        self.assertEqual(ac.color_for("pro", list(reversed(profs)), {}), ac.PALETTE[2])

    def test_chosen_color_kept(self):
        self.assertEqual(ac.color_for("a", ["a", "b"], {"a": "#112233"}), "#112233")
        # la couleur choisie par b n'est plus donnée à a
        self.assertEqual(ac.color_for("a", ["a", "b"], {"b": ac.PALETTE[0]}), ac.PALETTE[1])

    def test_invalid_choice_ignored(self):
        for bad in ("rouge", "#12", "#gggggg", 5, None):
            self.assertEqual(ac.color_for("a", ["a"], {"a": bad}), ac.PALETTE[0])

    def test_wraps_when_more_profiles_than_colors(self):
        profs = [f"p{i:02d}" for i in range(len(ac.PALETTE) + 2)]
        cols = [ac.color_for(p, profs, {}) for p in profs]
        self.assertEqual(cols[:len(ac.PALETTE)], list(ac.PALETTE))
        self.assertEqual(cols[-2:], list(ac.PALETTE[:2]))

    def test_rgb(self):
        self.assertEqual(ac.rgb("#ff0000"), (1.0, 0.0, 0.0))
        self.assertEqual(ac.rgb("nul"), (0.5, 0.5, 0.5))


if __name__ == "__main__":
    unittest.main()
