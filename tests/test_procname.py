import unittest
from unittest import mock

from ccs_app import procname


class NameForTest(unittest.TestCase):
    def test_roles(self):
        self.assertEqual(procname.name_for(["gui"]), "ccs-gui")
        self.assertEqual(procname.name_for([]), "ccs-gui")
        self.assertEqual(procname.name_for(["daemon"]), "ccs-daemon")
        self.assertEqual(procname.name_for(["tray"]), "ccs-tray")
        self.assertEqual(procname.name_for(["--print"]), "ccs-gui")

    def test_autres_commandes(self):
        self.assertEqual(procname.name_for(["print"]), "ccs")
        self.assertEqual(procname.name_for(["collect"]), "ccs")

    def test_longueur_noyau(self):
        for n in (*procname.NAMES.values(), procname.DEFAULT):
            self.assertLessEqual(len(n.encode()), 15)


class ApplyTest(unittest.TestCase):
    def test_tolere_les_echecs(self):
        with mock.patch.object(procname.ctypes, "CDLL", side_effect=OSError("non")):
            self.assertFalse(procname.apply("ccs-gui"))

    def test_prctl_appele(self):
        libc = mock.Mock()
        libc.prctl.return_value = 0
        with mock.patch.object(procname.ctypes, "CDLL", return_value=libc):
            self.assertTrue(procname.apply("ccs-daemon"))
        self.assertEqual(libc.prctl.call_args[0][:2], (procname.PR_SET_NAME, b"ccs-daemon"))


if __name__ == "__main__":
    unittest.main()
