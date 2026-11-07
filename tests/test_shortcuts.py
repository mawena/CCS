"""Raccourcis clavier globaux (GNOME) : réglages simulés, jamais ceux du bureau."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import shortcuts as sc

DIR = sc.CUSTOM_DIR
FOREIGN = [DIR + "custom0/", DIR + "custom1/", DIR + "custom2/"]


def gnome():
    """Bureau GNOME simulé : trois raccourcis personnalisés à Charles et quelques
    raccourcis courants du bureau."""
    b = sc.MemoryBackend.gnome()
    b.add_schema("org.gnome.desktop.wm.keybindings", {
        "close": ["<Alt>F4"], "minimize": ["<Super>h"],
        "switch-to-workspace-left": ["<Super>Page_Up", "<Super><Alt>Left"],
        "show-desktop": ["<Primary><Super>d", "<Super>d"]})
    b.add_schema("org.gnome.shell.keybindings", {
        "toggle-message-tray": ["<Super>v", "<Super>m"], "screenshot": ["Print"],
        "show-screen-recording-ui": ["<Ctrl><Shift><Alt>R"]})
    b.add_schema(sc.MEDIA_KEYS, {"screenreader": ["<Alt><Super>s"], "terminal": ["<Primary><Alt>t"],
                                 "magnifier": ["<Alt><Super>8"]})
    b.summaries[(sc.MEDIA_KEYS, "screenreader")] = "Lecteur d'écran"
    for path, (name, cmd, binding) in zip(FOREIGN, [
            ("play-previous", "playerctl previous", "<Control><Alt>Page_Up"),
            ("play-next", "playerctl next", "<Control><Alt>Page_Down"),
            ("play-pause", "playerctl play-pause", "<Control><Alt>space")]):
        b.set(sc.CUSTOM_SCHEMA, {"name": name, "command": cmd, "binding": binding}, path)
    b.set(sc.MEDIA_KEYS, {sc.CUSTOM_KEY: list(FOREIGN)})
    b.log.clear()
    return b


def custom_list(b):
    return b.get(sc.MEDIA_KEYS, sc.CUSTOM_KEY)


def custom(b, path):
    return {k: b.get(sc.CUSTOM_SCHEMA, k, path) for k in ("name", "command", "binding")}


class SafetyMixin:
    """Aucun test ne doit atteindre les vrais réglages : le moteur par défaut est interdit."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(sc, "default_backend",
                              side_effect=AssertionError("vrais réglages GNOME interdits en test"))
        p.start()
        self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"})
        env.start()
        self.addCleanup(env.stop)


# --------------------------------------------------------------------------
# Raccourcis : lecture, validation, libellés
# --------------------------------------------------------------------------

