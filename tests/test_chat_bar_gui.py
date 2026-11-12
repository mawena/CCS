"""Barre du chat : modèle, effort, ultracode, droits, contexte, compte."""

import unittest

from tests.helpers import gui_ready

GTK = gui_ready()

if GTK:
    from ccs_app import chat_options
    from ccs_app.chat_options import ChatOptions
    from ccs_app.gui.chat_bar import ChatBar


@unittest.skipUnless(GTK, "tests graphiques : CCS_GUI_TESTS=1 avec xvfb-run")
class ChatBarTest(unittest.TestCase):
    def make(self, options=None):
        bar = ChatBar()
        bar.set_options(options or ChatOptions())
        self.changes = []
        bar.connect("changed", lambda _b, o: self.changes.append(o))
        return bar

    def test_xhigh_disabled_for_4_6(self):
        bar = self.make(ChatOptions(model="claude-opus-4-6"))
        self.assertFalse(bar.effort_picker.rows["xhigh"].get_sensitive())
        self.assertTrue(bar.effort_picker.rows["high"].get_sensitive())
        self.assertFalse(bar.ultracode.get_sensitive())
        bar.set_options(ChatOptions(model="opus"))
        self.assertTrue(bar.effort_picker.rows["xhigh"].get_sensitive())
        self.assertTrue(bar.ultracode.get_sensitive())

    def test_model_change_drops_unsupported_effort_and_ultracode(self):
        models = (("Par défaut", None), ("Opus 4.6", "opus-4-6"), ("Opus", "opus"))
        bar = self.make(ChatOptions(model="opus", effort="xhigh", ultracode=True))
        bar.set_choices(models, chat_options.efforts_for, chat_options.ultracode_possible)
        bar.model_picker.rows["opus-4-6"].emit("clicked")
        self.assertEqual(self.changes[-1], ChatOptions(model="opus-4-6", effort=None, ultracode=False))

    def test_choices_emit_changed(self):
        bar = self.make()
        bar.effort_picker.rows["high"].emit("clicked")
        bar.ultracode.set_active(True)
        bar.rights_picker.rows["plan"].emit("clicked")
        self.assertEqual(self.changes[-1], ChatOptions(effort="high", ultracode=True, rights="plan"))

    def test_set_options_is_silent(self):
        bar = self.make()
        bar.set_options(ChatOptions(model="haiku", ultracode=True))
        self.assertEqual(self.changes, [])
        self.assertTrue(bar.ultracode.get_active())

    def test_bypass_asks_confirmation(self):
        bar = self.make()
        asked = []
        bar.confirm_dangerous = asked.append
        bar.rights_picker.rows["bypassPermissions"].emit("clicked")
        self.assertEqual(len(asked), 1)
        self.assertEqual(self.changes, [])          # rien ne change avant la confirmation
        asked[0]()                                  # « Tout autoriser »
        self.assertEqual(self.changes[-1].rights, "bypassPermissions")

    def test_context_color_over_threshold(self):
        bar = self.make()
        bar.set_context(30, 60)
        self.assertEqual(bar.context_level, "ok")
        self.assertTrue(bar.gauge.has_css_class("ccs-gauge-ok"))
        bar.set_context(65, 60)
        self.assertEqual(bar.context_level, "warn")
        self.assertTrue(bar.gauge.has_css_class("ccs-gauge-warn"))
        self.assertFalse(bar.gauge.has_css_class("ccs-gauge-ok"))
        bar.set_context(95, 60)
        self.assertEqual(bar.context_level, "crit")

    def test_account_is_shown_with_its_color(self):
        bar = self.make()
        bar.set_account("perso", "#3584e4")
        self.assertTrue(bar.account_box.get_visible())
        self.assertEqual(bar.account_label.get_label(), "perso")
        self.assertEqual(bar.dot_color, "#3584e4")


if __name__ == "__main__":
    unittest.main()
