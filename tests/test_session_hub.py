"""Onglet Sessions (logique pure) : liste des projets, recherche et filtre communs, projet
d'une session désignée par une notification."""

import unittest

from ccs_app import session_hub as hub
from ccs_app.conversations import Conversation
from ccs_app.project_accounts import Association
from ccs_app.sessions import Session

HOME = "/home/u"
APP, SITE, VIEUX = f"{HOME}/Work/App", f"{HOME}/Work/Site", f"{HOME}/Old/Vieux"
NOW = 1_800_000_000.0


def conv(sid, cwd, title, updated, origin="terminal", prompts=1, first="", last="", exists=True):
    return Conversation(session_id=sid, path=f"/j/{sid}.jsonl", cwd=cwd, title=title,
                        first_prompt=first or title, last_prompt=last or first or title, prompts=prompts,
                        started_at=None, updated_at=updated, origin=origin, git_branch="", size=10,
                        folder_exists=exists)


def sess(pid, sid, cwd, state="idle", entrypoint="cli", since=NOW - 60, name=None):
    project = cwd.rsplit("/", 1)[-1] if cwd else "?"
    return Session(pid=pid, session_id=sid, name=name or f"s{pid}", cwd=cwd, project=project, state=state,
                   waiting_for="permission" if state == "waiting" else None, started_at=since - 600,
                   state_since=since, kind="interactive", entrypoint=entrypoint)


CONVS = [
    conv("c1", APP, "Export CSV", NOW - 100),
    conv("c2", SITE, "Refonte du site", NOW - 50, origin="vscode"),
    conv("c3", APP, "Calcul des intérêts", NOW - 3000, first="corrige le calcul des intérêts"),
    conv("c4", VIEUX, "Ancien travail", NOW - 9000, exists=False),
]


def names(view):
    return [e.name for e in view.entries]


class BuildTest(unittest.TestCase):
    def test_all_first_then_by_last_activity(self):
        view = hub.build(CONVS, [], home=HOME)
        self.assertEqual(names(view), ["Tous les projets", "Site", "App", "Vieux"])
        self.assertIsNone(view.entries[0].cwd)
        self.assertIs(view.selected, view.entries[0])

    def test_projects_with_an_open_session_come_first(self):
        found = [sess(42, "c3", APP, since=NOW - 7200)]
        view = hub.build(CONVS, found, home=HOME)
        self.assertEqual(names(view), ["Tous les projets", "App", "Site", "Vieux"])

    def test_counts_and_activity(self):
        found = [sess(1, "c1", APP, "waiting"), sess(2, "c3", APP, "busy"), sess(3, "c2", SITE)]
        view = hub.build(CONVS, found, home=HOME)
        by_cwd = {e.cwd: e for e in view.entries}
        everything, app, site, vieux = by_cwd[None], by_cwd[APP], by_cwd[SITE], by_cwd[VIEUX]
        self.assertEqual((everything.conversations, everything.total, everything.open, everything.waiting),
                         (4, 4, 3, 1))
        self.assertEqual((app.conversations, app.total, app.open, app.waiting), (2, 2, 2, 1))
        self.assertEqual(app.activity, "attention")
        self.assertEqual(site.activity, "ouverte")
        self.assertIsNone(vieux.activity)
        self.assertEqual(everything.activity, "attention")

    def test_last_activity(self):
        found = [sess(1, "x", SITE, since=NOW - 10)]
        view = hub.build(CONVS, found, home=HOME)
        site = next(e for e in view.entries if e.cwd == SITE)
        app = next(e for e in view.entries if e.cwd == APP)
        self.assertEqual(site.last, NOW - 10)
        self.assertEqual(app.last, NOW - 100)

    def test_project_with_only_an_open_session(self):
        neuf = f"{HOME}/Work/Neuf"
        view = hub.build(CONVS, [sess(5, "n1", neuf, "busy")], home=HOME)
        entry = view.entries[1]
        self.assertEqual((entry.cwd, entry.name, entry.conversations, entry.open), (neuf, "Neuf", 0, 1))
        self.assertTrue(entry.exists)

    def test_same_name_shows_the_path(self):
        other = f"{HOME}/Perso/App"
        view = hub.build(CONVS + [conv("c9", other, "Autre app", NOW - 20)], [], home=HOME)
        self.assertIn("~/Perso/App", names(view))
        self.assertIn("~/Work/App", names(view))
        self.assertNotIn("App", names(view))

    def test_missing_folder_and_suggestion(self):
        view = hub.build(CONVS, [], suggestions={"c4": f"{HOME}/Work/Vieux"}, home=HOME)
        vieux = view.entries[-1]
        self.assertFalse(vieux.exists)
        self.assertEqual(vieux.moved_to, f"{HOME}/Work/Vieux")

    def test_unknown_folder(self):
        view = hub.build([conv("c8", "", "Sans dossier", NOW - 5, exists=False)], [], home=HOME)
        entry = view.entries[1]
        self.assertEqual((entry.cwd, entry.name, entry.exists), ("", "Dossier inconnu", False))

    def test_account_of_the_project_or_its_parent(self):
        assocs = [Association(f"{HOME}/Work", "pro"), Association(SITE, "perso")]
        view = hub.build(CONVS, [], associations=assocs, home=HOME)
        accounts = {e.cwd: e.profile for e in view.entries}
        self.assertEqual(accounts[APP], "pro")
        self.assertEqual(accounts[SITE], "perso")
        self.assertIsNone(accounts[VIEUX])
        self.assertIsNone(accounts[None])

    def test_selected_project(self):
        found = [sess(1, "c1", APP), sess(2, "c2", SITE)]
        view = hub.build(CONVS, found, selected=APP, home=HOME)
        self.assertEqual(view.selected.cwd, APP)
        self.assertEqual([c.session_id for c in view.conversations], ["c1", "c3"])
        self.assertEqual([s.pid for s in view.sessions], [1])
        self.assertEqual(view.total, 2)
        self.assertFalse(view.filtering)

    def test_all_shows_everything(self):
        found = [sess(1, "c1", APP), sess(2, "c2", SITE)]
        view = hub.build(CONVS, found, home=HOME)
        self.assertEqual([c.session_id for c in view.conversations], ["c1", "c2", "c3", "c4"])
        self.assertEqual([s.pid for s in view.sessions], [1, 2])
        self.assertEqual(view.total, 4)

    def test_number_of_projects_ignores_the_search(self):
        found = [sess(1, "x", f"{HOME}/Work/Neuf")]
        self.assertEqual(hub.build(CONVS, found, home=HOME).projects, 4)
        self.assertEqual(hub.build(CONVS, found, query="calcul", home=HOME).projects, 4)
        unknown = CONVS + [conv("c8", "", "Sans dossier", NOW - 5, exists=False)]
        self.assertEqual(hub.build(unknown, [], home=HOME).projects, 3)   # « dossier inconnu » ne compte pas

    def test_vanished_project_falls_back_to_all(self):
        view = hub.build(CONVS, [], selected=f"{HOME}/Work/Disparu", home=HOME)
        self.assertIsNone(view.selected.cwd)
        self.assertEqual(len(view.conversations), 4)


