"""Onglet Réglages : bascule automatique, orchestrateur, alertes, conseils, conseiller de
formule, intégration, raccourcis clavier, téléphone, sauvegarde, archive, sessions, tâches,
budgets, warm-up, service.

`render()` recrée tous les groupes à chaque affichage de l'onglet ; chaque changement est
enregistré aussitôt (`settings.json`) et réveille le service."""

import re
import subprocess
from datetime import date, datetime, timezone

from gi.repository import Adw, Gdk, GLib, GObject, Gtk

from .. import __version__, advisor, archive, budget, chat_options, context_alert, core, daemon, quiet, \
    session_memory, tasks, updates
from ..settings import load_settings, save_settings
from .backup_group import BackupGroup
from . import style
from .common import account_hex, in_thread, string_factory, sync_accounts
from .phone_group import PhoneGroup
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
        # Remplaçable (essais) : demande de confirmation avant « Tout autoriser ».
        self.confirm_dangerous = self._ask_dangerous

    def save(self):
        save_settings(self.s)
        daemon.request_refresh()
        self.window.sync_auto_switch(self.s["auto_switch"]["enabled"])

    def render(self):
        for g in self.groups:
            self.remove(g)
        self.groups = []
        self.s = self.seeded(load_settings())
        self.add_group(self.appearance_group())
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
        self.add_group(PhoneGroup(self.s, self.save, toast=self.window.toast))
        self.add_group(BackupGroup(toast=self.window.toast))
        self.add_group(self.archive_group())
        self.add_group(self.sessions_group())
        self.add_group(self.chat_files_group())
        self.add_group(self.projects_group())
        self.add_group(self.tasks_group())
        self.add_group(self.budget_group())
        self.add_group(self.warmup_group())
        self.add_group(self.service_group())

    @staticmethod
    def seeded(settings):
        """Réglages complétés des sections de la phase 11 absentes (valeurs par défaut de chaque
        module) : les groupes marchent même si `settings.json` ne les connaît pas encore."""
        for name, cfg in (("archive", archive.config(settings)), ("tasks", tasks.config(settings)),
                          ("budget", budget.config(settings)),
                          ("context_alert", context_alert.config(settings))):
            section = settings.get(name)
            section = settings[name] = section if isinstance(section, dict) else {}
            for key, value in cfg.items():
                if key == "night":
                    night = section.get("night")
                    night = section["night"] = night if isinstance(night, dict) else {}
                    for k, v in value.items():
                        night.setdefault(k, v)
                else:
                    section.setdefault(key, value)
        sessions = settings.get("sessions")
        sessions = settings["sessions"] = sessions if isinstance(sessions, dict) else {}
        sessions.setdefault("idle_hours", int(session_memory.idle_hours(settings)))
        return settings

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

    SCHEMES = (("Automatique (suit le système)", "auto"), ("Clair", "clair"), ("Sombre", "sombre"))

    def appearance_group(self):
        """Thème (Auto / Clair / Sombre) et couleur de chaque compte (cartes, jauges, courbes)."""
        ap = self.s.setdefault("appearance", {})
        ap.setdefault("color_scheme", "auto")
        colors = ap.setdefault("account_colors", {})
        g = Adw.PreferencesGroup(
            title="Apparence",
            description="Thème de l'application et couleur de chaque compte, reprise sur les cartes, "
                        "les jauges et les courbes.")

        def choose_scheme(value, _row):
            ap["color_scheme"] = value
            style.apply_color_scheme(value)
            self.save()
        g.add(self.combo_row("Thème", "Auto suit le réglage du système", self.SCHEMES,
                             ap["color_scheme"], choose_scheme))
        profiles = [p.name for p in core.list_profiles()]
        sync_accounts(profiles)
        self.color_buttons = {}
        for name in profiles:
            g.add(self.color_row(name, colors))
        return g

    def color_row(self, name, colors):
        row = Adw.ActionRow(title=name, subtitle="Couleur du compte", use_markup=False)
        rgba = Gdk.RGBA()
        rgba.parse(account_hex(name))
        button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), rgba=rgba,
                                       valign=Gtk.Align.CENTER, tooltip_text="Choisir la couleur")
        reset = Gtk.Button(icon_name="edit-undo-symbolic", css_classes=["flat"], valign=Gtk.Align.CENTER,
                           tooltip_text="Couleur automatique", sensitive=name in colors)
        self.color_buttons[name] = button

        def apply():
            self.save()
            sync_accounts([p.name for p in core.list_profiles()])

        def picked(b, _p):
            c = b.get_rgba()
            colors[name] = "#{:02x}{:02x}{:02x}".format(*(round(v * 255) for v in (c.red, c.green, c.blue)))
            reset.set_sensitive(True)
            apply()
        button.connect("notify::rgba", picked)

        def clicked(*_):
            colors.pop(name, None)
            reset.set_sensitive(False)
            apply()
            auto = Gdk.RGBA()
            auto.parse(account_hex(name))
            button.handler_block_by_func(picked)
            button.set_rgba(auto)
            button.handler_unblock_by_func(picked)
        reset.connect("clicked", clicked)
        row.add_suffix(reset)
        row.add_suffix(button)
        return row

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

    def archive_group(self):
        g = Adw.PreferencesGroup(
            title="Archive des conversations",
            description="Claude Code efface ses conversations après 30 jours : le service en garde une "
                        "copie compressée, que tu peux rouvrir et reprendre depuis l'onglet Sessions.")
        enabled = self.switch_row("Archiver les conversations", "Une copie par conversation, mise à jour "
                                  "si elle change", "archive", "enabled")
        days = self.spin_row("Archiver après (jours d'inactivité)", "Une conversation inchangée depuis "
                             "ce temps est copiée", "archive", "idle_days", 0, 365)
        age = self.spin_row("Supprimer l'archive après (jours)", "0 = ne jamais supprimer",
                            "archive", "max_age_days", 0, 3650, 30)
        size = Adw.ActionRow(title="Taille de l'archive", subtitle="Calcul…")
        self.depends_on(enabled, days, age)
        for row in (enabled, days, age, size):
            g.add(row)

        def done(result):
            size.set_subtitle("Archive illisible" if result is None else
                              f"{result[0]} conversation(s), {session_memory.fmt_bytes(result[1])}")

        def work():
            try:
                return archive.stats()
            except Exception:  # noqa: BLE001 — l'archive peut manquer ou être illisible
                return None
        in_thread(work, done)
        return g

    def sessions_group(self):
        g = Adw.PreferencesGroup(
            title="Sessions ouvertes",
            description="Mémoire des sessions Claude Code et alerte quand une conversation devient "
                        "lourde (chaque message coûte alors plus cher en quota).")
        g.add(self.spin_row("Sessions inactives après (h)", "Au-delà, l'onglet Sessions propose de les "
                            "fermer pour libérer la mémoire ; rien n'est jamais fermé tout seul",
                            "sessions", "idle_hours", 1, 72))
        alert = self.switch_row("Alerte de contexte lourd", "Une notification par session, avec le coût "
                                "d'un message et le conseil /compact", "context_alert", "enabled")
        tokens = self.spin_row("Seuil du contexte lourd (tokens)", "Taille du contexte au-delà de laquelle "
                               "prévenir", "context_alert", "threshold_tokens", 10000, 1000000, 10000)
        self.depends_on(alert, tokens)
        g.add(alert)
        g.add(tokens)
        return g

    LAYOUTS = (("A : fichier au centre", "A"), ("B : chat au centre", "B"))

    def chat_files_group(self):
        """Chat (mise en veille, droits par défaut) et fichiers (fichiers ignorés, disposition)."""
        chat = self.s["chat"] = self.s.get("chat") if isinstance(self.s.get("chat"), dict) else {}
        files = self.s["files"] = self.s.get("files") if isinstance(self.s.get("files"), dict) else {}
        chat.setdefault("idle_suspend_min", 30)
        chat.setdefault("rights", "manual")
        files.setdefault("show_ignored", False)
        files.setdefault("layout", "B")
        g = Adw.PreferencesGroup(
            title="Chat et fichiers",
            description="Valeurs de départ des nouveaux chats et de l'espace de session.")
        g.add(self.spin_row("Mettre en veille un chat inactif après (min)",
                            "0 : jamais. Le processus claude est suspendu, la conversation reste ouverte",
                            "chat", "idle_suspend_min", 0, 1440))
        rights = list(chat_options.RIGHTS)
        current = chat["rights"]
        row = self.combo_row("Droits par défaut des nouveaux chats",
                             "Réglable ensuite dans la barre de chaque chat",
                             rights, current, lambda value, r: self._pick_rights(value, r))
        self._rights_row, self._rights_value = row, current
        g.add(row)
        g.add(self.switch_row("Afficher les fichiers ignorés par git",
                              "Dans l'arbre des fichiers de l'espace de session", "files", "show_ignored"))
        g.add(self.combo_row("Disposition par défaut", "A : fichier au centre. B : chat au centre",
                             list(self.LAYOUTS), files["layout"],
                             lambda value, _r: self._set("files", "layout", value)))
        return g

    def _set(self, section, key, value):
        self.s[section][key] = value
        self.save()

    def _pick_rights(self, value, row):
        if value == self._rights_value:
            return
        if value == "bypassPermissions":
            self.confirm_dangerous(lambda: self._apply_rights(value), lambda: self._revert_rights())
        else:
            self._apply_rights(value)

    def _apply_rights(self, value):
        self._rights_value = value
        self._set("chat", "rights", value)

    def _revert_rights(self):
        values = [v for _l, v in chat_options.RIGHTS]
        self._rights_row.set_selected(values.index(self._rights_value))

    def _ask_dangerous(self, on_yes, on_no):
        from .chat_bar import DANGER_TEXT, DANGER_TITLE
        dialog = Adw.AlertDialog(heading="Tout autoriser ?", body=f"{DANGER_TITLE}. {DANGER_TEXT}")
        dialog.add_response("cancel", "Annuler")
        dialog.add_response("allow", "Tout autoriser")
        dialog.set_response_appearance("allow", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, r: on_yes() if r == "allow" else on_no())
        dialog.present(self.get_root())

    def projects_group(self):
        """Projets masqués de la page Projets, avec « Réafficher » pour chacun."""
        self.s["projects"] = self.s.get("projects") if isinstance(self.s.get("projects"), dict) else {}
        self.s["projects"].setdefault("hidden", [])
        g = Adw.PreferencesGroup(title="Projets")
        self._hidden_row = Adw.ExpanderRow(title="Projets masqués")
        self._hidden_rows = []
        self._fill_hidden()
        g.add(self._hidden_row)
        return g

    def _fill_hidden(self):
        for r in self._hidden_rows:
            self._hidden_row.remove(r)
        self._hidden_rows = []
        hidden = list(self.s["projects"]["hidden"])
        self._hidden_row.set_subtitle(f"{len(hidden)} masqué(s)" if hidden else "Aucun projet masqué")
        if not hidden:
            self._hidden_row.set_expanded(False)
        for path in hidden:
            row = Adw.ActionRow(title=GLib.markup_escape_text(path.rstrip("/").rsplit("/", 1)[-1] or path),
                                subtitle=GLib.markup_escape_text(path))
            button = Gtk.Button(label="Réafficher", valign=Gtk.Align.CENTER)
            button.connect("clicked", lambda _b, p=path: self.unhide_project(p))
            row.add_suffix(button)
            self._hidden_row.add_row(row)
            self._hidden_rows.append(row)

    def unhide_project(self, path):
        hidden = [p for p in load_settings().get("projects", {}).get("hidden", []) if p != path]
        self.s["projects"]["hidden"] = hidden
        self.save()
        self._fill_hidden()
        page = getattr(self.window, "projects", None)
        if page is not None:
            page.refresh()

    def tasks_group(self):
        night = self.s["tasks"]["night"]
        g = Adw.PreferencesGroup(
            title="Tâches",
            description="Messages que Claude traite sans fenêtre (onglet Planning, « ccs tache »), "
                        "avec le compte actif, une seule à la fois.")
        enabled = self.switch_row("Exécuter les tâches", "Sinon elles restent en file", "tasks", "enabled")
        hours = Adw.ActionRow(title="Plage de nuit", subtitle="Pour les tâches « cette nuit » (peut passer minuit)")
        box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        entries = {}
        for key in ("start", "end"):
            e = Gtk.Entry(text=night[key], width_chars=5, max_width_chars=5)
            entries[key] = e
            box.append(e)
            if key == "start":
                box.append(Gtk.Label(label="→"))

        def apply_night(*_):
            vals = {k: e.get_text().strip() for k, e in entries.items()}
            bad = False
            for k, e in entries.items():
                if TIME_RE.match(vals[k]):
                    e.remove_css_class("error")
                else:
                    e.add_css_class("error")
                    bad = True
            if not bad:
                night.update(vals)
                self.save()
        for e in entries.values():
            e.connect("changed", apply_night)
        hours.add_suffix(box)
        attempts = self.spin_row("Tentatives par tâche", "Reprises après une limite atteinte",
                                 "tasks", "max_attempts", 1, 10)
        self.depends_on(enabled, hours, attempts)
        for row in (enabled, hours, attempts):
            g.add(row)
        return g

    def budget_group(self):
        g = Adw.PreferencesGroup(
            title="Budgets par projet",
            description="Plafond hebdomadaire en équivalent dollars, réglé dans l'onglet Analyse ; "
                        "rien n'est jamais bloqué.")
        g.add(self.switch_row("Alertes de budget", "Une notification à 80 % et à 100 % du budget de "
                              "chaque projet", "budget", "enabled"))
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
