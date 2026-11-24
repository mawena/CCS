import io
import json
import os
import stat

from ccs_app import chat_options, launch_options, providers, task_runner, tasks, terminal
from ccs_app.launch_options import LaunchSpec
from tests.helpers import HomeTestCase


class ProvidersTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.key = self.home / ".config" / "openrouter" / "cle"

    def with_key(self):
        providers.save_key("openrouter", "sk-or-essai")

    def settings_of(self, args):
        return json.loads(args[args.index("--settings") + 1])

    # ---- configuration -----------------------------------------------------------------

    def test_presets_and_user_config(self):
        cfg = providers.config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({
            "ollama": {"label": "Ollama", "base_url": "http://100.64.0.5:11434/", "key_file": None,
                       "models": [["Qwen", "qwen3-coder:30b"], "autre"]},
            "openrouter": {"default_model": "x/y"}}))
        known = providers.load()
        self.assertEqual(known["ollama"].base_url, "http://100.64.0.5:11434")
        self.assertEqual(known["ollama"].models, (("Qwen", "qwen3-coder:30b"), ("autre", "autre")))
        self.assertEqual(known["ollama"].default_model, "qwen3-coder:30b")
        self.assertEqual(known["openrouter"].default_model, "x/y")
        self.assertEqual(known["openrouter"].base_url, "https://openrouter.ai/api")

    def test_presets_default_first_and_deepseek_direct(self):
        """Le modèle par défaut est le premier proposé (menus) ; DeepSeek direct, compatible Anthropic."""
        for name in providers.PRESETS:
            p = providers.get(name)
            self.assertEqual(p.models[0][1], p.default_model, name)
        ds = providers.get("deepseek")
        self.assertEqual(ds.base_url, "https://api.deepseek.com/anthropic")
        self.assertTrue(ds.key_path().endswith("/.config/deepseek/cle"))

    def test_bad_config_is_reported(self):
        cfg = providers.config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"rien": {"base_url": "ftp://x"}}))
        with self.assertRaises(ValueError):
            providers.load()

    def test_claude_words_mean_no_provider(self):
        for word in (None, "claude", "Claude", "défaut", "aucun"):
            self.assertIsNone(providers.normalize(word))
            self.assertEqual(providers.claude_args(word), [])
        with self.assertRaises(ValueError):
            providers.normalize("inconnu")

    # ---- clé -------------------------------------------------------------------------------

    def test_key_problems(self):
        p = providers.get("openrouter")
        self.assertIn("absente", providers.key_problem(p))
        with self.assertRaises(ValueError):
            providers.claude_args("openrouter")
        self.with_key()
        self.assertIsNone(providers.key_problem(p))
        self.assertEqual(stat.S_IMODE(os.stat(self.key).st_mode), 0o600)
        self.assertEqual(self.key.read_text(), "sk-or-essai\n")
        os.chmod(self.key, 0o644)
        self.assertIn("chmod 600", providers.key_problem(p))

    def test_save_key_refuses_empty(self):
        for bad in ("", "  ", "a\nb"):
            with self.assertRaises(ValueError):
                providers.save_key("openrouter", bad)

    # ---- arguments de claude -------------------------------------------------------------

    def test_args_carry_url_models_and_key_command_not_key(self):
        self.with_key()
        args = providers.claude_args("openrouter", "z-ai/glm-5.3")
        self.assertEqual(args[-2:], ["--model", "z-ai/glm-5.3"])
        s = self.settings_of(args)
        self.assertEqual(s["env"]["ANTHROPIC_BASE_URL"], "https://openrouter.ai/api")
        self.assertEqual(s["env"]["ANTHROPIC_API_KEY"], "")
        for var in ("ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL", "ANTHROPIC_MODEL"):
            self.assertEqual(s["env"][var], "z-ai/glm-5.3")
        self.assertIn(str(self.key), s["apiKeyHelper"])
        self.assertNotIn("sk-or-essai", " ".join(args))

    def test_default_model_used(self):
        self.with_key()
        args = providers.claude_args("openrouter")
        self.assertEqual(args[-1], providers.get("openrouter").default_model)

    def test_keyless_provider(self):
        cfg = providers.config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"ollama": {"base_url": "http://localhost:11434", "models": ["q"]}}))
        s = self.settings_of(providers.claude_args("ollama"))
        self.assertNotIn("apiKeyHelper", s)
        self.assertTrue(s["env"]["ANTHROPIC_AUTH_TOKEN"])

    def test_from_args_label_and_strip(self):
        self.with_key()
        args = ["--permission-mode", "plan", *providers.claude_args("openrouter", "a/b-c:free")]
        self.assertEqual(providers.from_args(args), ("openrouter", "a/b-c:free"))
        self.assertEqual(providers.label_for_args(args), "OpenRouter · b-c")
        self.assertEqual(providers.strip_args(args), ["--permission-mode", "plan"])
        self.assertEqual(providers.from_args(["--model", "opus"]), (None, None))
        self.assertIsNone(providers.label_for_args(["--model", "opus"]))

    # ---- branchements --------------------------------------------------------------------

    def test_launch_spec_and_tab_title(self):
        self.with_key()
        spec = LaunchSpec(cwd=str(self.home), profile=None, model="a/b", permission_mode="plan",
                          provider="OpenRouter")
        self.assertEqual(spec.provider, "openrouter")
        args = spec.args()
        self.assertIn("--settings", args)
        self.assertEqual(args.count("--model"), 1)
        launch = terminal.claude_launch(str(self.home), title="Projet", extra_args=args)
        self.assertEqual(launch.title, "Projet · OpenRouter · b")
        again = terminal.claude_launch(str(self.home), title=launch.title, extra_args=args)
        self.assertEqual(again.title, launch.title)
        self.assertEqual(launch_options.claude_args(model="opus"), ["--model", "opus"])

    def test_chat_options(self):
        self.with_key()
        o = chat_options.ChatOptions(model="a/b", effort="high", rights="plan", provider="openrouter")
        args = chat_options.launch_args(o)
        self.assertIn("--settings", args)
        self.assertNotIn("--effort", args)
        back = chat_options.from_args(args)
        self.assertEqual((back.provider, back.model, back.rights), ("openrouter", "a/b", "plan"))
        self.assertIsNone(chat_options.ChatOptions(provider="claude").provider)

    def test_task_with_provider(self):
        self.with_key()
        parsed = tasks.parse_add(["fais ça", "--provider", "openrouter", "--model", "a/b"])
        self.assertEqual(parsed["provider"], "openrouter")
        t = tasks.add(**{**parsed, "cwd": str(self.home)})
        self.assertEqual(tasks.get(t.id).provider, "openrouter")
        argv = task_runner.claude_argv(tasks.get(t.id))
        self.assertIn("--settings", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "a/b")
        ok, _msg = task_runner.prepare(tasks.get(t.id), {}, {}, None)
        self.assertTrue(ok)

    def test_task_refused_without_key(self):
        with self.assertRaises(ValueError):
            tasks.add("x", cwd=str(self.home), provider="openrouter")

    def test_command_list_and_show(self):
        out = io.StringIO()
        self.assertEqual(providers.command(["list"], out), 0)
        self.assertIn("openrouter", out.getvalue())
        out = io.StringIO()
        self.assertEqual(providers.command(["show", "openrouter"], out), 0)
        self.assertIn("openrouter.ai", out.getvalue())
        self.assertEqual(providers.command(["show", "inconnu"], io.StringIO()), 2)
