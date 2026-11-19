"""Réglages → page « Machines » : calcul réparti par Ricochet, comme la page Machines du web.

Trois groupes : les commandes `ccs distant lancer` en cours sur ce PC (avec « Arrêter », confirmé),
les machines du relais (en ligne ou non, charge, mémoire, outils, « Relever les outils ») et les
réglages du client Ricochet (adresse du relais, jeton jamais réaffiché). Les lectures réseau
tournent dans un fil ; la page se relit toutes les 10 s tant qu'elle est affichée.
"""

import threading
import time

from gi.repository import Adw, GLib, Gtk

from .. import distant

REFRESH_S = 10


def _threaded(work, done):
    def target():
        try:
            result, error = work(), None
        except Exception as e:  # noqa: BLE001 — l'erreur est montrée à l'utilisateur
            result, error = None, e
        GLib.idle_add(lambda: (done(result, error), False)[1])
    threading.Thread(target=target, daemon=True).start()


def since(ts, now=None):
    s = max(0, int((now or time.time()) - ts))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d}"
    return f"{s // 3600} h {s // 60 % 60:02d}"


def machine_subtitle(m, tools=None):
    """Ligne d'état d'une machine (sous son nom)."""
    if not m.online:
        return "Hors ligne"
    parts = [f"charge {m.load:.1f} sur {m.cores} cœurs" if m.cores else "charge inconnue"]
    if m.mem_total:
        parts.append(f"mémoire {m.mem_used / 2**30:.0f} / {m.mem_total / 2**30:.0f} Go")
    if m.local:
        parts.append("cette machine")
    elif not m.ports:
        parts.append("tunnel SSH non activé ([tunnel] dans son agent.toml)")
    elif tools is not None:
        parts.append("outils : " + (", ".join(tools) or "aucun de la liste"))
    return " · ".join(parts)


def known_tools(machine_id):
    inv = distant._load_inventory().get(machine_id)
    if not inv:
        return None
    return sorted(k for k, v in (inv.get("outils") or {}).items() if v)