class FilterTest(unittest.TestCase):
    def test_query_without_accents_or_case(self):
        view = hub.build(CONVS, [], query="INTERETS", home=HOME)
        self.assertEqual([c.session_id for c in view.conversations], ["c3"])
        self.assertTrue(view.filtering)
        self.assertEqual(view.total, 4)

    def test_query_matches_prompts_and_project(self):
        self.assertEqual([c.session_id for c in hub.filter_conversations(CONVS, "corrige")], ["c3"])
        self.assertEqual([c.session_id for c in hub.filter_conversations(CONVS, "site")], ["c2"])

    def test_project_list_follows_the_search(self):
        view = hub.build(CONVS, [], query="calcul", home=HOME)
        self.assertEqual(names(view), ["Tous les projets", "App"])
        self.assertEqual((view.entries[0].conversations, view.entries[1].conversations), (1, 1))
        self.assertEqual(view.entries[1].total, 2)

    def test_selected_project_kept_without_match(self):
        view = hub.build(CONVS, [], selected=SITE, query="calcul", home=HOME)
        self.assertIn("Site", names(view))
        self.assertEqual(view.selected.cwd, SITE)
        self.assertEqual(view.selected.conversations, 0)
        self.assertEqual(view.conversations, [])

    def test_sessions_follow_the_search(self):
        found = [sess(1, "c1", APP), sess(2, "c2", SITE)]
        titles = {"c1": "Export CSV", "c2": "Refonte du site"}
        view = hub.build(CONVS, found, query="export", titles=titles, home=HOME)
        self.assertEqual([s.pid for s in view.sessions], [1])
        self.assertEqual(view.entries[0].open, 1)
        # Le nom du projet compte aussi.
        self.assertEqual([s.pid for s in hub.filter_sessions(found, "site", titles={"c2": "Refonte"})], [2])
        self.assertEqual([s.pid for s in hub.filter_sessions(found, project=APP)], [1])

    def test_origin_filter(self):
        found = [sess(1, "c1", APP), sess(2, "c2", SITE, entrypoint="claude-vscode")]
        view = hub.build(CONVS, found, origin="vscode", home=HOME)
        self.assertEqual([c.session_id for c in view.conversations], ["c2"])
        self.assertEqual([s.pid for s in view.sessions], [2])
        self.assertEqual(names(view), ["Tous les projets", "Site"])
        terminal = hub.build(CONVS, found, origin="terminal", home=HOME)
        self.assertEqual([s.pid for s in terminal.sessions], [1])

    def test_session_origin(self):
        self.assertEqual(hub.session_origin(sess(1, "a", APP, entrypoint="claude-vscode")), "vscode")
        self.assertEqual(hub.session_origin(sess(1, "a", APP, entrypoint="cli")), "terminal")
        self.assertEqual(hub.session_origin(sess(1, "a", APP, entrypoint="")), "terminal")
        self.assertEqual(hub.session_origin(sess(1, "a", APP, entrypoint="sdk-py")), "autre")

    def test_unknown_folder_project_filter(self):
        convs = CONVS + [conv("c8", "", "Sans dossier", NOW - 5, exists=False)]
        self.assertEqual([c.session_id for c in hub.filter_conversations(convs, project="")], ["c8"])


