"""Onglet Réglages : bascule automatique, orchestrateur, alertes, conseils, conseiller de
formule, intégration, raccourcis clavier, warm-up, service.

`render()` recrée tous les groupes à chaque affichage de l'onglet ; chaque changement est
enregistré aussitôt (`settings.json`) et réveille le service."""

import re
import subprocess
from datetime import date, datetime, timezone

from gi.repository import Adw, GLib, GObject, Gtk

from .. import __version__, advisor, core, daemon, quiet, updates
from ..settings import load_settings, save_settings
from .common import string_factory
from .shortcuts_group import ShortcutsGroup

DAY_LABELS = ["L", "M", "M", "J", "V", "S", "D"]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SERVICE = "ccs-daemon.service"
WEEKDAYS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
# Jour du bilan de la semaine (`alerts.weekly_report_day`) : None = début de semaine de la
# plupart des comptes, sinon 0 = lundi … 6 = dimanche.
REPORT_DAYS = (("Début de semaine des comptes", None),) + tuple((d, i) for i, d in enumerate(WEEKDAYS))
# Formule d'un compte pour le conseiller (`advisor.profile_plans`) : None = détectée (clé retirée).
PLAN_CHOICES = (("Automatique", None),) + tuple((advisor.PLANS[k].label, k) for k in ("pro", "max5", "max20"))


def report_day(value):
    """Jour du bilan tel que `weekly_report.week_anchor` le comprend (None sinon)."""
    return value if isinstance(value, int) and 0 <= value <= 6 else None


def plan_status(name, detected, uncertain, unknown, forced):
    """Sous-titre de la ligne de formule d'un compte (`detect_plans` sans formule imposée)."""
    if name in unknown:
        plan = unknown[name]
        what = f"formule « {plan} » non reconnue" if plan and plan != "?" else "formule inconnue"
    else:
        what = f"détectée : {advisor.PLANS[detected[name]].label}"
        if name in uncertain:
            what += ", palier non indiqué"
    if forced:
        return f"Formule imposée ({what})"
    if name in unknown:
        return f"{what[:1].upper()}{what[1:]} : compte ignoré par le conseiller"
    return "Palier non indiqué par le compte : Max supposé (Ultra = l'ancien Max 20×)"


