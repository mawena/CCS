"""Options d'un chat : modèle, effort, ultracode, droits."""

import unittest

from ccs_app import chat_options as co
from ccs_app import chat_protocol as cp
from ccs_app import launch_options


class OptionsTest(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(co.ChatOptions(), co.ChatOptions(None, None, False, "manual"))
        with self.assertRaises(Exception):
            co.ChatOptions().model = "opus"   # gelée

    def test_tables(self):
        self.assertIs(co.MODELS, launch_options.MODELS)
        self.assertEqual(co.EFFORTS, ("low", "medium", "high", "xhigh", "max"))
        self.assertEqual(set(co.EFFORT_LABELS), set(co.EFFORTS))
        self.assertEqual([v for _l, v in co.RIGHTS], ["manual", "acceptEdits", "plan", "bypassPermissions"])

    def test_xhigh_hidden_for_4_6(self):
        for model in ("claude-opus-4-6", "claude-sonnet-4-6", "claude-opus-4-6[1m]", "sonnet-4-6"):
            self.assertNotIn("xhigh", co.efforts_for(model), model)
            self.assertFalse(co.ultracode_possible(model), model)
        # Un alias qui mène à un 4.6 : reconnu par le nom complet annoncé par la CLI.
        self.assertNotIn("xhigh", co.efforts_for("sonnet", resolved="claude-sonnet-4-6"))
        for model in (None, "opus", "claude-opus-5-5", "haiku", "claude-opus-4-7"):
            self.assertEqual(co.efforts_for(model), co.EFFORTS, model)
            self.assertTrue(co.ultracode_possible(model), model)

    def test_ultracode_launch_arg(self):
        args = co.launch_args(co.ChatOptions(model="opus", effort="high", ultracode=True, rights="plan"))
        self.assertEqual(args, ["--model", "opus", "--effort", "ultracode", "--permission-mode", "plan"])

    def test_launch_args_plain(self):
        self.assertEqual(co.launch_args(co.ChatOptions()), ["--permission-mode", "manual"])
        self.assertEqual(co.launch_args(co.ChatOptions(effort="max", rights="acceptEdits")),
                         ["--effort", "max", "--permission-mode", "acceptEdits"])

    def test_merge_hello_models(self):
        hello = cp.Hello(models=(("default", "Default (recommended)", "", co.EFFORTS),
                                 ("opus", "Opus 5.5", "", co.EFFORTS),
                                 ("claude-sonnet-4-6", "Sonnet 4.6", "", ("low", "high"))))
        self.assertEqual(co.merge_hello(hello), (("Par défaut", None), ("Opus 5.5", "opus"),
                                                 ("Sonnet 4.6", "claude-sonnet-4-6")))
        self.assertEqual(co.merge_hello(cp.Hello()), co.MODELS)

    def test_from_args(self):
        opts = co.from_args(("--model", "sonnet", "--permission-mode", "acceptEdits", "--effort", "low"))
        self.assertEqual(opts, co.ChatOptions("sonnet", "low", False, "acceptEdits"))
        self.assertEqual(co.from_args(("--model=opus", "--effort=ultracode")),
                         co.ChatOptions("opus", None, True, "manual"))
        self.assertEqual(co.from_args(()), co.ChatOptions())
        self.assertEqual(co.from_args(("--verbose", "--permission-mode", "default")), co.ChatOptions())

    def test_from_args_ignores_bad_values(self):
        opts = co.from_args(("--model", "pas valide!", "--permission-mode", "nimporte", "--effort", "enorme"))
        self.assertEqual(opts, co.ChatOptions())
        self.assertEqual(co.from_args(("--model",)), co.ChatOptions())   # valeur manquante
        self.assertEqual(co.from_args(("--model", "Par défaut")).model, None)


if __name__ == "__main__":
    unittest.main()
