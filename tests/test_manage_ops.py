"""Gestion des projets et de la corbeille au bureau : sur « Ce poste », les mêmes opérations
(et les mêmes contrôles) que celles du pont d'un serveur."""

import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from ccs_app import project_list, sessions
from ccs_app.remote import manage
from tests.helpers import make_home


def call(ops, method, **params):
    done, box = threading.Event(), {}

    def cb(result, error):
        box["r"], box["e"] = result, error
        done.set()
    ops.call(method, cb, **params)
    assert done.wait(10)
    return box["r"], box["e"]


class LocalOpsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-manage-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = make_home(self.tmp)
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.ops = manage.LocalOps(dispatch=lambda fn, *a: fn(*a))

    def test_add_new_folder_with_git_and_remove(self):
        (self.home / "Work").mkdir()
        r, e = call(self.ops, "projects.add", parent="~/Work", name="neuf", git=True)
        self.assertIsNone(e)
        self.assertTrue((self.home / "Work" / "neuf" / ".git").is_dir())
        self.assertIn(r["cwd"], project_list.load()[0])
        r, e = call(self.ops, "projects.remove", cwd=r["cwd"])
        self.assertIsNone(e)
        self.assertIn(r["cwd"], project_list.load()[1])

    def test_refused_outside_allowed_folders(self):
        _r, e = call(self.ops, "projects.add", cwd="/etc")
        self.assertIsNotNone(e)
        self.assertTrue(e.message)

    def test_trash_and_restore(self):
        project = self.home / "projet"
        project.mkdir()
        sid = "0f0e0d0c-aaaa-bbbb-cccc-000000000009"
        j = sessions.transcript_path(str(project), sid)
        j.parent.mkdir(parents=True)
        j.write_text('{"type":"user"}\n')
        with mock.patch.object(sessions, "list_sessions", return_value=[]):
            r, e = call(self.ops, "conversation.trash", path=str(j), session_id=sid, cwd=str(project), title="T")
        self.assertIsNone(e)
        self.assertFalse(j.exists())
        items, _e = call(self.ops, "conversation.trash_list")
        self.assertEqual([i["title"] for i in items["items"]], ["T"])
        _r, e = call(self.ops, "conversation.restore", tid=r["tid"])
        self.assertIsNone(e)
        self.assertTrue(j.exists())

    def test_unknown_method_refused(self):
        _r, e = call(self.ops, "files.write", path="/tmp/x", text="")
        self.assertIsNotNone(e)


if __name__ == "__main__":
    unittest.main()