def prices_summary(settings, now=None):
    """Sous-titre des tarifs : ceux que retient le conseiller, personnalisés ou publiés (datés)."""
    prices, custom = advisor.plan_prices(settings)
    names = ", ".join(f"{advisor.PLANS[k].label} {advisor.money(v)}" for k, v in prices.items())
    if custom:
        return f"Tarifs personnalisés : {names} par mois"
    d = date.fromisoformat(advisor.PLAN_PRICES_DATE)
    stale = " — à vérifier" if advisor.prices_stale(now or datetime.now(timezone.utc)) else ""
    return (f"{names} par mois, hors taxes ({advisor.PLAN_PRICES_SOURCE}, "
            f"{d.day} {core.MONTHS[d.month - 1]} {d.year}){stale}")


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
        self.add_group(self.quiet_group())
        self.add_group(self.advice_group())
        self.add_group(self.advisor_group())
        self.add_group(self.integration_group())
        if self.window.terminals.available:
            self.add_group(self.terminal_group())
        # Recréé à chaque rendu : l'ancien groupe, retiré, cesse seul de suivre GSettings.
        self.add_group(ShortcutsGroup(toast=self.window.toast))
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

    @staticmethod
    def combo_row(title, subtitle, choices, current, on_change, use_subtitle=False):
        """Liste déroulante : `choices` = [(libellé, valeur)] ; `on_change(valeur, ligne)` au
        choix de l'utilisateur (pas à la création). Valeur inconnue : premier choix affiché.
        `use_subtitle` : le choix s'affiche en sous-titre (libellés longs, fenêtre étroite)."""
        values = [v for _label, v in choices]
        row = Adw.ComboRow(title=title, use_markup=False, use_subtitle=use_subtitle,
                           model=Gtk.StringList.new([label for label, _v in choices]))
        if subtitle and not use_subtitle:
            row.set_subtitle(subtitle)
            # Choix jamais abrégé (« Au… ») : c'est le sous-titre qui passe à la ligne.
            row.set_factory(string_factory(False))
        # Comparaison stricte : 0 (lundi) n'est ni None ni False.
        row.set_selected(next((i for i, v in enumerate(values)
                               if v is current or (type(v) is type(current) and v == current)), 0))

        def changed(r, _p):
            i = r.get_selected()
            if i < len(values):
                on_change(values[i], r)
        row.connect("notify::selected", changed)
        return row

    @staticmethod
    def depends_on(switch, *rows):
        """Lignes grisées tant que l'interrupteur est coupé."""
        for row in rows:
            switch.bind_property("active", row, "sensitive", GObject.BindingFlags.SYNC_CREATE)

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
        days_box = Gtk.Box(css_classes=["linked", "ccs-days"], valign=Gtk.Align.CENTER)
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
        g.add(self.switch_row("Fin de semaine prévue",
                              "Quand la limite hebdomadaire sera atteinte avant la réinitialisation "
                              "au rythme actuel (une fois par semaine et par compte)",
                              "alerts", "weekly_forecast"))
        g.add(self.spin_row("Prévenir avant l'épuisement de la semaine (jours)",
                            "Pour l'alerte de fin de semaine prévue",
                            "alerts", "weekly_forecast_days", 1, 6))
        g.add(self.switch_row("Réinitialisations", "Quand un compte redevient disponible",
                              "alerts", "resets"))
        g.add(self.switch_row("Connexions expirées", "Quand un profil doit être rajouté",
                              "alerts", "auth"))
        g.add(self.switch_row("Sessions Claude Code", "Quand une session a terminé ou attend ta réponse",
                              "alerts", "sessions"))
        g.add(self.switch_row("Rappel des sessions en attente",
                              "Une seule fois par attente, même si les notifications de sessions "
                              "sont coupées", "alerts", "waiting_reminder"))
        g.add(self.spin_row("Rappeler après (min)", "Durée d'attente de ta réponse avant le rappel",
                            "alerts", "waiting_reminder_min", 2, 120))
        return g

    def quiet_group(self):
        """Ne pas déranger : plage de silence (réglages) et silence temporaire (quiet.json)."""
        q = self.s["alerts"]["quiet"]
        g = Adw.PreferencesGroup(
            title="Ne pas déranger",
            description="Pendant le silence, les notifications sont retenues puis résumées en une "
                        "seule à la fin ; une session bloquée par la limite reste signalée.")

        def save_quiet(key, value):
            q[key] = value
            self.save()
        enabled = Adw.SwitchRow(title="Plage de silence", subtitle="Chaque jour actif, de l'heure "
                                "de début à l'heure de fin (peut passer minuit)", active=q["enabled"])
        enabled.connect("notify::active", lambda r, _p: save_quiet("enabled", r.get_active()))
        g.add(enabled)
        hours = Adw.ActionRow(title="Début et fin", subtitle="Heure locale")
        box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        entries = {}
        for key in ("start", "end"):
            e = Gtk.Entry(text=q[key], width_chars=5, max_width_chars=5)
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
                q.update(vals)
                self.save()
        for e in entries.values():
            e.connect("changed", apply_hours)
        hours.add_suffix(box)
        g.add(hours)
        days_row = Adw.ActionRow(title="Jours", subtitle="Jour où la plage commence")
        days_box = Gtk.Box(css_classes=["linked", "ccs-days"], valign=Gtk.Align.CENTER)
        toggles = []
        for i, lbl in enumerate(DAY_LABELS):
            t = Gtk.ToggleButton(label=lbl, active=i in q["days"])
            toggles.append(t)
            days_box.append(t)

        def apply_days(*_):
            save_quiet("days", [i for i, t in enumerate(toggles) if t.get_active()])
        for t in toggles:
            t.connect("toggled", apply_days)
        days_row.add_suffix(days_box)
        g.add(days_row)
        waiting = Adw.SwitchRow(title="Toujours prévenir quand une session attend ma réponse",
                                subtitle="Aussi pendant un silence temporaire ; son rappel passe "
                                         "de même", active=q["allow_waiting"])
        waiting.connect("notify::active", lambda r, _p: save_quiet("allow_waiting", r.get_active()))
        g.add(waiting)
        status, buttons = self.quiet_now_rows()
        g.add(status)
        g.add(buttons)
        return g

    def quiet_now_rows(self):
        """Silence temporaire : (ligne d'état, ligne de boutons qui se replient) : 1 h, 4 h,
        jusqu'à demain, reprendre."""
        row = Adw.ActionRow(title="Silence temporaire")
        box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4,
                          column_spacing=6, row_spacing=6, margin_top=6, margin_bottom=6,
                          margin_start=12, margin_end=12, homogeneous=False)

        def refresh():
            now = datetime.now(timezone.utc)
            st = quiet.quiet_state(now, self.s)
            row.set_subtitle("Pas de silence en cours" if st is None else
                             f"En silence ({'plage' if st.source == 'plage' else 'temporaire'}) "
                             f"{quiet.label(st, now)}")

        def choose(choice):
            now = datetime.now(timezone.utc)
            quiet.apply(choice, now, self.s)
            daemon.request_refresh()
            refresh()
            self.window.toast(quiet.command(["status"], now, self.s)[1])
        for choice, label in (("1h", "1 h"), ("4h", "4 h"), ("demain", "Jusqu'à demain"),
                              ("off", "Reprendre")):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, c=choice: choose(c))
            box.append(b)
        refresh()
        buttons = Adw.PreferencesRow(title="Boutons du silence temporaire", child=box)
        return row, buttons

    def advice_group(self):
        a = self.s["alerts"]
        g = Adw.PreferencesGroup(
            title="Conseils",
            description="Notifications d'aide, envoyées seulement quand les notifications sont "
                        "activées (groupe Alertes).")
        model = self.switch_row(
            "Proposer un modèle moins cher près des limites",
            "Au-delà du seuil, si tes réponses récentes viennent d'un modèle cher : passer d'Opus à "
            "Sonnet (ou de Sonnet à Haiku). Une notification par fenêtre de 5 h, et l'indice "
            "« → sonnet ? » dans la ligne d'état de Claude Code", "alerts", "model_advice")
        pct = self.spin_row("Seuil du conseil (%)", "Session ou semaine du compte actif",
                            "alerts", "model_advice_pct", 50, 99)
        self.depends_on(model, pct)
        report = self.switch_row(
            "Bilan de la semaine",
            "Une notification résume la semaine écoulée : usage des comptes, coût, modèles, projets, "
            "bascules (détail dans l'onglet Analyse)", "alerts", "weekly_report")

        def set_day(value, _row):
            a["weekly_report_day"] = value
            self.save()
        day = self.combo_row("Jour du bilan", None, REPORT_DAYS, report_day(a.get("weekly_report_day")),
                             set_day, use_subtitle=True)
        hour = self.spin_row(
            "Heure du bilan",
            "Pour un jour fixe. Sinon le bilan part quand la plupart des comptes commencent leur "
            "semaine (le lundi à cette heure si leur semaine n'est pas encore connue)",
            "alerts", "weekly_report_hour", 0, 23)
        self.depends_on(report, day, hour)
        monthly = self.switch_row(
            "Rapport mensuel",
            "Le 1er du mois, une notification résume le mois écoulé : usage, coût équivalent API, "
            "modèles, projets et évolution (détail dans l'onglet Analyse ou avec « ccs mois »)",
            "alerts", "monthly_report")
        monthly_hour = self.spin_row("Heure du rapport mensuel", "Heure d'envoi, le 1er du mois",
                                     "alerts", "monthly_report_hour", 0, 23)
        self.depends_on(monthly, monthly_hour)
        for row in (model, pct, report, day, hour, monthly, monthly_hour):
            g.add(row)
        return g

    def advisor_group(self):
        g = Adw.PreferencesGroup(
            title="Conseiller de formule",
            description="Combien de comptes Pro, Max ou Ultra pour ton usage réel, d'après les relevés "
                        "du service : onglet Analyse et « ccs formule ».")
        g.add(self.spin_row("Semaines analysées", "Historique des relevés pris en compte",
                            "advisor", "weeks", 1, 12))
        g.add(self.spin_row("Marge de sécurité (%)", "Ajoutée au besoin le plus haut mesuré",
                            "advisor", "margin_pct", 0, 100, 5))
        g.add(self.spin_row("Comptes au plus", "Nombre maximal de comptes dans une combinaison conseillée",
                            "advisor", "max_accounts", 1, 5))
        for row in self.plan_rows():
            g.add(row)
        g.add(self.prices_row())
        return g

    def plan_rows(self):
        """Formule d'un compte, seulement quand la détection ne suffit pas (formule inconnue, Max
        sans palier) ou qu'une formule est déjà imposée. « Automatique » retire la clé."""
        cfg = self.s["advisor"]
        if not isinstance(cfg.get("profile_plans"), dict):
            cfg["profile_plans"] = {}
        forced = cfg["profile_plans"]
        profiles = core.list_profiles()
        detected, uncertain, unknown = advisor.detect_plans(profiles, {})
        unknown = dict(unknown)
        rows = []
        for p in profiles:
            name, current = p.name, forced.get(p.name)
            current = current if current in advisor.PLANS else None
            if current is None and name not in unknown and name not in uncertain:
                continue

            def changed(key, row, name=name):
                if key is None:
                    forced.pop(name, None)
                else:
                    forced[name] = key
                row.set_subtitle(plan_status(name, detected, uncertain, unknown, key is not None))
                self.save()
            rows.append(self.combo_row(f"Formule de « {name} »",
                                       plan_status(name, detected, uncertain, unknown, current is not None),
                                       PLAN_CHOICES, current, changed))
        return rows

    def prices_row(self):
        """Tarifs des formules ($/mois) : une valeur égale au tarif publié retire la clé."""
        cfg = self.s["advisor"]
        if not isinstance(cfg.get("plan_prices"), dict):
            cfg["plan_prices"] = {}
        custom = cfg["plan_prices"]
        prices, _custom = advisor.plan_prices(self.s)
        exp = Adw.ExpanderRow(title="Tarifs des formules", subtitle=prices_summary(self.s))
        for key, plan in advisor.PLANS.items():
            row = Adw.SpinRow.new_with_range(0, 2000, 1)
            row.set_title(f"{plan.label} ($/mois)")
            row.set_subtitle(f"Tarif publié : {advisor.money(plan.price)}")
            row.set_value(prices[key])

            def changed(r, _p, key=key, default=plan.price):
                value = int(r.get_value())
                if value == default:
                    custom.pop(key, None)
                else:
                    custom[key] = value
                exp.set_subtitle(prices_summary(self.s))
                self.save()
            row.connect("notify::value", changed)
            exp.add_row(row)
        return exp

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

    def terminal_group(self):
        """Les deux interrupteurs du menu « ⋮ » de la page Terminaux (gardés dans
        terminals.json) : changés par l'action de la page, qui reste la seule à écrire."""
        terms = self.window.terminals
        g = Adw.PreferencesGroup(title="Terminal intégré")
        for title, subtitle, action, key in (
                ("Reprise automatique après une limite",
                 "Après une bascule due à une limite, la conversation reprend seule (« continue »)",
                 "auto-resume", "auto_resume"),
                ("Rouvrir les onglets au démarrage",
                 "Sinon, l'application propose de les rouvrir", "reopen-at-start", "reopen_at_start")):
            row = Adw.SwitchRow(title=title, subtitle=subtitle, active=terms.options[key])
            row.connect("notify::active", lambda r, _p, a=action: terms.page_actions.change_action_state(
                a, GLib.Variant.new_boolean(r.get_active())))
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
        days_box = Gtk.Box(css_classes=["linked", "ccs-days"], valign=Gtk.Align.CENTER)
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
        g.add(self.switch_row("Nouvelles versions",
                              f"Version installée : {__version__}. Vérifie une fois par jour sur "
                              "GitHub et prévient une seule fois par version", "updates", "enabled"))
        release = updates.available() if self.s["updates"]["enabled"] else None
        if release:
            new = Adw.ActionRow(title=f"CCS {release.version} est disponible",
                                subtitle="Installe le nouveau paquet : le service et l'indicateur "
                                         "se relancent tout seuls")
            new.add_suffix(Gtk.LinkButton(uri=release.url, label="Voir la version",
                                          valign=Gtk.Align.CENTER))
            g.add(new)
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