class ParseTest(unittest.TestCase):
    def test_gtk_format(self):
        b = sc.parse_binding("<Super><Alt>c")
        self.assertEqual(b.accel, "<Super><Alt>c")
        self.assertEqual(b.label, "Super+Alt+C")

    def test_human_format_and_case(self):
        self.assertEqual(sc.parse_binding("Super+Alt+C").accel, "<Super><Alt>c")
        self.assertEqual(sc.parse_binding("super + alt + c").accel, "<Super><Alt>c")
        self.assertEqual(sc.parse_binding("<SUPER><alt>C").accel, "<Super><Alt>c")

    def test_modifier_order_is_canonical(self):
        self.assertEqual(sc.parse_binding("<Shift><Alt><Control><Super>F5").accel,
                         "<Super><Control><Alt><Shift>F5")
        self.assertEqual(sc.parse_binding("<Shift><Alt><Control><Super>F5").label,
                         "Super+Ctrl+Alt+Maj+F5")

    def test_modifier_aliases(self):
        for text in ("<Primary><Alt>t", "<Ctrl><Alt>t", "<Control><Alt>t", "Ctrl+Alt+T", "<Mod1><Control>t"):
            self.assertEqual(sc.parse_binding(text).accel, "<Control><Alt>t", text)
        self.assertEqual(sc.parse_binding("Win+Maj+X").accel, "<Super><Shift>x")
        self.assertEqual(sc.parse_binding("<Mod4>x").accel, "<Super>x")

    def test_named_keys_and_aliases(self):
        self.assertEqual(sc.parse_binding("Super+Alt+PageDown").accel, "<Super><Alt>Page_Down")
        self.assertEqual(sc.parse_binding("<Super>Next").accel, "<Super>Page_Down")
        self.assertEqual(sc.parse_binding("Ctrl+Alt+Suppr").accel, "<Control><Alt>Delete")
        self.assertEqual(sc.parse_binding("Super+Espace").accel, "<Super>space")
        self.assertEqual(sc.parse_binding("Super+Échap").accel, "<Super>Escape")
        self.assertEqual(sc.parse_binding("Super+→").accel, "<Super>Right")
        self.assertEqual(sc.parse_binding("Super+-").accel, "<Super>minus")
        self.assertEqual(sc.parse_binding("Super+Alt++").accel, "<Super><Alt>plus")
        self.assertEqual(sc.parse_binding("<Super>KP_5").accel, "<Super>KP_5")
        self.assertEqual(sc.parse_binding("<Super>eacute").accel, "<Super>eacute")
        self.assertEqual(sc.parse_binding("Super+É").accel, "<Super>eacute")
        self.assertEqual(sc.parse_binding("Ctrl+Alt+Retour arrière").accel, "<Control><Alt>BackSpace")

    def test_labels_round_trip(self):
        for accel in ("<Super><Alt>Page_Down", "<Control><Alt>space", "<Super>Left", "<Super>eacute",
                      "<Super><Alt>plus", "<Super><Shift>F5", "<Control><Alt>Delete", "<Super>Print"):
            self.assertEqual(sc.parse_binding(sc.label(accel)).accel, accel, accel)

    def test_media_key_alone_is_allowed(self):
        self.assertEqual(sc.parse_binding("XF86Launch1").accel, "XF86Launch1")

    def test_labels(self):
        self.assertEqual(sc.label("<Super><Alt>Page_Down"), "Super+Alt+Page suiv.")
        self.assertEqual(sc.label("<Control><Alt>space"), "Ctrl+Alt+Espace")
        self.assertEqual(sc.label("<Super>Left"), "Super+←")
        self.assertEqual(sc.label(""), "aucun")
        self.assertEqual(sc.label("n'importe quoi"), "n'importe quoi")

    def test_invalid(self):
        for text in ("", "   ", "c", "Shift+C", "<Shift>F5", "Super+", "<Super>", "<Super>Foo",
                     "<Bad>c", "<Super>Shift_L", "Super+Alt", "<Super><Alt>c d", "Super+Alt+Ctrl_L"):
            with self.subTest(text=text), self.assertRaises(sc.ShortcutError):
                sc.parse_binding(text)

    def test_messages_explain(self):
        with self.assertRaises(sc.ShortcutError) as cm:
            sc.parse_binding("c")
        self.assertIn("Super, Ctrl ou Alt", str(cm.exception))
        with self.assertRaises(sc.ShortcutError) as cm:
            sc.parse_binding("<Super>Foo")
        self.assertIn("Foo", str(cm.exception))

    def test_unknown_name_checked_with_gdk_when_present(self):
        with mock.patch.object(sc, "_gdk_known", return_value=True):
            self.assertEqual(sc.parse_binding("<Super>dead_grave").accel, "<Super>dead_grave")
        with mock.patch.object(sc, "_gdk_known", return_value=False), self.assertRaises(sc.ShortcutError):
            sc.parse_binding("<Super>dead_grave")

    def test_normalize_and_same(self):
        self.assertEqual(sc.normalize("Super+Alt+C"), "<Super><Alt>c")
        self.assertIsNone(sc.normalize("Super+Foo"))
        self.assertTrue(sc.same("<Primary><Alt>T", "<Alt><Control>t"))
        self.assertFalse(sc.same("<Super><Alt>t", "<Control><Alt>t"))
        self.assertFalse(sc.same("", ""))
        self.assertFalse(sc.same("Print", "Print!"))

    def test_is_modifier_key(self):
        for name in ("Shift_L", "super_r", "ISO_Level3_Shift", "Control_L", "Alt_R"):
            self.assertTrue(sc.is_modifier_key(name), name)
        for name in ("c", "space", "", None, "Super"):
            self.assertFalse(sc.is_modifier_key(name), name)

    def test_same_accepts_bindings_without_modifier(self):
        """Les raccourcis du bureau peuvent être une touche seule (Print) : ils se comparent."""
        self.assertTrue(sc.same("Print", "Print"))
        self.assertFalse(sc.same("Super_L", "Super_L"))


