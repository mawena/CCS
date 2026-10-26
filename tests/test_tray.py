import unittest

from ccs_app.tray import label_for


def state(*limits, active="perso"):
    return {"active": active, "accounts": [
        {"name": "perso", "active": True,
         "limits": [{"kind": k, "percent": p} for k, p in limits]}]}


class TrayLabelTest(unittest.TestCase):
    def test_label_for(self):
        self.assertEqual(label_for(state(("session", 32), ("weekly_all", 40))), "◔ 32 %")
        self.assertEqual(label_for(state(("session", 10), ("weekly_all", 98))), "⚠ 98 %")
        self.assertEqual(label_for(state(("session", 96))), "⚠ 96 %")
        self.assertEqual(label_for({}), "—")
        self.assertEqual(label_for(state(active=None)), "—")
        self.assertEqual(label_for(state()), "—")

    def test_label_quarters(self):
        self.assertEqual(label_for(state(("session", 5))), "○ 5 %")
        self.assertEqual(label_for(state(("session", 60))), "◑ 60 %")
        self.assertEqual(label_for(state(("session", 80))), "◕ 80 %")
