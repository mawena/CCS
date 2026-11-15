"""Compte par projet dans l'application : bascule proposée avant d'ouvrir une session, et
choix du compte d'un projet (« Compte de ce projet… »).

Le compte actif est global : basculer pour un projet fait aussi changer de compte toutes
les sessions ouvertes, d'où la question avant d'ouvrir. Jamais de proposition pendant une
pause de CCS ; une bascule choisie explicitement (« Nouvelle session ») reste possible.

Briques réutilisables par toute page qui liste des projets ou des conversations :
- `confirm_switch(window, cwd, ouvrir)` : à appeler à la place de l'ouverture directe ;
- `load_associations()` (hors de l'interface), `account_label(...)` (ligne d'une carte
  de projet), `account_menu_item(cwd, action)` et `account_action(window, done)`
  (entrée « Compte de ce projet… » et son action, paramètre : le dossier).
"""

from datetime import datetime, timezone

from gi.repository import Adw, Gio, GLib, Gtk

from .. import core, daemon, launch_options, pause, project_accounts
from ..launch_options import LaunchSpec
from .common import in_thread

MENU_LABEL = "Compte de ce projet…"


def paused_now():
    """CCS en pause (une pause illisible ne compte pas)."""
    try:
        return pause.pause_state(datetime.now(timezone.utc)) is not None
    except (OSError, ValueError, TypeError, OverflowError):
        return False


def pending_proposal(cwd):
    """(association à proposer ou None, compte actif) pour une session dans `cwd`."""
    try:
        profiles = core.list_profiles()
        associations = project_accounts.all()
    except OSError:
        return None, None
    active = next((p.name for p in profiles if p.active), None)
    return project_accounts.proposal(cwd, active, [p.name for p in profiles], paused_now(),
                                     associations), active


def confirm_switch(window, cwd, proceed):
    """Ouvre une session dans `cwd` par `proceed()`. Si le projet utilise un autre compte que
    l'actif (hors pause, sauf « ne plus demander »), demande d'abord : Basculer et ouvrir /
    Ouvrir sans basculer / Annuler. Renvoie le dialogue affiché, ou None."""
    proposal, active = pending_proposal(cwd)
    if proposal is None:
        proceed()
        return None
    heading, body = project_accounts.question(proposal, active)
    d = Adw.AlertDialog(heading=heading, body=body)
    never = Gtk.CheckButton(label="Ne plus demander pour ce projet", halign=Gtk.Align.CENTER)
    d.set_extra_child(never)
    d.add_response("cancel", "Annuler")
    d.add_response("open", "Ouvrir sans basculer")
    d.add_response("switch", "Basculer et ouvrir")
    d.set_response_appearance("switch", Adw.ResponseAppearance.SUGGESTED)
    d.set_default_response("switch")
    d.set_close_response("cancel")

    def on_response(_d, r):
        if r not in ("open", "switch"):
            return
        if never.get_active():
            try:
                project_accounts.set_ask(proposal.cwd, False)
            except OSError as e:
                window.toast(f"Réglage du projet non enregistré : {e.strerror or e}")
        if r == "open":
            proceed()
        else:
            switch_then(window, cwd, proposal, proceed)
    d.connect("response", on_response)
    d.present(window)
    return d


def switch_then(window, cwd, proposal, proceed):
    """Bascule sur le compte du projet (hors de l'interface), puis ouvre. Échec : message,
    rien n'est ouvert (comme « Nouvelle session »)."""
    spec = LaunchSpec(cwd=cwd, profile=proposal.profile, origin="projet")

    def work():
        try:
            return launch_options.switch_if_needed(spec, project=proposal.cwd)
        except OSError as e:
            return False, str(e)

    def done(result):
        switched, error = result
        if error:
            window.toast(f"Session non ouverte : {error}")
            return
        if switched:
            daemon.request_refresh()
            window.toast(f"Basculé sur « {proposal.profile} » — les sessions ouvertes suivront "
                         "à leur prochaine requête")
        proceed()
    in_thread(work, done)


# --------------------------------------------------------------------------
# Carte d'un projet : compte affiché, entrée de menu
# --------------------------------------------------------------------------

def load_associations():
    """Comptes par projet (liste vide si le fichier est illisible) ; peut tourner hors de
    l'interface, avec le reste d'un chargement."""
    try:
        return project_accounts.all()
    except OSError:
        return []


