import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import root_keeper as rk, root_vault
from tests.test_root_keeper import GOOD, Clock, fake_verify


class VaultCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        env = {"XDG_CONFIG_HOME": f"{self.tmp}/conf", "XDG_STATE_HOME": f"{self.tmp}/state"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)


class VaultTest(VaultCase):
    def test_aller_retour_chiffre(self):
        self.assertTrue(root_vault.save(rk.to_secret(GOOD)))
        raw = root_vault.vault_path().read_bytes()
        self.assertNotIn(GOOD.encode(), raw)
        for p in (root_vault.vault_path(), root_vault.key_path()):
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertNotEqual(root_vault.vault_path().parent, root_vault.key_path().parent)
        self.assertEqual(bytes(root_vault.load(rk.Secret).view()), GOOD.encode())

    def test_autre_machine_refuse(self):
        root_vault.save(rk.to_secret(GOOD))
        with mock.patch.object(root_vault, "_aad", return_value=b"autre"):
            self.assertIsNone(root_vault.load(rk.Secret))

    def test_fichier_lisible_par_autres_ignore(self):
        root_vault.save(rk.to_secret(GOOD))
        os.chmod(root_vault.vault_path(), 0o644)
        self.assertIsNone(root_vault.load(rk.Secret))

    def test_effacer(self):
        root_vault.save(rk.to_secret(GOOD))
        self.assertTrue(root_vault.delete())
        self.assertFalse(root_vault.vault_path().exists() or root_vault.key_path().exists())
        self.assertIsNone(root_vault.load(rk.Secret))


class ForeverTest(VaultCase):
    def make(self, verify=None):
        self.clock = Clock()
        return rk.Keeper(machine="vps", clock=self.clock, verify=verify or fake_verify(),
                         vault=root_vault)

    async def test_garde_pour_toujours_et_survit(self):
        k = self.make()
        k.store(rk.to_secret(GOOD))
        self.clock.t += 365 * 86400
        self.assertTrue(k.kept())
        st = k.status()
        self.assertTrue(st["stored"])
        self.assertFalse(st["kept"])                # pas de bandeau dans les interfaces
        self.assertIn("sans limite", rk.status_text(st))
        k.close()                                   # arrêt du pont : le coffre reste
        k2 = self.make()
        self.assertTrue(k2.kept())
        (await k2.ask("ls")).wipe()

    async def test_oublier_efface_le_coffre(self):
        k = self.make()
        k.store(rk.to_secret(GOOD))
        k.forget()
        self.assertFalse(root_vault.vault_path().exists())
        self.assertFalse(self.make().kept())

    async def test_mot_de_passe_change(self):
        root_vault.save(rk.to_secret("ancien"))
        k = self.make()
        self.assertTrue(k.kept())
        k.ask_timeout = 0.05
        self.assertIsNone(await k.ask("ls"))        # refusé par sudo : effacé et redemandé
        self.assertFalse(root_vault.vault_path().exists())


if __name__ == "__main__":
    unittest.main()