class MachinesPage(Adw.PreferencesPage):
    def __init__(self, toast=None, runner=None, fetch=None):
        super().__init__(title="Machines", icon_name="network-server-symbolic")
        self.toast = toast or (lambda _t: None)
        self.runner = runner or _threaded
        self.fetch = fetch or distant.fetch_machines
        self.last_alert = None
        self._timer = None
        self._loading = False

        self.running_group = Adw.PreferencesGroup(
            title="Commandes en cours",
            description="Builds et tests lancés par les chats avec « ccs distant lancer ».")
        self.machines_group = Adw.PreferencesGroup(
            title="Machines", description="Les machines du relais Ricochet.")
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text="Actualiser", css_classes=["flat"])
        refresh.connect("clicked", lambda _b: self.reload())
        self.machines_group.set_header_suffix(refresh)
        self.settings_group = Adw.PreferencesGroup(
            title="Réglages du calcul réparti",
            description="Enregistrés dans ~/.config/ricochet/client.toml (droits 600). Utilisateur "
                        "et port SSH par machine : ~/.config/ccs/distant.toml.")
        for g in (self.running_group, self.machines_group, self.settings_group):
            self.add(g)
        self._rows = {"running": [], "machines": []}
        self.build_settings()
        self.connect("map", lambda _w: self.start())
        self.connect("unmap", lambda _w: self.stop_timer())

    # ---- rafraîchissement ------------------------------------------------------------------

    def start(self):
        self.reload()
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(REFRESH_S, self._tick)

    def stop_timer(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self):
        self.reload()
        return True

    def reload(self):
        self.show_running(distant.running())
        if self._loading:
            return
        self._loading = True

        def done(machines, error):
            self._loading = False
            self.show_machines(machines or [], error)
        self.runner(self.fetch, done)

    def _replace(self, key, group, rows):
        for row in self._rows[key]:
            group.remove(row)
        self._rows[key] = rows
        for row in rows:
            group.add(row)

    # ---- commandes en cours -----------------------------------------------------------------

    def show_running(self, records):
        rows = []
        if not records:
            rows.append(Adw.ActionRow(title="Aucune commande en cours"))
        for r in records:
            where = r.get("projet", "") + ("/" + r["dossier"] if r.get("dossier") else "")
            row = Adw.ActionRow(title=GLib.markup_escape_text(r.get("commande", "")),
                                subtitle=GLib.markup_escape_text(
                                    f"{r.get('machine', '?')} · {where} · depuis {since(r.get('debut', 0))}"))
            btn = Gtk.Button(label="Arrêter", valign=Gtk.Align.CENTER, css_classes=["destructive-action"])
            btn.connect("clicked", lambda _b, rec=r: self.ask_stop(rec))
            row.add_suffix(btn)
            rows.append(row)
        self._replace("running", self.running_group, rows)

    def ask_stop(self, record):
        alert = Adw.AlertDialog(heading="Arrêter cette commande ?",
                                body=f"{record.get('commande', '')}\nsur {record.get('machine', '?')}")
        alert.add_response("cancel", "Annuler")
        alert.add_response("stop", "Arrêter")
        alert.set_response_appearance("stop", Adw.ResponseAppearance.DESTRUCTIVE)
        alert.set_close_response("cancel")

        def answered(_d, response):
            if response != "stop":
                return
            try:
                distant.stop(record["pid"])
                self.toast("Commande arrêtée")
            except distant.DistantError as e:
                self.toast(str(e))
            GLib.timeout_add(1500, lambda: (self.show_running(distant.running()), False)[1])
        alert.connect("response", answered)
        self.last_alert = alert
        if self.get_root() is not None:
            alert.present(self)

    # ---- machines ----------------------------------------------------------------------------

    def show_machines(self, machines, error=None):
        rows = []
        if error is not None:
            rows.append(Adw.ActionRow(title="Machines indisponibles",
                                      subtitle=GLib.markup_escape_text(str(error))))
        elif not machines:
            rows.append(Adw.ActionRow(title="Aucune machine sur le relais Ricochet"))
        for m in machines:
            title = f"{m.name} ({m.id})" if m.name and m.name != m.id else m.id
            row = Adw.ActionRow(title=GLib.markup_escape_text(title),
                                subtitle=GLib.markup_escape_text(machine_subtitle(m, known_tools(m.id))))
            dot = Gtk.Image(icon_name="emblem-ok-symbolic" if m.online else "network-offline-symbolic",
                            css_classes=["success" if m.online else "dim-label"])
            row.add_prefix(dot)
            if m.online and m.ports and not m.local:
                btn = Gtk.Button(label="Relever les outils", valign=Gtk.Align.CENTER, css_classes=["flat"])
                btn.connect("clicked", lambda b, mach=m, r=row: self.probe(mach, r, b))
                row.add_suffix(btn)
            rows.append(row)
        self._replace("machines", self.machines_group, rows)

    def probe(self, machine, row, button):
        button.set_sensitive(False)
        button.set_label("Relevé…")

        def work():
            return distant.inventory(machine, distant.load_overrides(), refresh=True)

        def done(inv, error):
            button.set_sensitive(True)
            button.set_label("Relever les outils")
            if error is not None:
                self.toast(str(error))
                return
            tools = sorted(k for k, v in inv.get("outils", {}).items() if v)
            row.set_subtitle(GLib.markup_escape_text(machine_subtitle(machine, tools)))
        self.runner(work, done)

    # ---- réglages ------------------------------------------------------------------------------

    def build_settings(self):
        s = distant.client_settings()
        if not s["agent"]:
            self.settings_group.add(Adw.ActionRow(
                title="ricochet-agent n'est pas installé",
                subtitle="Il faut ricochet-agent 0.3.0 ou plus sur ce PC pour le calcul réparti."))
        self.f_relais = Adw.EntryRow(title="Adresse du relais", text=s["relais"])
        self.f_jeton = Adw.PasswordEntryRow(
            title="Jeton (inchangé si vide)" if s["jeton"] else "Jeton des tunnels")
        save = Gtk.Button(label="Enregistrer", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        save.connect("clicked", lambda _b: self.save_settings())
        self.f_jeton.add_suffix(save)
        self.settings_group.add(self.f_relais)
        self.settings_group.add(self.f_jeton)

    def save_settings(self):
        try:
            s = distant.save_client(self.f_relais.get_text().strip(), self.f_jeton.get_text().strip() or None)
        except distant.DistantError as e:
            self.toast(str(e))
            return False
        self.f_jeton.set_text("")
        self.f_jeton.set_title("Jeton (inchangé si vide)" if s["jeton"] else "Jeton des tunnels")
        self.toast("Réglages enregistrés")
        self.reload()
        return True