class RefTest(unittest.TestCase):
    def test_session_by_pid_then_by_id(self):
        found = [sess(42, "c1", APP), sess(43, "c2", SITE)]
        self.assertEqual(hub.project_for_ref("43:zzz", found, CONVS), SITE)
        self.assertEqual(hub.project_for_ref("42", found, CONVS), APP)
        self.assertEqual(hub.project_for_ref("c2", found, CONVS), SITE)

    def test_closed_session_uses_its_conversation(self):
        self.assertEqual(hub.project_for_ref("999:c3", [], CONVS), APP)

    def test_unknown_or_illegible(self):
        self.assertIsNone(hub.project_for_ref("999:inconnu", [], CONVS))
        self.assertIsNone(hub.project_for_ref("pas une ref !", [], CONVS))
        self.assertIsNone(hub.project_for_ref("", [], CONVS))


class TextTest(unittest.TestCase):
    def entry(self, **kw):
        base = dict(cwd=APP, name="App", conversations=3, total=3, open=0, waiting=0, last=NOW)
        return hub.ProjectEntry(**{**base, **kw})

    def test_detail_of_a_project(self):
        self.assertEqual(hub.entry_detail(self.entry()), ("", False))
        self.assertEqual(hub.entry_detail(self.entry(open=1)), ("1 session ouverte", False))
        self.assertEqual(hub.entry_detail(self.entry(open=2, profile="pro")),
                         ("2 sessions ouvertes · compte pro", False))
        self.assertEqual(hub.entry_detail(self.entry(open=2, waiting=1)), ("attend ta réponse", False))
        self.assertEqual(hub.entry_detail(self.entry(open=3, waiting=2)), ("2 attendent ta réponse", False))

    def test_detail_of_a_missing_folder(self):
        self.assertEqual(hub.entry_detail(self.entry(exists=False)), ("dossier introuvable", True))
        self.assertEqual(hub.entry_detail(self.entry(exists=False, moved_to="/x")),
                         ("dossier introuvable · déplacé ?", True))
        self.assertEqual(hub.entry_detail(self.entry(cwd="", exists=False)), ("dossier inconnu", True))

    def test_detail_of_all(self):
        everything = self.entry(cwd=None, name="Tous les projets")
        self.assertEqual(hub.entry_detail(everything), ("", False))
        self.assertEqual(hub.entry_detail(self.entry(cwd=None, open=2)), ("2 sessions ouvertes", False))
        # Plus court quand une session attend : la colonne est étroite.
        self.assertEqual(hub.entry_detail(self.entry(cwd=None, open=2, waiting=1)),
                         ("2 sessions · 1 attend ta réponse", False))
        self.assertEqual(hub.entry_detail(self.entry(cwd=None, open=3, waiting=2)),
                         ("3 sessions · 2 attendent ta réponse", False))

    def test_count_text(self):
        self.assertEqual(hub.count_text(1, 1), "1 conversation")
        self.assertEqual(hub.count_text(12, 12), "12 conversations")
        self.assertEqual(hub.count_text(3, 340), "3 conversations sur 340")
        self.assertEqual(hub.count_text(0, 5), "0 conversation sur 5")

    def test_signature_changes_with_what_is_shown(self):
        a = hub.build(CONVS, [], home=HOME)
        b = hub.build(CONVS, [], home=HOME)
        c = hub.build(CONVS, [sess(1, "c1", APP, "waiting")], home=HOME)
        self.assertEqual(hub.entries_signature(a.entries), hub.entries_signature(b.entries))
        self.assertNotEqual(hub.entries_signature(a.entries), hub.entries_signature(c.entries))


if __name__ == "__main__":
    unittest.main()
