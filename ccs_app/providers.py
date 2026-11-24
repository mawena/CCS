"""Fournisseurs de modèles : faire tourner Claude Code sur un autre service que Claude.

Claude Code sait parler à tout serveur qui imite l'API Anthropic (OpenRouter, Ollama,
LiteLLM…). Un fournisseur se résume donc à des arguments de `claude` :

  --settings '<json>'   réglages de la session : adresse du service (ANTHROPIC_BASE_URL),
                        modèle derrière chaque alias (opus, sonnet, haiku, sous-agents) et
                        `apiKeyHelper`, la commande qui lit la clé dans son fichier ;
  --model <modèle>      modèle choisi chez le fournisseur.

La clé n'est jamais dans la ligne de commande ni dans l'environnement de CCS : claude la lit
lui-même dans le fichier (droits 600). Ces arguments passent partout où passent déjà les
autres (`extra_args` des onglets, relance, sauvegarde des onglets, tâches, chats).

Fournisseurs connus : `PRESETS` (OpenRouter, DeepSeek), complétés ou remplacés par
`~/.config/ccs/providers.json` :

  {"ollama": {"label": "Ollama", "base_url": "http://100.64.0.5:11434", "key_file": null,
              "models": [["Qwen3 Coder 30B", "qwen3-coder:30b"]]}}

`key_file` null : service sans clé (Ollama local).

`"api": "openai"` : service qui ne parle que l'API OpenAI (Venice…). `base_url` est alors
l'adresse OpenAI (…/v1) ; claude passe par le proxy local de CCS (openai_proxy.py), lancé à la
demande et arrêté avec la dernière session. `extra_body` : champs ajoutés à chaque requête.
"""

import json
import os
import re
import shlex
import stat
import sys
from dataclasses import dataclass, field

from . import core

# Le nom « claude » (et ses synonymes) veut dire : pas de fournisseur, Claude comme d'habitude.
CLAUDE_WORDS = {"claude", "anthropic", "default", "défaut", "par défaut", "aucun", "none"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MARK = "CCS_PROVIDER"   # variable posée dans les réglages : retrouve le fournisseur d'un onglet

# Préréglages vérifiés le 24/11/2026 (catalogue OpenRouter, docs DeepSeek) : modèles avec appel
# d'outils, indispensable à Claude Code. Prix indicatifs en $ par million de jetons (entrée/sortie).
PRESETS = {
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api",
        "key_file": "~/.config/openrouter/cle",
        "models_url": "https://openrouter.ai/api/v1/models",
        "default_model": "deepseek/deepseek-v4.1-flash-1017:floor",
        "models": [
            # « :floor » : OpenRouter choisit l'hébergeur le moins cher (~0,03-0,05/0,10-0,50 $, cache)
            ["DeepSeek V4.1 Flash (défaut, le moins cher)", "deepseek/deepseek-v4.1-flash-1017:floor"],
            ["GLM 5.3 (peu filtré)", "z-ai/glm-5.3"],
            ["Grok 4.7 (le plus puissant, 2/6 $)", "x-ai/grok-4.7"],
            ["DeepSeek V4.1 Flash 1017", "deepseek/deepseek-v4.1-flash-1017"],
            ["DeepSeek V4.1 Flash", "deepseek/deepseek-v4.1-flash"],
            ["DeepSeek V4 Pro", "deepseek/deepseek-v4-pro-0813"],
            ["Kimi K3.1 Pro", "moonshotai/kimi-k3.1-pro"],
            ["Qwen3 Coder Next", "qwen/qwen3-coder-next"],
            ["GLM 5.3 Flash", "z-ai/glm-5.3-flash"],
            ["GLM 4.6", "z-ai/glm-4.6"],
            ["Qwen3 Coder", "qwen/qwen3-coder"],
            ["Nemotron 3 Ultra (gratuit)", "nvidia/nemotron-3-ultra-550b-a55b:free"],
        ],
    },
    # API directe, compatible Anthropic : la moins chère pour DeepSeek (heures creuses -50 %).
    # `claude-opus*` part sur V4 Pro, le reste sur Flash ; ici le modèle est donné explicitement.
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/anthropic",
        "key_file": "~/.config/deepseek/cle",
        "default_model": "deepseek-flash",
        "models": [
            ["DeepSeek V4.1 Flash (0,30/1,20 $)", "deepseek-flash"],
            ["DeepSeek V4 Pro (1,32/3,96 $)", "deepseek-v4-pro"],
        ],
    },
    # API seulement compatible OpenAI : par le proxy local (openai_proxy.py). Modèles peu filtrés
    # avec appel d'outils ; sans l'invite système de Venice, qui gênerait celle de Claude Code.
    "venice": {
        "label": "Venice",
        "api": "openai",
        "base_url": "https://api.venice.ai/api/v1",
        "key_file": "~/.config/venice/cle",
        "default_model": "deepseek-v4-1-flash-1017-uncensored",
        "extra_body": {"venice_parameters": {"include_venice_system_prompt": False}},
        "models": [
            ["DeepSeek V4.1 Flash 1017 Uncensored (défaut)", "deepseek-v4-1-flash-1017-uncensored"],
            ["Qwen 3.6 Plus Uncensored", "qwen-3-6-plus"],
            ["GLM 5.3 Flash Uncensored", "glm-5-3-flash-uncensored"],
            ["Venice Uncensored 1.2", "venice-uncensored"],
        ],
    },
}
APIS = ("anthropic", "openai")


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    base_url: str
    key_file: str | None = None
    default_model: str | None = None
    models: tuple = field(default_factory=tuple)   # (libellé, identifiant)
    models_url: str | None = None
    api: str = "anthropic"            # « openai » : par le proxy local
    extra_body: dict | None = field(default=None, hash=False, compare=False)

    def claude_url(self):
        """Adresse donnée à claude : le service lui-même, ou le proxy local pour OpenAI."""
        if self.api == "openai":
            from . import openai_proxy
            return openai_proxy.url_for(self.name)
        return self.base_url

    def key_path(self):
        return os.path.expanduser(self.key_file) if self.key_file else None


