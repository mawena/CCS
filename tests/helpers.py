"""Outils de test : HOME isolé avec faux comptes, HTTP simulé."""

import json
import os
import shutil
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ACCOUNTS = {
    "perso": {"uuid": "uA", "org": "orgA", "email": "a@x.com", "plan": "pro"},
    "pro": {"uuid": "uB", "org": "orgB", "email": "b@y.com", "plan": "max"},
}


def oauth_for(name, expires_in_s=8 * 3600):
    return {
        "claudeAiOauth": {
            "accessToken": f"AT-{name}",
            "refreshToken": f"RT-{name}",
            "expiresAt": int((time.time() + expires_in_s) * 1000),
            "scopes": ["user:profile", "user:inference"],
            "subscriptionType": ACCOUNTS[name]["plan"],
        },
        "organizationUuid": ACCOUNTS[name]["org"],
    }


def account_for(name):
    a = ACCOUNTS[name]
    return {"accountUuid": a["uuid"], "organizationUuid": a["org"],
            "emailAddress": a["email"], "organizationName": f"Org {name}"}


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


def make_home(tmp, active="perso"):
    """HOME isolé : profils `perso` et `pro`, `active` connecté."""
    home = Path(tmp) / "home"
    store = home / ".claude-accounts"
    for name in ACCOUNTS:
        write(store / name / "oauth.json", oauth_for(name))
        write(store / name / "account.json", account_for(name))
    creds = oauth_for(active)
    creds["mcpOAuth"] = {"x": 1}
    write(home / ".claude" / ".credentials.json", creds)
    write(home / ".claude.json", {"numStartups": 1, "oauthAccount": account_for(active)})
    return home


@contextmanager
def fake_http(responses):
    """Patch de core.http_json : clé = sous-chaîne de l'URL, valeur = dict ou exception."""
    from ccs_app import core
    calls = []

    def handler(method, url, body=None, headers=None):
        calls.append((method, url, body, headers))
        for key, value in responses.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise core.UsageError(f"pas de réponse simulée pour {url}")

    with mock.patch.object(core, "http_json", side_effect=handler):
        yield calls


class HomeTestCase(unittest.TestCase):
    """Chaque test tourne dans un HOME temporaire avec deux profils."""

    active = "perso"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-test-")
        self.home = make_home(self.tmp, self.active)
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        self.env.start()
        for var in ("CLAUDE_CONFIG_DIR", "CCS_HOME"):
            os.environ.pop(var, None)
        running = mock.patch("ccs_app.core.claude_running", return_value=False)
        self.claude_running = running.start()
        self.addCleanup(running.stop)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    @property
    def store(self):
        return self.home / ".claude-accounts"
