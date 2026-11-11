"""Import paresseux et protégé de VTE : l'application ne dépend jamais de sa présence."""

import os
import unittest
from unittest import mock

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class LazyVteTest(unittest.TestCase):
    def setUp(self):
        from ccs_app.gui import terminals
        self.terminals = terminals
        terminals._vte = None
        self.addCleanup(setattr, terminals, "_vte", None)

    def test_missing_typelib_means_no_embedded_terminal(self):
        real = gi.require_version

        def missing(namespace, version):
            if namespace == "Vte":
                raise ValueError("Namespace Vte not available")
            return real(namespace, version)
        with mock.patch.object(gi, "require_version", side_effect=missing), \
                mock.patch.dict(os.environ, {"CCS_NO_VTE": ""}):
            self.assertIsNone(self.terminals.vte())
            self.assertIsNone(self.terminals.vte())  # réponse gardée : pas de nouvel essai

    def test_disabled_by_environment_without_importing(self):
        with mock.patch.object(gi, "require_version") as require, \
                mock.patch.dict(os.environ, {"CCS_NO_VTE": "1"}):
            self.assertIsNone(self.terminals.vte())
        require.assert_not_called()

    def test_module_import_does_not_load_vte(self):
        import importlib
        import sys
        sys.modules.pop("gi.repository.Vte", None)
        importlib.reload(self.terminals)
        self.assertNotIn("gi.repository.Vte", sys.modules)
