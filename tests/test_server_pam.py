"""Comptes Ubuntu : groupe `ccs`, root refusé, PAM par ctypes (fausse libpam : jamais le vrai PAM)."""

import ctypes
import grp
import pwd
import unittest

from ccs_app.server import pam_auth


def pw(name, uid, gid=1000):
    return pwd.struct_passwd((name, "x", uid, gid, "", f"/home/{name}", "/bin/bash"))


USERS = {"alice": pw("alice", 1001), "bob": pw("bob", 1002), "root": pw("root", 0, 0),
         "toor": pw("toor", 0, 0)}


def getpwnam(name):
    if name not in USERS:
        raise KeyError(name)
    return USERS[name]


def getgrnam(name):
    if name != "ccs":
        raise KeyError(name)
    return grp.struct_group(("ccs", "x", 990, ["alice", "root", "toor"]))


def getgrouplist(user, gid):
    return [gid, 990] if user in ("alice", "root", "toor") else [gid]


def allowed(user, **kw):
    return pam_auth.allowed(user, getpwnam=getpwnam, getgrnam=getgrnam, getgrouplist=getgrouplist, **kw)


class FakePam:
    """Imite libpam : pam_authenticate appelle la conversation avec une invite masquée."""

    def __init__(self, expected="secret", acct=0, prompts=((1, b"Password: "),), crash=False):
        self.expected, self.acct, self.prompts, self.crash = expected, acct, prompts, crash
        self.calls = []
        self.answers = []

    def pam_start(self, service, user, conv_ref, handle_ref):
        self.calls.append(("start", service, user))
        self.conv = conv_ref._obj
        return 0

    def pam_authenticate(self, handle, flags):
        if self.crash:
            raise OSError("libpam absente")
        n = len(self.prompts)
        msgs = [pam_auth.PamMessage(style, text) for style, text in self.prompts]
        arr = (ctypes.POINTER(pam_auth.PamMessage) * n)(*[ctypes.pointer(m) for m in msgs])
        resp = ctypes.POINTER(pam_auth.PamResponse)()
        rc = self.conv.conv(n, arr, ctypes.byref(resp), None)
        if rc != 0:
            return rc
        self.answers = [ctypes.string_at(resp[i].resp).decode() if resp[i].resp else None for i in range(n)]
        return 0 if self.expected in self.answers else 7

    def pam_acct_mgmt(self, handle, flags):
        self.calls.append(("acct",))
        return self.acct

    def pam_end(self, handle, status):
        self.calls.append(("end", status))
        return 0


class AllowedTest(unittest.TestCase):
    def test_allowed_refuses_root_and_uid0(self):
        self.assertFalse(allowed("root"))
        self.assertFalse(allowed("toor"))           # uid 0 sous un autre nom

    def test_allowed_requires_group(self):
        self.assertTrue(allowed("alice"))
        self.assertFalse(allowed("bob"))

    def test_allowed_unknown_user(self):
        self.assertFalse(allowed("personne"))
        self.assertFalse(allowed("../etc"))

    def test_allowed_missing_group(self):
        def nogroup(name):
            raise KeyError(name)
        self.assertFalse(pam_auth.allowed("alice", getpwnam=getpwnam, getgrnam=nogroup,
                                          getgrouplist=getgrouplist))


class AuthenticateTest(unittest.TestCase):
    def test_authenticate_with_fake_lib_success(self):
        lib = FakePam()
        self.assertTrue(pam_auth.authenticate("alice", "secret", lib=lib))
        self.assertEqual(lib.calls[0], ("start", b"ccs", b"alice"))
        self.assertIn(("acct",), lib.calls)
        self.assertEqual(lib.calls[-1][0], "end")

    def test_username_prompt_gets_user(self):
        lib = FakePam(prompts=((2, b"login: "), (1, b"Password: "), (4, b"info")))
        self.assertTrue(pam_auth.authenticate("alice", "secret", lib=lib))
        self.assertEqual(lib.answers, ["alice", "secret", None])

    def test_authenticate_fake_lib_failure(self):
        self.assertFalse(pam_auth.authenticate("alice", "faux", lib=FakePam()))

    def test_account_refused(self):
        self.assertFalse(pam_auth.authenticate("alice", "secret", lib=FakePam(acct=13)))

    def test_authenticate_exception_is_false(self):
        self.assertFalse(pam_auth.authenticate("alice", "secret", lib=FakePam(crash=True)))

    def test_empty_or_odd_input(self):
        self.assertFalse(pam_auth.authenticate("", "secret", lib=FakePam()))
        self.assertFalse(pam_auth.authenticate("alice", "", lib=FakePam(expected="")))
        self.assertFalse(pam_auth.authenticate("alice", "a\0b", lib=FakePam()))


if __name__ == "__main__":
    unittest.main()
