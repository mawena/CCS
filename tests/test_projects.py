"""Projets : liste, version, historique git de la feuille de route."""

import os
import subprocess
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ccs_app import projects
from tests.helpers import HomeTestCase


def conv(cwd, updated_at=1000.0):
    return SimpleNamespace(cwd=str(cwd), updated_at=updated_at)


class GitCase(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.repo = Path(self.tmp) / "depot"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")

    def git(self, *args, day=None):
        env = dict(os.environ)
        if day:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{day}T12:00:00+00:00"
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                              cwd=self.repo, check=True, capture_output=True, text=True,
                              env=env).stdout

    def commit(self, text, day, name="ROADMAP.md"):
        (self.repo / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"c {day}", day=day)


class HistoryTest(GitCase):
    def make_history(self):
        self.commit("# T\n## Phase 1 (0.1.0)\n- [ ] a\n- [ ] b\n## Phase 2\n- [ ] c\n",
                    "2026-11-01")
        self.git("tag", "v0.1.0", day="2026-11-01")
        self.commit("# T\n## Phase 1 (0.1.0)\n- [x] a\n- [ ] b\n## Phase 2\n- [ ] c\n",
                    "2026-11-02")
        self.commit("# T\n## Phase 1 (0.1.0)\n- [x] a\n- [x] b\n## Phase 2\n- [x] c\n"
                    "- [x] ajoutée déjà cochée\n", "2026-11-04")
        self.git("tag", "-a", "v0.2.0", "-m", "x", day="2026-11-04")

    def test_versions_from_tags(self):
        self.make_history()
        self.git("tag", "pas-une-version")
        h = projects.history(self.repo)
        self.assertEqual(h.versions, [("v0.1.0", date(2026, 11, 1)), ("v0.2.0", date(2026, 11, 4))])

    def test_checks_per_day_from_log(self):
        self.make_history()
        h = projects.history(self.repo)
        self.assertEqual(h.checks_per_day, {date(2026, 11, 2): 1, date(2026, 11, 4): 2})
        self.assertEqual(h.phase_done, {"Phase 1 (0.1.0)": date(2026, 11, 4),
                                        "Phase 2": date(2026, 11, 4)})

    def test_unfinished_phase_has_no_done_date(self):
        self.commit("## P\n- [ ] a\n- [ ] b\n", "2026-11-01")
        self.commit("## P\n- [x] a\n- [ ] b\n", "2026-11-02")
        h = projects.history(self.repo)
        self.assertEqual(h.checks_per_day, {date(2026, 11, 2): 1})
        self.assertEqual(h.phase_done, {})

    def test_cache_reused_until_head_moves(self):
        self.make_history()
        with mock.patch.object(projects, "_git", wraps=projects._git) as g:
            def logs():
                return [c for c in g.call_args_list if "log" in c.args[1]]
            first = projects.history(self.repo)
            n_first = g.call_count
            self.assertEqual(len(logs()), 1)
            second = projects.history(self.repo)
            self.assertEqual(len(logs()), 1)             # relu depuis le cache
            self.assertEqual(g.call_count, n_first + 1)  # seulement `rev-parse HEAD`
            self.assertEqual(second, first)
            self.assertTrue((self.store / "projects-cache.json").is_file())
            self.commit("# T\n## Phase 1 (0.1.0)\n- [x] a\n- [x] b\n## Phase 2\n- [x] c\n"
                        "- [x] ajoutée déjà cochée\n- [ ] z\n", "2026-11-05")
            projects.history(self.repo)
            self.assertEqual(len(logs()), 2)

    def test_corrupt_cache_is_ignored(self):
        self.make_history()
        self.store.mkdir(parents=True, exist_ok=True)
        (self.store / "projects-cache.json").write_text("{pas du json")
        self.assertEqual(len(projects.history(self.repo).versions), 2)

    def test_not_a_git_repo(self):
        plain = Path(self.tmp) / "simple"
        plain.mkdir()
        (plain / "ROADMAP.md").write_text("## P\n- [x] a\n")
        empty = projects.History([], {}, {})
        self.assertEqual(projects.history(plain), empty)
        self.assertEqual(projects.history(Path(self.tmp) / "absent"), empty)
        self.commit("## P\n- [x] a\n", "2026-11-01")
        with mock.patch.object(projects.subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(projects.history(self.repo), empty)
        with mock.patch.object(projects.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("git", 10)):
            self.assertEqual(projects.history(self.repo), empty)


class ListProjectsTest(GitCase):
    def test_version_and_current_phase(self):
        self.commit("# T\n## Phase 1 (0.1.0) ✅\n- [x] a\n## Phase 12 (0.10.0)\n- [x] b\n- [ ] c\n"
                    "## Phase 4 (idées)\n- [ ] d\n", "2026-11-01")
        self.git("tag", "v0.9.0")
        (p,) = projects.list_projects([conv(self.repo, 5.0)])
        self.assertEqual((p.name, p.path, p.version), ("depot", self.repo, "0.9.0"))
        self.assertEqual(p.roadmap_path, self.repo / "ROADMAP.md")
        self.assertEqual(p.current_phase.title, "Phase 12 (0.10.0)")
        self.assertEqual((p.done, p.total), (2, 4))

    def test_version_falls_back_to_changelog_and_not_a_git_repo(self):
        plain = Path(self.tmp) / "simple"
        plain.mkdir()
        (plain / "ROADMAP.md").write_text("## P\n- [x] a\n- [ ] b\n")
        (plain / "CHANGELOG.md").write_text("# Journal\n\n## [Non publié]\n\n## [1.2.3] - 2026\n")
        (p,) = projects.list_projects([conv(plain, 7.0)])
        self.assertEqual((p.version, p.last_activity), ("1.2.3", 7.0))
        self.assertEqual(p.current_phase.title, "P")
        (plain / "CHANGELOG.md").unlink()
        (p,) = projects.list_projects([conv(plain)])
        self.assertIsNone(p.version)

    def test_all_finished_has_no_current_phase(self):
        self.commit("## P\n- [x] a\n", "2026-11-01")
        (p,) = projects.list_projects([conv(self.repo)])
        self.assertIsNone(p.current_phase)

    def test_hidden_projects_skipped(self):
        self.commit("## P\n- [ ] a\n", "2026-11-01")
        other = Path(self.tmp) / "autre"
        other.mkdir()
        (other / "ROADMAP.md").write_text("## P\n- [ ] a\n")
        sans = Path(self.tmp) / "sans"
        sans.mkdir()
        convs = [conv(self.repo, 1.0), conv(other, 9.0), conv(sans, 20.0),
                 conv(self.repo / "inexistant", 30.0), conv("", 40.0)]
        # `other` est hors git, activité 9 ; `depot` a un commit récent (bien > 9)
        names = [p.name for p in projects.list_projects(convs)]
        self.assertEqual(names, ["depot", "autre"])     # sans ROADMAP exclus
        self.assertEqual([p.name for p in projects.list_projects(convs, hidden=[str(other)])],
                         ["depot"])
        self.assertEqual([p.name for p in projects.list_projects(convs, hidden={self.repo})],
                         ["autre"])

    def test_subfolders_share_one_project(self):
        self.commit("## P\n- [ ] a\n", "2026-11-01")
        sub = self.repo / "src"
        sub.mkdir()
        ps = projects.list_projects([conv(self.repo, 5.0), conv(sub, 8.0)])
        self.assertEqual(len(ps), 1)
        self.assertEqual(ps[0].path, self.repo)

    def test_last_commit_counts_as_activity(self):
        self.commit("## P\n- [ ] a\n", "2026-11-01")
        (p,) = projects.list_projects([conv(self.repo, 5.0)])
        self.assertGreater(p.last_activity, 1.7e9)


if __name__ == "__main__":
    unittest.main()
