"""Onglet Réglages : bascule automatique, alertes, warm-up, service."""

import re
import subprocess

from gi.repository import Adw, Gtk

from .. import core, daemon
from ..settings import load_settings, save_settings

DAY_LABELS = ["L", "M", "M", "J", "V", "S", "D"]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SERVICE = "ccs-daemon.service"


def systemctl(*args):
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


class PrefsPage(Adw.PreferencesPage):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.s = load_settings()
        self.groups = []

    def save(self):
        save_settings(self.s)
        daemon.request_refresh()
        self.window.sync_auto_switch(self.s["auto_switch"]["enabled"])

    def render(self):
        for g in self.groups:
            self.remove(g)
        self.groups = []
        self.s = load_settings()
        self.add_group(self.auto_group())
        self.add_group(self.orchestrator_group())
        self.add_group(self.alerts_group())
        self.add_group(self.integration_group())
        self.add_group(self.warmup_group())
        self.add_group(self.service_group())

    def add_group(self, g):
        self.groups.append(g)
        self.add(g)

    # ---- lignes génériques ------------------------------------------------------

    def switch_row(self, title, subtitle, section, key):
        row = Adw.SwitchRow(title=title, subtitle=subtitle, active=self.s[section][key])

        def changed(r, _p):
            self.s[section][key] = r.get_active()
            self.save()
        row.connect("notify::active", changed)
        return row

    def spin_row(self, title, subtitle, section, key, lo, hi, step=1):
        row = Adw.SpinRow.new_with_range(lo, hi, step)
        row.set_title(title)
        row.set_subtitle(subtitle)
        row.set_value(self.s[section][key])

        def changed(r, _p):
            self.s[section][key] = int(r.get_value())
            self.save()
        row.connect("notify::value", changed)
        return row

    # ---- groupes -----------------------------------------------------------------

    def auto_group(self):
        g = Adw.PreferencesGroup(
            title="Bascule automatique",
            description="Change de compte avant la coupure ; les sessions ouvertes suivent "
                        "à leur prochaine requête.")
        g.add(self.switch_row("Activer", "Recommandé", "auto_switch", "enabled"))
        g.add(self.spin_row("Seuil de bascule (%)", "Session ou semaine du compte actif",
                            "auto_switch", "threshold", 80, 100))
        g.add(self.spin_row("Session max du compte cible (%)", "Ne bascule que vers un compte en dessous",
                            "auto_switch", "target_max_session", 30, 95, 5))
        return g

    def orchestrator_group(self):
        o = self.s["orchestrator"]
        g = Adw.PreferencesGroup(
            title="Orchestrateur",
            description="Enchaîne les fenêtres de 5 h de chaque compte pendant la plage horaire, "
                        "les décale entre comptes et bascule vers le quota qui va expirer.")
        g.add(self.switch_row("Activer", "Démarre les fenêtres par une requête minimale (Haiku)",
                              "orchestrator", "enabled"))
        hours = Adw.ActionRow(title="Plage horaire", subtitle="Aucun démarrage en dehors")
        box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        entries = {}
        for key in ("start", "end"):
            e = Gtk.Entry(text=o["active_hours"][key], width_chars=5, max_width_chars=5)
            entries[key] = e
            box.append(e)
            if key == "start":
                box.append(Gtk.Label(label="→"))

        def apply_hours(*_):
            vals = {k: e.get_text().strip() for k, e in entries.items()}
            bad = False
            for k, e in entries.items():
                if TIME_RE.match(vals[k]):
                    e.remove_css_class("error")
                else:
                    e.add_css_class("error")
                    bad = True
            if not bad:
                o["active_hours"].update(vals)
                self.save()
        for e in entries.values():
            e.connect("changed", apply_hours)
        hours.add_suffix(box)
        g.add(hours)
        days_row = Adw.ActionRow(title="Jours actifs")
        days_box = Gtk.Box(css_classes=["linked"], valign=Gtk.Align.CENTER)
        toggles = []
        for i, lbl in enumerate(DAY_LABELS):
            t = Gtk.ToggleButton(label=lbl, active=i in o["active_hours"]["days"])
            toggles.append(t)
            days_box.append(t)

        def apply_days(*_):
            o["active_hours"]["days"] = [i for i, t in enumerate(toggles) if t.get_active()]
            self.save()
        for t in toggles:
            t.connect("toggled", apply_days)
        days_row.add_suffix(days_box)
        g.add(days_row)
        g.add(self.switch_row("Décaler les comptes", "Une recharge toutes les 5 h ÷ nombre de comptes",
                              "orchestrator", "stagger"))
        g.add(self.switch_row("Utiliser d'abord le quota qui expire",
                              "Bascule anticipée vers un compte qui va perdre son quota",
                              "orchestrator", "expiring_switch"))
        g.add(self.spin_row("Fin de fenêtre dans moins de (min)", "Pour la bascule anticipée",
                            "orchestrator", "expiring_within_min", 15, 120, 5))
        g.add(self.spin_row("Quota restant d'au moins (%)", "Pour la bascule anticipée",
                            "orchestrator", "expiring_min_left", 10, 90, 5))
        g.add(self.spin_row("Réserve : avance hebdo de plus de (pts)",
                            "Un compte en avance sur sa semaine sert en dernier",
                            "orchestrator", "reserve_points", 0, 50, 5))
        return g

    def alerts_group(self):
        g = Adw.PreferencesGroup(title="Alertes")
        g.add(self.switch_row("Notifications", "Seuils 80 % et 95 %, prévisions, bascules",
                              "alerts", "enabled"))
        g.add(self.spin_row("Prévenir avant la limite (min)", "Quand la fin de session estimée approche",
                            "alerts", "eta_minutes", 5, 60, 5))
        g.add(self.spin_row("Avance hebdomadaire (pts)", "Écart au rythme idéal de la semaine",
                            "alerts", "weekly_ahead_points", 5, 50, 5))
        g.add(self.switch_row("Réinitialisations", "Quand un compte redevient disponible",
                              "alerts", "resets"))
        g.add(self.switch_row("Connexions expirées", "Quand un profil doit être rajouté",
                              "alerts", "auth"))
        g.add(self.switch_row("Sessions Claude Code", "Quand une session a terminé ou attend ta réponse",
                              "alerts", "sessions"))
        return g

    def integration_group(self):
        from .. import integration
        g = Adw.PreferencesGroup(
            title="Intégration dans Claude Code",
            description="Ligne d'état en bas de chaque session (compte, %, recharge, prévision) et "
                        "bascule automatique quand une session atteint la limite. Modifie "
                        "~/.claude/settings.json (sauvegarde créée, ta ligne d'état n'est jamais remplacée).")
        st = integration.status()
        sl = {"ccs": "installée", "autre": "ta propre ligne d'état est conservée",
              None: "non installée"}[st["statusline"]]
        row = Adw.ActionRow(title="Ligne d'état · bascule après blocage",
                            subtitle=f"{sl} · {'installée' if st['hook'] else 'non installée'}")
        installed = st["statusline"] == "ccs" or st["hook"]
        btn = Gtk.Button(label="Retirer" if installed else "Installer", valign=Gtk.Align.CENTER)

        def toggle(*_):
            try:
                msgs = integration.uninstall() if installed else integration.install()
                self.window.toast(msgs[-1] if installed else "Intégration installée — relance tes sessions")
            except integration.IntegrationError as e:
                self.window.toast(str(e))
            self.render()
        btn.connect("clicked", toggle)
        row.add_suffix(btn)
        g.add(row)
        return g

    def warmup_group(self):
        g = Adw.PreferencesGroup(
            title="Warm-up",
            description="Envoie une requête minimale (Haiku) à l'heure choisie pour démarrer la "
                        "fenêtre de 5 h plus tôt. Laisse l'heure vide pour désactiver.")
        profiles = core.list_profiles()
        if not profiles:
            g.add(Adw.ActionRow(title="Aucun profil enregistré"))
        for p in profiles:
            g.add(self.warmup_row(p.name))
        return g

    def warmup_row(self, name):
        slots = self.s["warmup"].get(name) or []
        slot = slots[0] if slots else {"days": [0, 1, 2, 3, 4], "time": ""}
        exp = Adw.ExpanderRow(title=name,
                              subtitle=f"à {slot['time']}" if slot["time"] else "désactivé")
        entry = Adw.EntryRow(title="Heure (HH:MM)", text=slot["time"])
        days_box = Gtk.Box(css_classes=["linked"], valign=Gtk.Align.CENTER)
        toggles = []
        for i, lbl in enumerate(DAY_LABELS):
            t = Gtk.ToggleButton(label=lbl, active=i in slot["days"])
            toggles.append(t)
            days_box.append(t)
        days_row = Adw.ActionRow(title="Jours")
        days_row.add_suffix(days_box)

        def apply(*_):
            text = entry.get_text().strip()
            days = [i for i, t in enumerate(toggles) if t.get_active()]
            if not text:
                self.s["warmup"].pop(name, None)
                exp.set_subtitle("désactivé")
                entry.remove_css_class("error")
            elif TIME_RE.match(text) and days:
                self.s["warmup"][name] = [{"days": days, "time": text}]
                exp.set_subtitle(f"à {text}")
                entry.remove_css_class("error")
            else:
                entry.add_css_class("error")
                return
            self.save()
        entry.connect("changed", apply)
        for t in toggles:
            t.connect("toggled", apply)
        exp.add_row(entry)
        exp.add_row(days_row)
        return exp

    def service_group(self):
        g = Adw.PreferencesGroup(title="Service de collecte")
        active = systemctl("is-active", SERVICE).stdout.strip() == "active"
        running = daemon.running_pid() is not None
        row = Adw.ActionRow(
            title="En marche" if active or running else "Arrêté",
            subtitle="Relève l'usage toutes les 5 min (1 min près des limites)" if active or running
            else "Sans lui : pas de bascule automatique, d'alertes ni d'historique")
        btn = Gtk.Button(label="Redémarrer" if active else "Démarrer", valign=Gtk.Align.CENTER)

        def start(*_):
            r = systemctl("enable", "--now", SERVICE) if not active else systemctl("restart", SERVICE)
            self.window.toast("Service démarré" if r.returncode == 0
                              else "Service non installé : installe le paquet ccs")
            self.render()
        btn.connect("clicked", start)
        row.add_suffix(btn)
        g.add(row)
        g.add(self.indicator_row())
        return g

    def indicator_row(self):
        from ..tray import EXTENSION, watcher_available
        ok = watcher_available()
        row = Adw.ActionRow(
            title="Indicateur de la barre du haut",
            subtitle="Affiché" if ok else "Invisible : l'extension GNOME « Ubuntu AppIndicators » est désactivée")
        if not ok:
            btn = Gtk.Button(label="Activer l'extension", valign=Gtk.Align.CENTER)

            def enable(*_):
                try:
                    r = subprocess.run(["gnome-extensions", "enable", EXTENSION],
                                       capture_output=True, text=True, timeout=10)
                    ok_ = r.returncode == 0
                except (OSError, subprocess.SubprocessError):
                    ok_ = False
                self.window.toast("Extension activée" if ok_ else "Activation impossible")
                self.render()
            btn.connect("clicked", enable)
            row.add_suffix(btn)
        return row
