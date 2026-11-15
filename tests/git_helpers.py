"""Aides des tests git : dépôts temporaires, identité locale, jamais la config de Charles."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

IDENT = ["-c", "user.name=Test", "-c", "user.email=test@example.org",
         "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]


def g(repo, *args):
    """git de test (identité locale, aucune config de Charles)."""
    return subprocess.run(["git", *IDENT, "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def commit_file(repo, name, text, msg=None):
    path = Path(repo) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    g(repo, "add", "--", name)
    g(repo, "commit", "-q", "-m", msg or f"ajoute {name}")
    return g(repo, "rev-parse", "HEAD").strip()


class GitTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-git-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {k: os.environ.get(k) for k in ("HOME", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")}
        os.environ["HOME"] = self.tmp
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        cfg = Path(self.tmp) / "gitconfig"
        cfg.write_text("[user]\n\tname = Test\n\temail = test@example.org\n"
                       "[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n")
        os.environ["GIT_CONFIG_GLOBAL"] = str(cfg)
        self.addCleanup(self._restore_env)
        self.repo = Path(self.tmp) / "depot"
        self.repo.mkdir()
        g(self.repo, "init", "-q")

    def _restore_env(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def remote(self):
        """Distant nu local (file://), branche main poussée."""
        bare = Path(self.tmp) / "distant.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        g(self.repo, "remote", "add", "origin", bare.as_uri())
        return bare


def many_commits(repo, n, branch="main"):
    """n commits linéaires créés d'un coup par `git fast-import` (rapide même pour 1000)."""
    lines, mark = [], 0
    for i in range(n):
        mark += 1
        msg = f"commit {i}".encode()
        lines.append(f"commit refs/heads/{branch}\nmark :{mark}\n"
                     f"committer Test <test@example.org> {1_700_000_000 + i} +0000\n"
                     f"data {len(msg)}\n".encode() + msg + b"\n")
        if i:
            lines.append(f"from :{mark - 1}\n".encode())
        lines.append(f"M 644 inline f.txt\ndata {len(str(i))}\n{i}\n\n".encode())
    subprocess.run(["git", "-C", str(repo), "fast-import", "--quiet"], input=b"".join(lines),
                   check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-f", branch], check=True)