def account_label(cwd, active, associations, paused=None):
    """Ligne « Compte du projet : … » d'une carte de projet (None sans compte associé),
    mise en avant quand ce n'est pas le compte actif. `paused` : lu s'il n'est pas donné."""
    a = project_accounts.resolve(cwd, associations)
    if a is None:
        return None
    if paused is None:
        paused = paused_now()
    text = project_accounts.card_text(cwd, active, paused, associations)
    return Gtk.Label(label=text, xalign=0, wrap=True,
                     css_classes=["caption", "accent" if a.profile != active else "dim-label"])


def account_menu_item(cwd, action):
    """Entrée « Compte de ce projet… » d'un menu (`action` : « groupe.nom », paramètre s)."""
    item = Gio.MenuItem.new(MENU_LABEL, None)
    item.set_action_and_target_value(action, GLib.Variant.new_string(cwd))
    return item


def account_action(window, done=None, name="account"):
    """Action (paramètre : dossier) qui ouvre « Compte de ce projet… » ; `done()` après
    l'enregistrement (pour relire la page)."""
    action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
    action.connect("activate", lambda _a, v: choose_account(window, v.get_string(), done))
    return action


# --------------------------------------------------------------------------
# « Compte de ce projet… »
# --------------------------------------------------------------------------

def _radio_row(title, subtitle, group):
    check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
    if group is not None:
        check.set_group(group)
    row = Adw.ActionRow(title=title, subtitle=subtitle, use_markup=False, activatable_widget=check)
    row.add_prefix(check)
    return row, check


def choose_account(window, cwd, done=None):
    """Associe le dossier `cwd` à un compte (ou à aucun) et règle la proposition de bascule.
    `done()` est appelé après l'enregistrement."""
    folder = project_accounts.normalize(cwd)
    try:
        profiles = core.list_profiles()
        current = project_accounts.get(folder)
    except OSError as e:
        window.toast(f"Lecture impossible : {e.strerror or e}")
        return None
    own = current if current is not None and current.cwd == folder else None
    inherited = current if own is None else None

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    accounts = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
    none_sub = (f"Hérité de {project_accounts.short_path(inherited.cwd)} : {inherited.profile}"
                if inherited else "Le compte actif, quel qu'il soit")
    row, none_check = _radio_row("Aucun", none_sub, None)
    accounts.append(row)
    choices = [(None, none_check)]
    names = [p.name for p in profiles]
    for p in profiles:
        row, check = _radio_row(p.name, p.email + (" · compte actif" if p.active else ""), none_check)
        accounts.append(row)
        choices.append((p.name, check))
    if own is not None and own.profile not in names:
        row, check = _radio_row(own.profile, "compte introuvable", none_check)
        accounts.append(row)
        choices.append((own.profile, check))
    selected = own.profile if own is not None else None
    for name, check in choices:
        check.set_active(name == selected)
    box.append(accounts)

    options = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
    ask = Adw.SwitchRow(title="Proposer la bascule",
                        subtitle="À l'ouverture d'une session de ce projet depuis l'application",
                        active=own.ask if own is not None else True)
    options.append(ask)
    box.append(options)

    def sync(*_):
        ask.set_sensitive(not none_check.get_active())
    none_check.connect("toggled", sync)
    sync()

    d = Adw.AlertDialog(heading="Compte de ce projet",
                        body=f"{project_accounts.short_path(folder)}\nLes sessions de ce dossier et de ses "
                             "sous-dossiers proposeront de basculer sur ce compte.",
                        extra_child=box)
    d.add_response("cancel", "Annuler")
    d.add_response("save", "Enregistrer")
    d.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
    d.set_default_response("save")
    d.set_close_response("cancel")

    def on_response(_d, r):
        if r != "save":
            return
        chosen = next((name for name, check in choices if check.get_active()), None)
        try:
            project_accounts.set(folder, chosen)
            if chosen is not None:
                project_accounts.set_ask(folder, ask.get_active())
        except (OSError, ValueError) as e:
            window.toast(f"Enregistrement impossible : {getattr(e, 'strerror', None) or e}")
            return
        window.toast(f"Compte du projet : {chosen}" if chosen else "Ce projet n'a plus de compte associé")
        if done:
            done()
    d.connect("response", on_response)
    d.present(window)
    return d
