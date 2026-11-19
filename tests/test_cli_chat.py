"""`ccs chat effacer` : demande d'effacement déposée pour le moteur du chat."""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from ccs_app import chat_engine, cli


class ChatEffacerTest(unittest.TestCase):
    def run_cli(self, env):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env), redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["chat", "effacer"])
        return code, out.getvalue(), err.getvalue()

    def test_request_is_written_for_the_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _err = self.run_cli({"XDG_CACHE_HOME": tmp, chat_engine.CLEAR_TOKEN_VAR: "ab12"})
            self.assertEqual(code, 0)
            self.assertIn("effacée", out)
            self.assertTrue((Path(tmp) / "ccs" / "effacer" / "ab12").exists())

    def test_outside_a_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"XDG_CACHE_HOME": tmp, chat_engine.CLEAR_TOKEN_VAR: ""}
            code, _out, err = self.run_cli(env)
            self.assertEqual(code, 1)
            self.assertIn("Pas dans un chat de CCS", err)
            code, _out, err = self.run_cli({**env, chat_engine.CLEAR_TOKEN_VAR: "../x"})
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