# --------------------------------------------------------------------------
# Actions et commandes
# --------------------------------------------------------------------------

class ActionsTest(unittest.TestCase):
    def test_actions_and_commands(self):
        ids = [a.id for a in sc.ACTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        cmds = {a.id: a.display for a in sc.ACTIONS}
        self.assertEqual(cmds, {
            "ouvrir": "claude-accounts gui",
            "sessions": "claude-accounts gui --page sessions",
            "nouvelle-session": "claude-accounts gui --new-session",
            "suivant": "ccs next --notifier",
            "meilleur": "ccs best --notifier",
            "pause": "ccs pause 1h --notifier",
            "reprendre": "ccs pause off --notifier",
        })

    def test_defaults_valid_distinct_and_free_of_known_gnome_shortcuts(self):
        accels = [sc.parse_binding(a.default).accel for a in sc.ACTIONS]
        self.assertEqual(len(accels), len(set(accels)))
        b = gnome()
        for a in sc.ACTIONS:
            self.assertEqual(sc.conflicts(a.default, backend=b), [], a.id)

    def test_paths_are_ours(self):
        for a in sc.ACTIONS:
            self.assertTrue(a.path.startswith(DIR + "ccs-"))
            self.assertTrue(a.path.endswith("/"))
            self.assertTrue(sc.is_ours(a.path))
        self.assertFalse(sc.is_ours(DIR + "custom0/"))
        self.assertFalse(sc.is_ours("/ailleurs/ccs-ouvrir/"))

    def test_unknown_action(self):
        with self.assertRaises(sc.ShortcutError) as cm:
            sc.action("inconnue")
        self.assertIn("ouvrir", str(cm.exception))

    def test_command_prefers_installed_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            usr, repo = Path(tmp, "usr"), Path(tmp, "repo")
            for d in (usr, repo):
                d.mkdir()
                for prog in ("ccs", "claude-accounts"):
                    p = d / prog
                    p.write_text("#!/bin/sh\n")
                    p.chmod(0o755)
            with mock.patch.object(sc, "USR_BIN", usr), mock.patch.object(sc, "REPO_BIN", repo):
                self.assertEqual(sc.command_for(sc.action("suivant")), f"{usr}/ccs next --notifier")
                (usr / "ccs").unlink()
                self.assertEqual(sc.command_for(sc.action("suivant")), f"{repo}/ccs next --notifier")
                self.assertEqual(sc.command_for(sc.action("sessions")),
                                 f"{usr}/claude-accounts gui --page sessions")

    def test_command_quotes_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp, "mon dépôt")
            repo.mkdir()
            p = repo / "ccs"
            p.write_text("#!/bin/sh\n")
            p.chmod(0o755)
            with mock.patch.object(sc, "USR_BIN", Path(tmp, "absent")), \
                    mock.patch.object(sc, "REPO_BIN", repo):
                self.assertEqual(sc.command_for(sc.action("pause")), f"'{repo}/ccs' pause 1h --notifier")


# --------------------------------------------------------------------------
# Prise en charge du bureau
# --------------------------------------------------------------------------

class SupportedTest(SafetyMixin, unittest.TestCase):
    def test_gnome(self):
        s = sc.supported(gnome(), environ={"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"})
        self.assertTrue(s.ok)
        self.assertEqual(s.message, "")

    def test_unknown_desktop_relies_on_schemas(self):
        self.assertTrue(sc.supported(gnome(), environ={}).ok)

    def test_other_desktop(self):
        s = sc.supported(gnome(), environ={"XDG_CURRENT_DESKTOP": "KDE"})
        self.assertFalse(s.ok)
        self.assertIn("GNOME", s.message)
        self.assertIn("KDE", s.message)

    def test_missing_schemas(self):
        s = sc.supported(sc.MemoryBackend(), environ={"XDG_CURRENT_DESKTOP": "GNOME"})
        self.assertFalse(s.ok)
        self.assertIn("schéma", s.message.lower())

    def test_no_gio(self):
        with mock.patch.object(sc, "default_backend", side_effect=sc.ShortcutError("Gio absent")):
            s = sc.supported(environ={"XDG_CURRENT_DESKTOP": "GNOME"})
        self.assertFalse(s.ok)
        self.assertIn("Gio absent", s.message)

    def test_operations_refused_when_unsupported(self):
        b = sc.MemoryBackend()
        with self.assertRaises(sc.ShortcutError):
            sc.install("ouvrir", backend=b)
        self.assertEqual(b.log, [])