def config_path():
    return core.ccs_dir("config") / "providers.json"


def _user_config():
    try:
        with open(config_path(), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise ValueError(f"{config_path()} illisible : {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{config_path()} : un objet JSON est attendu")
    return data


def _build(name, raw):
    if not NAME_RE.match(name):
        raise ValueError(f"nom de fournisseur invalide : {name!r} (minuscules, chiffres, - et _)")
    if not isinstance(raw, dict) or not str(raw.get("base_url") or "").startswith(("http://", "https://")):
        raise ValueError(f"fournisseur « {name} » : base_url (http:// ou https://) manquante")
    models = []
    for item in raw.get("models") or ():
        if isinstance(item, str):
            item = [item, item]
        if isinstance(item, (list, tuple)) and len(item) == 2 and all(isinstance(x, str) for x in item):
            models.append((item[0], item[1]))
    default = raw.get("default_model") or (models[0][1] if models else None)
    api = str(raw.get("api") or "anthropic").casefold()
    if api not in APIS:
        raise ValueError(f"fournisseur « {name} » : api inconnue {api!r} ({', '.join(APIS)})")
    extra = raw.get("extra_body") if isinstance(raw.get("extra_body"), dict) else None
    return Provider(name, str(raw.get("label") or name), str(raw["base_url"]).rstrip("/"),
                    raw.get("key_file"), default, tuple(models), raw.get("models_url"), api, extra)


def load():
    """Fournisseurs connus, par nom (préréglages complétés par le fichier de l'utilisateur)."""
    merged = {k: dict(v) for k, v in PRESETS.items()}
    for name, raw in _user_config().items():
        if isinstance(raw, dict):
            merged[name] = {**merged.get(name, {}), **raw}
    return {name: _build(name, raw) for name, raw in merged.items()}


def is_claude(name):
    return name is None or str(name).strip().casefold() in CLAUDE_WORDS


def normalize(name):
    """Nom de fournisseur validé ; None pour Claude. ValueError si inconnu."""
    if is_claude(name):
        return None
    name = str(name).strip().casefold()
    known = load()
    if name not in known:
        raise ValueError(f"fournisseur inconnu : {name!r} (connus : claude, {', '.join(sorted(known))})")
    return name


def get(name):
    return load()[normalize(name)]


def key_problem(provider):
    """Ce qui empêche d'utiliser la clé (texte), ou None si tout va bien."""
    path = provider.key_path()
    if not path:
        return None
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return f"clé absente : « ccs provider key {provider.name} » pour l'enregistrer ({path})"
    except OSError as e:
        return f"clé illisible ({path}) : {e}"
    if st.st_size == 0:
        return f"clé vide : {path}"
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        return f"clé lisible par d'autres : chmod 600 {path}"
    return None


def settings(provider, model=None):
    """Réglages de `claude --settings` pour ce fournisseur (dict)."""
    model = model or provider.default_model
    env = {MARK: provider.name, "ANTHROPIC_BASE_URL": provider.claude_url(),
           # une clé Anthropic de l'environnement passerait avant celle du fournisseur
           "ANTHROPIC_API_KEY": ""}
    if model:
        for var in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"):
            env[var] = model
    out = {"env": env}
    path = provider.key_path()
    if path:
        out["apiKeyHelper"] = "cat " + shlex.quote(path)
    else:
        env["ANTHROPIC_AUTH_TOKEN"] = "aucune"   # le service n'en veut pas, claude en exige une
    return out


def claude_args(name, model=None, check=True):
    """Arguments de `claude` pour le fournisseur `name` ([] pour Claude). `check` : refuse
    (ValueError) une clé absente ou mal protégée, pour échouer avant de lancer claude."""
    name = normalize(name)
    if name is None:
        return []
    provider = load()[name]
    if check:
        problem = key_problem(provider)
        if problem:
            raise ValueError(f"{provider.label} : {problem}")
        if provider.api == "openai":
            # le proxy part maintenant ; il s'arrêtera seul après la dernière session
            from . import openai_proxy
            openai_proxy.ensure_running()
    model = model or provider.default_model
    args = ["--settings", json.dumps(settings(provider, model), ensure_ascii=False, separators=(",", ":"))]
    if model:
        args += ["--model", model]
    return args


def from_args(args):
    """(fournisseur, modèle) d'une ligne d'arguments de claude ; (None, None) pour Claude."""
    args = [a for a in (args or ()) if isinstance(a, str)]
    name = model = None
    for i, a in enumerate(args):
        value = None
        if a == "--settings" and i + 1 < len(args):
            value = args[i + 1]
        elif a.startswith("--settings="):
            value = a.split("=", 1)[1]
        if value and value.lstrip().startswith("{"):
            try:
                name = (json.loads(value).get("env") or {}).get(MARK) or name
            except (ValueError, AttributeError):
                pass
        if a == "--model" and i + 1 < len(args):
            model = args[i + 1]
        elif a.startswith("--model="):
            model = a.split("=", 1)[1]
    return (name, model) if name else (None, None)


def strip_args(args):
    """Les arguments sans ceux d'un fournisseur (--settings de CCS et --model qui va avec)."""
    args = list(args or ())
    name, _model = from_args(args)
    if not name:
        return args
    out, skip = [], False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a in ("--settings", "--model") and i + 1 < len(args):
            skip = True
            continue
        if a.startswith(("--settings=", "--model=")):
            continue
        out.append(a)
    return out


def short_model(model):
    return (model or "").rsplit("/", 1)[-1].removesuffix(":free")


def label_for_args(args):
    """« OpenRouter · glm-5.3 » pour un onglet lancé chez un fournisseur, sinon None."""
    name, model = from_args(args)
    if not name:
        return None
    try:
        label = load()[name].label
    except (KeyError, ValueError):
        label = name
    return f"{label} · {short_model(model)}" if model else label


def choices():
    """[(nom, libellé, [(libellé, modèle)…])] : Claude d'abord, puis les fournisseurs connus.
    Pour les menus (bureau, web)."""
    out = [("claude", "Claude", [])]
    try:
        known = load()
    except ValueError:
        known = {}
    for name in sorted(known):
        p = known[name]
        out.append((name, p.label, list(p.models)))
    return out


# --------------------------------------------------------------------------
# Commande « ccs provider »
# --------------------------------------------------------------------------

USAGE = """usage : ccs provider [list | show <nom> | models <nom> [mots…] | key <nom> | test <nom> [modèle] | proxy [stop]]

  list                 fournisseurs connus, adresse, état de la clé (défaut)
  show <nom>           détail et modèles proposés
  models <nom> [mots]  modèles disponibles en ce moment chez le fournisseur (filtre par mots ;
                       « free » pour les gratuits)
  key <nom>            enregistre la clé (lue sans écho, ou sur l'entrée standard), droits 600
  test <nom> [modèle]  envoie « ok » au modèle par claude et affiche la réponse
  proxy [stop]         état du proxy local des services OpenAI (Venice…), ou arrêt

Ajouter un fournisseur : {path}
Utiliser : ccs task add "…" --provider openrouter [--model <modèle>] ; dans l'appli et sur le
web, choisir le fournisseur dans les options de la session ou du chat."""


def _list(out):
    for name, p in sorted(load().items()):
        problem = key_problem(p)
        state = "clé prête" if not problem else problem
        via = " (OpenAI, par le proxy local)" if p.api == "openai" else ""
        print(f"{name:<12} {p.label:<14} {p.base_url}{via}", file=out)
        print(f"{'':<12} modèle par défaut : {p.default_model or '—'} ; {state}", file=out)
    return 0


def _show(name, out):
    p = get(name)
    via = f" (API OpenAI, par le proxy {p.claude_url()})" if p.api == "openai" else ""
    print(f"{p.label} ({p.name})\n  adresse : {p.base_url}{via}\n  clé : {p.key_path() or 'aucune'}"
          f" — {key_problem(p) or 'prête'}\n  modèle par défaut : {p.default_model or '—'}", file=out)
    for label, model in p.models:
        print(f"  • {label:<44} {model}", file=out)
    return 0


def fetch_models(provider, timeout=15):
    """Modèles annoncés par le fournisseur ([(identifiant, nom, prix entrée $/M)]), si son
    catalogue est public (`models_url`). Sinon ceux de la configuration."""
    if not provider.models_url:
        return [(m, label, None) for label, m in provider.models]
    import urllib.request
    req = urllib.request.Request(provider.models_url, headers={"User-Agent": "ccs"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r).get("data") or []
    out = []
    for m in data:
        try:
            price = float((m.get("pricing") or {}).get("prompt") or 0) * 1e6
        except (TypeError, ValueError):
            price = None
        out.append((m.get("id"), m.get("name") or m.get("id"), price))
    return [m for m in out if m[0]]


def _models(name, words, out):
    p = get(name)
    try:
        found = fetch_models(p)
    except OSError as e:
        print(f"catalogue de {p.label} injoignable : {e}", file=sys.stderr)
        return 1
    words = [w.casefold() for w in words]
    found = [m for m in found if all(w in f"{m[0]} {m[1]}".casefold() for w in words)]
    for model, label, price in sorted(found):
        cost = "" if price is None else ("gratuit" if price == 0 else f"{price:.2f} $/M")
        print(f"{model:<60} {cost:>10}  {label}", file=out)
    print(f"{len(found)} modèle(s)", file=out)
    return 0


def save_key(name, text):
    """Écrit la clé du fournisseur (droits 600, dossier 700). Renvoie le chemin."""
    p = get(name)
    path = p.key_path()
    if not path:
        raise ValueError(f"{p.label} n'utilise pas de clé")
    text = (text or "").strip()
    if not text or "\n" in text:
        raise ValueError("clé vide ou sur plusieurs lignes")
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text + "\n")
    os.chmod(path, 0o600)
    return path


def _key(name, out):
    if sys.stdin.isatty():
        import getpass
        text = getpass.getpass(f"Clé {get(name).label} : ")
    else:
        text = sys.stdin.readline()
    print(f"clé enregistrée : {save_key(name, text)}", file=out)
    return 0


def _test(name, model, out):
    import subprocess

    from . import sessions
    args = claude_args(name, model)
    # claude réserve 32 000 jetons de sortie par défaut : une clé plafonnée (ou peu de crédit)
    # serait refusée (402) alors que l'essai n'en coûte que quelques-uns
    env = {**os.environ, "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "256"}
    r = subprocess.run([sessions._claude_bin(), "-p", "Réponds seulement : ok", *args],
                       capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL, env=env)
    text = (r.stdout or "").strip() or (r.stderr or "").strip()
    print(text[-2000:], file=out)
    return r.returncode


def command(argv, out=None):
    out = out or sys.stdout
    argv = list(argv)
    action = argv.pop(0) if argv else "list"
    try:
        if action in ("list", "liste", "ls"):
            return _list(out)
        if action == "proxy":
            from . import openai_proxy
            return openai_proxy.main(["stop" if argv[:1] == ["stop"] else "status"])
        if action in ("help", "aide", "-h", "--help"):
            print(USAGE.format(path=config_path()), file=out)
            return 0
        if not argv:
            raise ValueError(f"« {action} » attend le nom du fournisseur")
        name = argv.pop(0)
        if action in ("show", "voir"):
            return _show(name, out)
        if action in ("models", "modeles", "modèles"):
            return _models(name, argv, out)
        if action in ("key", "cle", "clé"):
            return _key(name, out)
        if action in ("test", "essai"):
            return _test(name, argv[0] if argv else None, out)
        raise ValueError(f"action inconnue : {action}")
    except ValueError as e:
        print(f"ccs provider : {e}", file=sys.stderr)
        if action not in ("list", "show", "models", "key", "test"):
            print(USAGE.format(path=config_path()), file=sys.stderr)
        return 2