# --------------------------------------------------------------------------
# Installation, retrait, liste des raccourcis personnalisés
# --------------------------------------------------------------------------

class InstallTest(SafetyMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.b = gnome()
        p = mock.patch.object(sc, "command_for", side_effect=lambda a: "/usr/bin/" + a.display)
        p.start()
        self.addCleanup(p.stop)

    def test_install_appends_our_path_and_keeps_the_list(self):
        item = sc.install("ouvrir", backend=self.b)
        path = DIR + "ccs-ouvrir/"
        self.assertEqual(custom_list(self.b), FOREIGN + [path])
        self.assertEqual(custom(self.b, path), {
            "name": "CCS : Ouvrir Comptes Claude", "command": "/usr/bin/claude-accounts gui",
            "binding": "<Super><Alt>c"})
        self.assertTrue(item.installed)
        self.assertEqual(item.binding, "<Super><Alt>c")
        self.assertEqual(item.conflicts, [])
        for p, (name, _c, _b) in zip(FOREIGN, [("play-previous", 0, 0), ("play-next", 0, 0),
                                                ("play-pause", 0, 0)]):
            self.assertEqual(custom(self.b, p)["name"], name)

    def test_values_written_before_the_list_in_one_change_each(self):
        sc.install("suivant", backend=self.b)
        self.assertEqual([(op, schema) for op, schema, _p, _v in self.b.log],
                         [("set", sc.CUSTOM_SCHEMA), ("set", sc.MEDIA_KEYS)])
        self.assertEqual(set(self.b.log[0][3]), {"name", "command", "binding"})
        self.assertEqual(self.b.log[1][3], {sc.CUSTOM_KEY: FOREIGN + [DIR + "ccs-suivant/"]})

    def test_install_twice_does_not_duplicate(self):
        sc.install("ouvrir", backend=self.b)
        self.b.log.clear()
        sc.install("ouvrir", "Super+Alt+O", backend=self.b)
        self.assertEqual(custom_list(self.b), FOREIGN + [DIR + "ccs-ouvrir/"])
        self.assertEqual(custom(self.b, DIR + "ccs-ouvrir/")["binding"], "<Super><Alt>o")
        self.assertEqual([op for op, *_ in self.b.log], ["set"])  # liste inchangée : pas réécrite

    def test_install_keeps_current_binding(self):
        sc.install("ouvrir", "Super+Alt+O", backend=self.b)
        sc.install("ouvrir", backend=self.b)
        self.assertEqual(custom(self.b, DIR + "ccs-ouvrir/")["binding"], "<Super><Alt>o")

    def test_install_invalid_binding_writes_nothing(self):
        with self.assertRaises(sc.ShortcutError):
            sc.install("ouvrir", "c", backend=self.b)
        self.assertEqual(self.b.log, [])
        self.assertEqual(custom_list(self.b), FOREIGN)

    def test_install_reports_conflicts_but_installs(self):
        item = sc.install("sessions", "<Super><Alt>s", backend=self.b)
        self.assertTrue(item.installed)
        self.assertEqual([c.name for c in item.conflicts], ["Lecteur d'écran"])
        self.assertIn(DIR + "ccs-sessions/", custom_list(self.b))

    def test_remove_only_ours_and_keeps_order(self):
        sc.install("ouvrir", backend=self.b)
        sc.install("pause", backend=self.b)
        self.b.set(sc.CUSTOM_SCHEMA, {"name": "à moi", "command": "x", "binding": "<Super>F9"},
                   DIR + "custom3/")
        self.b.set(sc.MEDIA_KEYS, {sc.CUSTOM_KEY: custom_list(self.b) + [DIR + "custom3/"]})
        self.b.log.clear()
        self.assertTrue(sc.remove("ouvrir", backend=self.b))
        self.assertEqual(custom_list(self.b), FOREIGN + [DIR + "ccs-pause/", DIR + "custom3/"])
        self.assertEqual(custom(self.b, DIR + "ccs-ouvrir/"), {"name": "", "command": "", "binding": ""})
        self.assertEqual(custom(self.b, DIR + "custom3/")["name"], "à moi")
        # La liste d'abord (le bureau oublie le raccourci), puis les valeurs.
        self.assertEqual([(op, schema) for op, schema, _p, _v in self.b.log],
                         [("set", sc.MEDIA_KEYS), ("reset", sc.CUSTOM_SCHEMA)])

    def test_remove_not_installed(self):
        self.assertFalse(sc.remove("ouvrir", backend=self.b))
        self.assertEqual(self.b.log, [])

    def test_remove_duplicates_of_our_path(self):
        path = DIR + "ccs-meilleur/"
        self.b.set(sc.MEDIA_KEYS, {sc.CUSTOM_KEY: [path] + FOREIGN + [path]})
        self.assertTrue(sc.remove("meilleur", backend=self.b))
        self.assertEqual(custom_list(self.b), FOREIGN)

    def test_remove_all_only_ours(self):
        for a in ("ouvrir", "suivant", "reprendre"):
            sc.install(a, backend=self.b)
        old = DIR + "ccs-ancienne-action/"  # action d'une ancienne version
        self.b.set(sc.MEDIA_KEYS, {sc.CUSTOM_KEY: [old] + custom_list(self.b)})
        self.b.log.clear()
        removed = sc.remove_all(backend=self.b)
        self.assertEqual(removed, ["ccs-ancienne-action", "ouvrir", "suivant", "reprendre"])
        self.assertEqual(custom_list(self.b), FOREIGN)
        self.assertEqual(sum(1 for op, schema, *_ in self.b.log if schema == sc.MEDIA_KEYS), 1)
        for p in FOREIGN:
            self.assertNotEqual(custom(self.b, p)["command"], "")

    def test_remove_all_nothing(self):
        self.assertEqual(sc.remove_all(backend=self.b), [])
        self.assertEqual(self.b.log, [])

    def test_list_reread_just_before_writing(self):
        """Un raccourci ajouté ailleurs entre-temps (Réglages GNOME) n'est jamais perdu :
        la liste est relue après l'écriture des valeurs, juste avant d'être réécrite."""
        real_set = self.b.set

        def set_(schema, values, path=None):
            real_set(schema, values, path)
            if schema == sc.CUSTOM_SCHEMA:  # quelqu'un ajoute un raccourci à cet instant
                real_set(sc.MEDIA_KEYS, {sc.CUSTOM_KEY: custom_list(self.b) + [DIR + "custom9/"]})
        with mock.patch.object(self.b, "set", side_effect=set_):
            sc.install("ouvrir", backend=self.b)
        self.assertEqual(custom_list(self.b), FOREIGN + [DIR + "custom9/", DIR + "ccs-ouvrir/"])

    def test_set_binding_installed(self):
        sc.install("pause", backend=self.b)
        self.b.log.clear()
        item = sc.set_binding("pause", "Super+Alt+F12", backend=self.b)
        self.assertEqual(item.binding, "<Super><Alt>F12")
        self.assertEqual(self.b.log, [("set", sc.CUSTOM_SCHEMA, DIR + "ccs-pause/",
                                       {"binding": "<Super><Alt>F12"})])

    def test_set_binding_not_installed_installs(self):
        item = sc.set_binding("pause", "Super+Alt+F12", backend=self.b)
        self.assertTrue(item.installed)
        self.assertEqual(custom_list(self.b), FOREIGN + [DIR + "ccs-pause/"])
        self.assertEqual(custom(self.b, DIR + "ccs-pause/")["command"], "/usr/bin/ccs pause 1h --notifier")

    def test_set_binding_invalid(self):
        sc.install("pause", backend=self.b)
        self.b.log.clear()
        with self.assertRaises(sc.ShortcutError):
            sc.set_binding("pause", "Super+Foo", backend=self.b)
        self.assertEqual(self.b.log, [])

    def test_update_commands(self):
        sc.install("ouvrir", backend=self.b)
        sc.install("suivant", backend=self.b)
        self.b.set(sc.CUSTOM_SCHEMA, {"command": "/vieux/depot/bin/ccs next"}, DIR + "ccs-suivant/")
        self.b.log.clear()
        self.assertEqual(sc.update_commands(backend=self.b), ["suivant"])
        self.assertEqual(custom(self.b, DIR + "ccs-suivant/")["command"], "/usr/bin/ccs next --notifier")
        self.assertEqual(sc.update_commands(backend=self.b), [])

    def test_shortcuts_installed_without_notifier_are_outdated(self):
        """Raccourcis de la 0.6 de développement (sans --notifier) : à mettre à jour, raccourci
        gardé ; les commandes de l'application, elles, n'ont pas changé."""
        for act in ("ouvrir", "suivant", "meilleur", "pause", "reprendre"):
            sc.install(act, backend=self.b)
        old = {"suivant": "ccs next", "meilleur": "ccs best", "pause": "ccs pause 1h",
               "reprendre": "ccs pause off"}
        for act, cmd in old.items():
            self.b.set(sc.CUSTOM_SCHEMA, {"command": "/usr/bin/" + cmd}, DIR + f"ccs-{act}/")
        sc.set_binding("pause", "Super+Alt+F12", backend=self.b)
        self.b.set(sc.CUSTOM_SCHEMA, {"command": "/usr/bin/ccs pause 1h"}, DIR + "ccs-pause/")
        st = sc.status(backend=self.b)
        self.assertEqual([i.id for i in st.items if i.outdated], list(old))
        self.assertIn("commande à mettre à jour : ccs raccourcis on suivant", sc.format_text(st))
        self.assertEqual(sc.update_commands(backend=self.b), list(old))
        for act, cmd in old.items():
            self.assertEqual(custom(self.b, DIR + f"ccs-{act}/")["command"], f"/usr/bin/{cmd} --notifier")
        self.assertEqual(custom(self.b, DIR + "ccs-pause/")["binding"], "<Super><Alt>F12")
        self.assertFalse(any(i.outdated for i in sc.status(backend=self.b).items))


# --------------------------------------------------------------------------
# Conflits
# --------------------------------------------------------------------------

class ConflictsTest(SafetyMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.b = gnome()

    def test_desktop_shortcut(self):
        found = sc.conflicts("Ctrl+Alt+T", backend=self.b)
        self.assertEqual([(c.kind, c.name, c.binding) for c in found],
                         [("bureau", "Lancer un terminal", "<Primary><Alt>t")])
        self.assertEqual((found[0].schema, found[0].key), (sc.MEDIA_KEYS, "terminal"))
        self.assertEqual(found[0].describe(), "Lancer un terminal (raccourci du bureau)")

    def test_name_from_summary_then_key(self):
        self.b.add_schema("org.gnome.mutter.keybindings", {"toggle-tiled-left": ["<Super><Alt>F1"],
                                                           "obscure": ["<Super><Alt>F2"]})
        self.b.summaries[("org.gnome.mutter.keybindings", "toggle-tiled-left")] = "View split on left"
        self.assertEqual(sc.conflicts("<Super><Alt>F1", backend=self.b)[0].name, "View split on left")
        self.assertEqual(sc.conflicts("<Super><Alt>F2", backend=self.b)[0].name, "obscure")

    def test_second_value_of_a_list(self):
        self.assertEqual([c.key for c in sc.conflicts("<Super>m", backend=self.b)],
                         ["toggle-message-tray"])

    def test_same_shortcut_repeated_as_text_counts_once(self):
        """Le Dock range son raccourci dans une liste et dans une chaîne."""
        self.b.add_schema("org.gnome.shell.extensions.dash-to-dock",
                          {"shortcut": ["<Super>q"], "shortcut-text": "<Super>q", "dock-position": "BOTTOM"})
        self.assertEqual([c.name for c in sc.conflicts("<Super>q", backend=self.b)],
                         ["Dock : afficher les numéros"])

    def test_foreign_custom_shortcut(self):
        found = sc.conflicts("<Control><Alt>space", backend=self.b)
        self.assertEqual([(c.kind, c.name) for c in found], [("personnalisé", "play-pause")])
        self.assertEqual(found[0].path, FOREIGN[2])

    def test_other_ccs_action_and_exclusion(self):
        with mock.patch.object(sc, "command_for", side_effect=lambda a: a.display):
            sc.install("ouvrir", backend=self.b)
        found = sc.conflicts("<Super><Alt>c", backend=self.b)
        self.assertEqual([(c.kind, c.name) for c in found], [("ccs", "Ouvrir Comptes Claude")])
        self.assertEqual(sc.conflicts("<Super><Alt>c", exclude="ouvrir", backend=self.b), [])

    def test_no_conflict_and_invalid(self):
        self.assertEqual(sc.conflicts("<Super><Alt>c", backend=self.b), [])
        self.assertEqual(sc.conflicts("pas un raccourci", backend=self.b), [])

    def test_missing_optional_schemas_are_skipped(self):
        b = sc.MemoryBackend.gnome()
        self.assertEqual(sc.conflicts("<Super><Alt>c", backend=b), [])

    def test_unreadable_key_is_skipped(self):
        real_get = self.b.get

        def get(schema, key, path=None):
            if key == "close":
                raise RuntimeError("clé illisible")
            return real_get(schema, key, path)
        with mock.patch.object(self.b, "get", side_effect=get):
            self.assertEqual([c.name for c in sc.conflicts("<Alt><Super>s", backend=self.b)],
                             ["Lecteur d'écran"])


@unittest.skipUnless(sc.installed_schemas_available(), "schémas GNOME absents")
class StockGnomeTest(unittest.TestCase):
    def test_defaults_free_in_stock_gnome(self):
        """Valeurs par défaut des schémas installés (jamais les réglages de l'utilisateur)."""
        b = sc.MemoryBackend.from_installed_defaults()
        self.assertGreater(len(b.keys("org.gnome.desktop.wm.keybindings")), 10)
        for a in sc.ACTIONS:
            self.assertEqual(sc.conflicts(a.default, backend=b), [], a.id)
        self.assertTrue(sc.conflicts("<Super><Alt>s", backend=b))  # lecteur d'écran


# --------------------------------------------------------------------------
# État et texte de « ccs raccourcis »
# --------------------------------------------------------------------------

class StatusTest(SafetyMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.b = gnome()
        p = mock.patch.object(sc, "command_for", side_effect=lambda a: "/usr/bin/" + a.display)
        p.start()
        self.addCleanup(p.stop)

    def test_status(self):
        sc.install("ouvrir", backend=self.b)
        sc.install("sessions", "<Super><Alt>s", backend=self.b)
        self.b.set(sc.CUSTOM_SCHEMA, {"command": "/ancien/ccs gui"}, DIR + "ccs-ouvrir/")
        st = sc.status(backend=self.b)
        self.assertTrue(st.support.ok)
        self.assertEqual([i.id for i in st.items], [a.id for a in sc.ACTIONS])
        ouvrir, sessions, nouvelle = st.item("ouvrir"), st.item("sessions"), st.item("nouvelle-session")
        self.assertTrue(ouvrir.installed)
        self.assertTrue(ouvrir.outdated)
        self.assertEqual(ouvrir.installed_command, "/ancien/ccs gui")
        self.assertEqual(sessions.binding_label, "Super+Alt+S")
        self.assertEqual([c.name for c in sessions.conflicts], ["Lecteur d'écran"])
        self.assertFalse(nouvelle.installed)
        self.assertEqual(nouvelle.binding, nouvelle.action.default)
        self.assertFalse(nouvelle.outdated)
        self.assertEqual([i.id for i in st.installed], ["ouvrir", "sessions"])

    def test_status_binding_cleared_in_gnome_settings(self):
        sc.install("ouvrir", backend=self.b)
        self.b.set(sc.CUSTOM_SCHEMA, {"binding": ""}, DIR + "ccs-ouvrir/")
        item = sc.status(backend=self.b).item("ouvrir")
        self.assertTrue(item.installed)
        self.assertEqual(item.binding, "")
        self.assertEqual(item.binding_label, "aucun")
        self.assertEqual(item.conflicts, [])

    def test_status_unsupported(self):
        st = sc.status(backend=sc.MemoryBackend())
        self.assertFalse(st.support.ok)
        self.assertEqual(st.items, [])
        text = sc.format_text(st)
        self.assertIn(st.support.message, text)
        self.assertIn("ccs next", text)  # les commandes à créer à la main

    def test_format_text(self):
        sc.install("ouvrir", backend=self.b)
        sc.install("sessions", "<Super><Alt>s", backend=self.b)
        text = sc.format_text(sc.status(backend=self.b))
        self.assertIn("Raccourcis clavier", text)
        self.assertRegex(text, r"✔ Ouvrir Comptes Claude\s+Super\+Alt\+C")
        self.assertRegex(text, r"⚠ Afficher les sessions\s+Super\+Alt\+S")
        self.assertIn("Lecteur d'écran", text)
        self.assertRegex(text, r"· Pause 1 h\s+Super\+Alt\+P\s+\(désactivé\)")
        self.assertIn("ccs raccourcis on", text)


class CommandTest(SafetyMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.b = gnome()
        p = mock.patch.object(sc, "command_for", side_effect=lambda a: "/usr/bin/" + a.display)
        p.start()
        self.addCleanup(p.stop)

    def test_status_default(self):
        code, text = sc.command([], backend=self.b)
        self.assertEqual(code, 0)
        self.assertIn("Raccourcis clavier", text)
        self.assertEqual(sc.command(["status"], backend=self.b)[1], text)

    def test_on_all_then_off_all(self):
        code, text = sc.command(["on"], backend=self.b)
        self.assertEqual(code, 0)
        self.assertEqual(custom_list(self.b), FOREIGN + [a.path for a in sc.ACTIONS])
        self.assertIn("Super+Alt+C", text)
        code, text = sc.command(["off"], backend=self.b)
        self.assertEqual(code, 0)
        self.assertEqual(custom_list(self.b), FOREIGN)
        self.assertIn("retiré", text)

    def test_on_and_off_some(self):
        self.assertEqual(sc.command(["on", "pause", "reprendre"], backend=self.b)[0], 0)
        self.assertEqual(custom_list(self.b), FOREIGN + [DIR + "ccs-pause/", DIR + "ccs-reprendre/"])
        self.assertEqual(sc.command(["off", "pause"], backend=self.b)[0], 0)
        self.assertEqual(custom_list(self.b), FOREIGN + [DIR + "ccs-reprendre/"])

    def test_on_unknown_action_writes_nothing(self):
        code, text = sc.command(["on", "pause", "zut"], backend=self.b)
        self.assertEqual(code, 2)
        self.assertIn("zut", text)
        self.assertEqual(custom_list(self.b), FOREIGN)

    def test_on_with_conflict_warns(self):
        sc.install("sessions", "<Super><Alt>s", backend=self.b)
        code, text = sc.command(["on", "sessions"], backend=self.b)
        self.assertEqual(code, 0)
        self.assertIn("Lecteur d'écran", text)

    def test_set(self):
        code, text = sc.command(["set", "suivant", "Super+Alt+Page_Down"], backend=self.b)
        self.assertEqual(code, 0)
        self.assertIn("Super+Alt+Page suiv.", text)
        self.assertEqual(custom(self.b, DIR + "ccs-suivant/")["binding"], "<Super><Alt>Page_Down")

    def test_set_errors(self):
        self.assertEqual(sc.command(["set", "suivant"], backend=self.b)[0], 2)
        code, text = sc.command(["set", "suivant", "c"], backend=self.b)
        self.assertEqual(code, 1)
        self.assertIn("Super, Ctrl ou Alt", text)

    def test_unknown_subcommand(self):
        code, text = sc.command(["zut"], backend=self.b)
        self.assertEqual(code, 2)
        self.assertIn("ccs raccourcis", text)

    def test_unsupported(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}):
            code, text = sc.command(["on"], backend=self.b)
            self.assertEqual(code, 1)
            self.assertIn("GNOME", text)
            self.assertEqual(sc.command([], backend=self.b)[0], 1)
        self.assertEqual(custom_list(self.b), FOREIGN)


class MemoryBackendTest(unittest.TestCase):
    def test_watch(self):
        b = sc.MemoryBackend.gnome()
        seen = []
        token = b.watch(lambda: seen.append(1))
        b.set(sc.MEDIA_KEYS, {sc.CUSTOM_KEY: ["/x/"]})
        b.unwatch(token)
        b.set(sc.MEDIA_KEYS, {sc.CUSTOM_KEY: []})
        self.assertEqual(seen, [1])

    def test_unknown_key(self):
        b = sc.MemoryBackend.gnome()
        with self.assertRaises(KeyError):
            b.get(sc.MEDIA_KEYS, "nope")
        with self.assertRaises(KeyError):
            b.set("schema.absent", {"a": 1})


if __name__ == "__main__":
    unittest.main()
