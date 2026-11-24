"""Onglet « Réseau » du bureau : le contenu de l'onglet web `#/reseau`, à la manière GTK.

- « Appareils » : une fiche dépliable par appareil du réseau maillé (genre, en ligne ou non,
  chemin réel : réseau local, direct par internet ou relais du VPS), son adresse sur le réseau à
  copier, les adresses qu'il publie avec leur type, son trafic, « Mesurer » (`tailscale ping`),
  « Renommer » et « Retirer du réseau » (confirmé). La machine de calcul Ricochet qui lui
  correspond s'y rattache (charge, mémoire, places et limite) ; celle hors du réseau maillé a sa
  propre fiche, comme sur le web.
- « Son partagé » (SoundGroup, `audio.*`), puis « Travaux », « Lancer une commande »,
  « Ajouter un appareil » (PC Linux par lien Ricochet ou par clé jetable, Android, iPhone) et
  « Secours Ricochet » (MachinesPage).

Les méthodes `network.*` sont celles du web, demandées au pont du serveur CCS (socket local si ce
PC l'héberge, sinon le premier serveur appairé, comme le son partagé) : le bureau voit le réseau
depuis le serveur, comme le web. Serveur injoignable : `tailscale` et `headscale` de ce PC.
Tout appel lent part dans un fil, le résultat revient dans la page.
"""

import socket

from gi.repository import Adw, GLib, Gtk, Pango

from .. import audio, network
from .machines_page import REFRESH_S, MachinesPage, machine_subtitle
from .servers_group import _threaded

PATHS = {"self": "Serveur CCS", "lan": "Réseau local", "direct": "Direct par internet",
         "relay": "Relais du VPS", "ricochet": "Par Ricochet", "idle": "En veille",
         "offline": "Hors ligne"}
ICONS = {"apple": "phone-apple-iphone-symbolic", "phone": "phone-symbolic",
         "laptop": "computer-symbolic", "server": "network-server-symbolic",
         "desktop": "computer-symbolic"}


class MeshApi:
    """`network.*` comme le web : par le pont du serveur CCS ; s'il est injoignable, les mêmes
    fonctions sur ce PC (`remote` dit d'où vient le dernier état)."""

    def __init__(self, call=None, local_status=None):
        self._call = call or audio.call
        self._local_status = local_status or network.overview
        self.remote = True

    def status(self):
        try:
            st = self._call("network.status")
            self.remote = True
        except Exception as e:  # noqa: BLE001 — montré dans la page, vue locale à la place
            st = dict(self._local_status())
            st["bridge_error"] = str(e)
            self.remote = False
        return st

    def call(self, method, **params):
        if self.remote:
            return self._call(method, **params)
        name = params.get("name")
        if method == "network.ping":
            return network.ping(name)
        if method == "network.rename":
            return network.rename(name, params["new"])
        if method == "network.remove":
            return network.remove(name)
        if method == "network.key":
            key = network.auth_key()
            return {"key": key, "url": network.SERVER_URL, "linux": network.join_lines(key, name)}
        if method == "network.register":
            return {"name": network.register(params["key"])}
        raise network.NetworkError(f"Méthode inconnue : {method}")


def match_machine(machines, d, is_self, here="", remote=True):
    """Machine de calcul d'une fiche (règles de `matchMachine` du web). La machine « locale » du
    relais est ce PC : sa fiche est celle qui porte son nom d'hôte (ou « cet appareil » quand
    l'état vient de ce PC)."""
    keys = {str(k).lower() for k in (d.get("name"), d.get("host")) if k}
    ips = d.get("ips") or []
    for m in machines:
        if m.get("local"):
            if (is_self and not remote) or (here and here.lower() in keys):
                return m
            continue
        if (m.get("mesh_ip") and m["mesh_ip"] in ips) or any(
                k and str(k).lower() in keys for k in (m.get("mesh"), m.get("id"), m.get("host"))):
            return m
    return None


def device_subtitle(d, self_label="Serveur CCS"):
    """« En ligne · Direct par internet · android »."""
    path = d.get("path", "")
    parts = ["En ligne" if d.get("online") else "Hors ligne"]
    if path not in ("offline", ""):
        parts.append(self_label if path == "self" else PATHS.get(path, path))
    extra = [d.get("os") or ""]
    if d.get("host") and d.get("host") != d.get("name"):
        extra.append(d["host"])
    return " · ".join(parts + [x for x in extra if x])


def published(d):
    """Adresses publiées hors réseau maillé, une par ligne : « Local : 192.168.1.20 »."""
    lines = []
    for a in d.get("addrs") or []:
        ip, kind = network.addr_kind(a)
        if kind != "mesh":
            lines.append(f"{network.ADDR_LABELS[kind]} : {ip}")
    return "\n".join(lines)


def _flat(label, icon=None, tooltip=None, css=None):
    b = Gtk.Button(valign=Gtk.Align.CENTER, tooltip_text=tooltip)
    if icon and not label:
        b.set_icon_name(icon)
    elif icon:
        b.set_child(Adw.ButtonContent(icon_name=icon, label=label))
    else:
        b.set_label(label)
    b.add_css_class("flat")
    if css:
        b.add_css_class(css)
    return b


class MeshGroup(Adw.PreferencesGroup):
    """« Appareils » : une fiche par appareil du réseau maillé, rechargée toutes les 10 s."""

    def __init__(self, toast=None, runner=None, api=None, on_limit=None, on_status=None):
        super().__init__(title="Appareils",
                         description=f"Réseau maillé {network.SERVER_URL.split('//')[-1]}")
        self.toast = toast or (lambda _t: None)
        self.runner = runner or _threaded
        self.api = api or MeshApi()
        self.on_limit = on_limit
        self.on_status = on_status or (lambda _st: None)
        self.here = socket.gethostname()
        self.st = None
        self.machines = []
        self.pings = {}
        self.expanded = set()
        self.last_alert = None
        self._rows = []
        self._loading = False
        self._timer = None
        self.connect("map", lambda _w: self.start_refresh())
        self.connect("unmap", lambda _w: self.stop_refresh())

    # ---- rechargement ----------------------------------------------------------------------

    def start_refresh(self):
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(REFRESH_S * 2, lambda: (self.refresh(), True)[1])
        self.refresh()

    def stop_refresh(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def refresh(self):
        if self._loading:
            return
        self._loading = True
        self.runner(self.api.status, self._loaded)

    def _loaded(self, st, error):
        self._loading = False
        self.st = {"error": str(error), "peers": []} if error is not None else st
        self.on_status(self.st)
        self.draw()

    def set_machines(self, machines):
        self.machines = list(machines or [])
        if self.st is not None:
            self.draw()

    # ---- dessin ----------------------------------------------------------------------------

    def _busy(self):
        """Pas de redessin sous les doigts (limite en cours de saisie)."""
        root = self.get_root()
        focus = root.get_focus() if root is not None and hasattr(root, "get_focus") else None
        return (focus is not None and focus.is_ancestor(self)
                and focus.get_ancestor(Gtk.SpinButton) is not None)

    def _clear(self):
        for row in self._rows:
            if isinstance(row, Adw.ExpanderRow) and row.get_expanded():
                self.expanded.add(row.get_title())
            elif isinstance(row, Adw.ExpanderRow):
                self.expanded.discard(row.get_title())
            self.remove(row)
        self._rows = []

    def _add(self, row):
        self.add(row)
        self._rows.append(row)

    def headline(self, st):
        """« Connecté · 4/5 en ligne · 2 en local · 1 en direct · 1 par relais »."""
        if not st.get("installed", True):
            state = "Pas encore dans le réseau"
        elif st.get("state") == "Running":
            state = "Connecté"
        else:
            state = st.get("state") or "Arrêté"
        s = network.summary(st)
        parts = [state, f"{s['online']}/{s['total']} en ligne", f"{s['lan']} en local",
                 f"{s['direct']} en direct", f"{s['relay']} par relais"]
        lines = [" · ".join(parts)]
        if not self.api.remote:
            lines.append(f"Vu depuis ce PC : serveur CCS injoignable ({st.get('bridge_error', '')}).")
        if st.get("error"):
            lines.append(st["error"])
        return "\n".join(lines)

    def devices(self):
        """[(appareil, est-ce le serveur)] comme la liste du web : pairs, appareils connus du
        serveur pas encore vus, puis machines Ricochet hors du réseau maillé."""
        st = self.st
        all_ = ([(dict(st["self"]), True)] if st.get("self") else []) + \
            [(dict(d), False) for d in st.get("peers") or []]
        seen = {d["name"] for d, _ in all_}
        for n in st.get("nodes") or []:
            if n["name"] not in seen:
                all_.append(({"name": n["name"], "host": n.get("host", ""), "ips": n.get("ips") or [],
                              "online": n.get("online"), "path": "idle" if n.get("online") else "offline"}, False))
        used = set()
        for d, is_self in all_:
            m = match_machine(self.machines, d, is_self, self.here, self.api.remote)
            if m:
                d["machine"] = m
                used.add(m.get("id"))
        for m in self.machines:
            if m.get("id") in used or m.get("local"):
                continue
            all_.append(({"name": m.get("name") or m.get("id"), "host": m.get("id"), "online": m.get("online"),
                          "path": "ricochet" if m.get("online") else "offline", "machine": m,
                          "meshless": True}, False))
        return all_

    def draw(self):
        if self.st is None or self._busy():
            return
        self._clear()
        st = self.st
        self.set_description(self.headline(st))
        items = self.devices()
        if not items:
            self._add(Adw.ActionRow(title="Aucun appareil pour l'instant",
                                    subtitle="Ajoute le premier plus bas."))
            return
        for d, is_self in items:
            self._add(self.device_row(d, is_self))

    def device_row(self, d, is_self):
        st = self.st
        self_label = "Serveur CCS" if self.api.remote else "Cet appareil"
        row = Adw.ExpanderRow(title=d["name"], subtitle=device_subtitle(d, self_label))
        row.set_title_selectable(True)
        row.add_prefix(Gtk.Image(icon_name=ICONS[network.device_kind(d)], pixel_size=24))
        if not d.get("online"):
            row.add_css_class("dim-label")
        row.device = d
        row.measure = row.rename = row.forget = None
        if not is_self and d.get("online") and not d.get("meshless"):
            b = _flat("Mesurer", tooltip="Chemin et latence réels (tailscale ping)")
            b.connect("clicked", lambda btn, n=d["name"]: self.measure(btn, n))
            row.add_suffix(b)
            row.measure = b
        ip = (d.get("ips") or [""])[0]
        if not d.get("meshless"):
            r = Adw.ActionRow(title=ip or "—", subtitle=f"{d['name']}.{st.get('domain', network.BASE_DOMAIN)}",
                              subtitle_selectable=True)
            r.add_prefix(Gtk.Image(icon_name="network-workgroup-symbolic"))
            if ip:
                copy = _flat(None, "edit-copy-symbolic", "Copier l'adresse")
                copy.connect("clicked", lambda _b, v=ip: self.copy(v))
                r.add_suffix(copy)
                row.copy = copy
            row.add_row(r)
        via = d.get("endpoint") if not is_self else ""
        if d.get("path") == "relay" and d.get("relay"):
            via = f"relais {d['relay']}"
        if via:
            row.add_row(Adw.ActionRow(title="Passe par", subtitle=via, subtitle_selectable=True))
        pub = published(d)
        if pub:
            row.add_row(Adw.ActionRow(title="Adresses publiées", subtitle=pub, subtitle_selectable=True,
                                      subtitle_lines=0))
        if d.get("rx") or d.get("tx"):
            row.add_row(Adw.ActionRow(title="Trafic", subtitle=f"↓ {network.human_bytes(d.get('rx'))} · "
                                                                f"↑ {network.human_bytes(d.get('tx'))}"))
        ping = self.pings.get(d["name"])
        if ping:
            row.add_row(Adw.ActionRow(title="Mesure", subtitle=self.ping_text(ping)))
        m = d.get("machine")
        if m:
            row.add_row(self.machine_row(m))
        actions = Gtk.Box(spacing=6, halign=Gtk.Align.END, margin_top=6, margin_bottom=6,
                          margin_start=6, margin_end=6)
        if st.get("server") and not d.get("meshless"):
            b = _flat("Renommer", "document-edit-symbolic")
            b.connect("clicked", lambda _b, dev=d: self.ask_rename(dev))
            actions.append(b)
            row.rename = b
            if not is_self:
                b = _flat("Retirer du réseau", "user-trash-symbolic", css="error")
                b.connect("clicked", lambda _b, dev=d: self.ask_remove(dev))
                actions.append(b)
                row.forget = b
        if actions.get_first_child() is not None:
            row.add_row(actions)
        row.set_expanded(d["name"] in self.expanded)
        return row

    def machine_row(self, m):
        name = m.get("name") or m.get("id")
        r = Adw.ActionRow(title="Calcul", subtitle=machine_subtitle(m), subtitle_lines=3, use_markup=False)
        r.add_prefix(Gtk.Image(icon_name="system-run-symbolic"))
        if self.on_limit is not None:
            spin = Gtk.SpinButton.new_with_range(1, 8, 1)
            spin.set_value(m.get("limit") or 2)
            spin.set_valign(Gtk.Align.CENTER)
            spin.set_tooltip_text(f"Travaux à la fois sur {name}")
            spin.connect("value-changed", lambda s, mid=m.get("id"): self.on_limit(mid, s.get_value_as_int()))
            r.add_suffix(spin)
            r.limit = spin
        return r

    @staticmethod
    def ping_text(res):
        if not res.get("ok"):
            return res.get("error") or "pas de réponse"
        ms = f"{res['ms']:g}".replace(".", ",")
        return f"{ms} ms · {PATHS.get(res['path'], res['path'])} · {res['via']}"

    # ---- actions ---------------------------------------------------------------------------

    def copy(self, text):
        self.get_clipboard().set(text)
        self.toast("Adresse copiée")

    def measure(self, button, name):
        button.set_sensitive(False)
        button.set_label("…")

        def done(res, error):
            button.set_sensitive(True)
            button.set_label("Mesurer")
            res = {"ok": False, "error": str(error)} if error is not None else res
            self.pings[name] = res
            self.toast(f"{name} : {self.ping_text(res)}")
            self.draw()
        self.runner(lambda: self.api.call("network.ping", name=name), done)

    def _present(self, alert):
        self.last_alert = alert
        if self.get_root() is not None:
            alert.present(self)

    def ask_rename(self, d):
        entry = Gtk.Entry(text=d["name"], activates_default=True)
        alert = Adw.AlertDialog(heading=f"Renommer {d['name']}",
                                body="Lettres minuscules, chiffres et tirets.", extra_child=entry)
        alert.add_response("cancel", "Annuler")
        alert.add_response("rename", "Renommer")
        alert.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        alert.set_default_response("rename")
        alert.set_close_response("cancel")
        alert.entry = entry
        alert.connect("response", lambda _a, r: r == "rename" and self.rename(d["name"], entry.get_text()))
        self._present(alert)
        return alert

    def rename(self, name, new):
        new = new.strip()
        if new == name:
            return
        if not network.NAME_RE.match(new):
            self.toast("Nom : lettres minuscules, chiffres et tirets.")
            return
        self._act("network.rename", "Renommé", name=name, new=new)

    def ask_remove(self, d):
        alert = Adw.AlertDialog(heading=f"Retirer {d['name']} du réseau ?",
                                body="L'appareil perd l'accès au réseau. Il faudra l'inscrire à nouveau.")
        alert.add_response("cancel", "Garder")
        alert.add_response("remove", "Retirer")
        alert.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        alert.set_close_response("cancel")
        alert.connect("response", lambda _a, r: r == "remove" and self.remove_device(d["name"]))
        self._present(alert)
        return alert

    def remove_device(self, name):
        self._act("network.remove", "Retiré du réseau", name=name)

    def _act(self, method, ok, **params):
        def done(_r, error):
            self.toast(str(error) if error is not None else ok)
            self.refresh()
        self.runner(lambda: self.api.call(method, **params), done)


class AddDeviceGroup(Adw.PreferencesGroup):
    """« Ajouter un appareil » : PC Linux (lien Ricochet si le jeton opérateur est là, sinon clé
    jetable du réseau maillé), Android et iPhone (appli Tailscale, puis la clé affichée)."""

    def __init__(self, page, toast=None, runner=None, api=None):
        super().__init__(title="Ajouter un appareil")
        self.toast = toast or (lambda _t: None)
        self.runner = runner or _threaded
        self.api = api
        self.server = False
        self.on_change = None            # rechargement des appareils après une inscription

        self.pc = Adw.ExpanderRow(title="PC Linux")
        self.pc.add_prefix(Gtk.Image(icon_name="computer-symbolic"))
        self.ricochet = page.add_pc_widgets()
        for w in self.ricochet:
            self.pc.add_row(w)
        self.k_name = Adw.EntryRow(title="Nom de la machine (facultatif)")
        self.k_go = Gtk.Button(label="Créer la ligne d'inscription", css_classes=["suggested-action"],
                               halign=Gtk.Align.END)
        self.k_go.connect("clicked", lambda _b: self.make_key())
        self.k_hint = Gtk.Label(wrap=True, xalign=0, visible=False, css_classes=["dim-label"],
                                label="Sur le PC, colle dans un terminal (clé valable 15 min, une seule machine) :")
        self.k_line = Gtk.Label(wrap=True, xalign=0, selectable=True, visible=False,
                                css_classes=["monospace"], wrap_mode=Pango.WrapMode.CHAR)
        self.k_copy = Gtk.Button(label="Copier", visible=False)
        self.k_copy.connect("clicked", lambda _b: self.copy(self.k_line.get_text(), "Ligne copiée"))
        buttons = Gtk.Box(spacing=6, halign=Gtk.Align.END)
        buttons.append(self.k_copy)
        buttons.append(self.k_go)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6,
                      margin_start=6, margin_end=6)
        for w in (self.k_hint, self.k_line, buttons):
            box.append(w)
        self.keyed = [self.k_name, box]
        for w in self.keyed:
            self.pc.add_row(w)
        self.add(self.pc)

        self.phones = {}
        for kind, store, how in (
                ("Android", "Play Store", "Écran de connexion → menu ⋮ → « Changer de serveur »"),
                ("iPhone", "App Store", "Réglages de l'appli → Comptes → « Utiliser un serveur personnalisé »")):
            self.phones[kind] = self._phone(kind, store, how)
            self.add(self.phones[kind])
        self.set_ricochet(False)

    def _phone(self, kind, store, how):
        row = Adw.ExpanderRow(title=kind, subtitle="Appli Tailscale, puis la clé affichée")
        row.add_prefix(Gtk.Image(icon_name="phone-apple-iphone-symbolic" if kind == "iPhone" else "phone-symbolic"))
        row.add_row(Adw.ActionRow(title=f"1. Installe l'appli Tailscale ({store})"))
        server = Adw.ActionRow(title=f"2. {how}", subtitle=network.SERVER_URL, subtitle_selectable=True)
        copy = _flat(None, "edit-copy-symbolic", "Copier l'adresse du serveur")
        copy.connect("clicked", lambda _b: self.copy(network.SERVER_URL, "Adresse copiée"))
        server.add_suffix(copy)
        row.add_row(server)
        row.add_row(Adw.ActionRow(title="3. Connecte-toi : une page affiche une clé « hskey-authreq-… »"))
        key = Adw.EntryRow(title="Clé ou lien affiché")
        go = Gtk.Button(label="Valider l'appareil", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        go.connect("clicked", lambda _b: self.register(key))
        key.connect("entry-activated", lambda _e: self.register(key))
        key.add_suffix(go)
        row.add_row(key)
        row.key = key
        return row

    def copy(self, text, said):
        self.get_clipboard().set(text)
        self.toast(said)

    def set_server(self, server):
        """Les clés et l'inscription des téléphones ne se font que sur le serveur du réseau."""
        self.server = bool(server)
        for row in self.phones.values():
            row.set_visible(self.server)
        self._sync()

    def set_ricochet(self, can):
        self.can_ricochet = bool(can)
        self._sync()

    def _sync(self):
        for w in self.ricochet:
            w.set_visible(self.can_ricochet)
        for w in self.keyed:
            w.set_visible(not self.can_ricochet and self.server)
        self.pc.set_visible(self.can_ricochet or self.server)
        self.pc.set_subtitle("Lien Ricochet : SSH, agent de secours et réseau maillé" if self.can_ricochet
                             else "Clé jetable du réseau maillé")
        self.set_description("" if self.server or self.can_ricochet
                             else "Les appareils s'ajoutent depuis le serveur du réseau (le VPS).")

    def make_key(self):
        name = self.k_name.get_text().strip()
        if name and not network.NAME_RE.match(name):
            self.toast("Nom : lettres minuscules, chiffres et tirets.")
            return

        def done(r, error):
            self.k_go.set_sensitive(True)
            if error is not None:
                self.toast(str(error))
                return
            self.k_line.set_text("sudo sh -c '" + " && ".join(r["linux"]) + "'")
            for w in (self.k_hint, self.k_line, self.k_copy):
                w.set_visible(True)
        self.k_go.set_sensitive(False)
        params = {"name": name} if name else {}
        self.runner(lambda: self.api.call("network.key", **params), done)

    def register(self, entry):
        key = entry.get_text().strip()
        if not key:
            self.toast("Colle la clé affichée par l'appli.")
            return

        def done(r, error):
            if error is not None:
                self.toast(str(error))
                return
            entry.set_text("")
            self.toast(f"{r.get('name', 'appareil')} ajouté au réseau")
            if self.on_change:
                self.on_change()
        self.runner(lambda: self.api.call("network.register", key=key), done)


class SoundGroup(Adw.PreferencesGroup):
    """Son partagé : appareils annoncés, flux en cours, « Envoyer le son de … vers … », et
    l'interrupteur du service `ccs-audio` de ce PC (sorties virtuelles des autres appareils)."""

    def __init__(self, toast=None, runner=None, call=None, config=None, service=None):
        super().__init__(title="Son partagé",
                         description="Le son d'un appareil joué sur un autre (RTP/Opus sur le réseau maillé)")
        self.toast = toast or (lambda _t: None)
        self.runner = runner or _threaded
        self.call = call or audio.call
        self.config = config or audio.load_config
        self.service = service or audio.service
        self._rows = []
        self._loading = False
        self._timer = None
        self.devices = []
        cfg = self.config()
        self.switch = Adw.SwitchRow(title="Son partagé sur ce PC",
                                    subtitle="Annonce ce PC ; les autres appareils deviennent des sorties son",
                                    active=cfg["active"])
        self.switch.connect("notify::active", self._toggled)
        self.add(self.switch)
        self.connect("map", lambda _w: self.start_refresh())
        self.connect("unmap", lambda _w: self.stop_refresh())

    def start_refresh(self):
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(REFRESH_S, lambda: (self.refresh(), True)[1])
        self.refresh()

    def stop_refresh(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _toggled(self, row, _pspec):
        on = row.get_active()

        def work():
            cfg = audio.load_config()
            cfg["active"] = on
            audio.save_config(cfg)
            return self.service("on" if on else "off")

        def done(res, error):
            ok, err = res if error is None else (False, str(error))
            self.toast(("Son partagé activé." if on else "Son partagé désactivé.") if ok
                       else f"ccs-audio : {err}")
        self.runner(work, done)

    def refresh(self):
        if self._loading:
            return
        self._loading = True
        self.runner(lambda: self.call("audio.list"), self._loaded)

    def _clear(self):
        for row in self._rows:
            self.remove(row)
        self._rows = []

    def _add(self, row):
        self.add(row)
        self._rows.append(row)

    def _label(self, name):
        return next((d["label"] for d in self.devices if d["device"] == name), name)

    def _loaded(self, listing, error):
        self._loading = False
        self._clear()
        if error is not None:
            self._add(Adw.ActionRow(title="Son partagé indisponible", subtitle=str(error)))
            return
        self.devices = listing.get("devices") or []
        if not self.devices:
            self._add(Adw.ActionRow(title="Aucun appareil annoncé",
                                    subtitle="CCS ouvert sur le téléphone, ou son partagé activé sur un PC"))
            return
        for d in self.devices:
            can = " + ".join(x for x, ok in (("joue", d["play"]), ("capte", d["capture"])) if ok) or "-"
            row = Adw.ActionRow(title=d["label"], subtitle=f"{d['device']} · {d['ip']} · {can}")
            row.add_prefix(Gtk.Image(icon_name="phone-symbolic" if d["system"] in ("android", "ios")
                                     else "audio-speakers-symbolic"))
            self._add(row)
        for st in listing.get("streams") or []:
            row = Adw.ActionRow(title=f"{self._label(st['source'])} → {self._label(st['target'])}",
                                subtitle=f"flux {st['stream']}")
            row.add_prefix(Gtk.Image(icon_name="media-playback-start-symbolic"))
            stop = Gtk.Button(label="Arrêter", valign=Gtk.Align.CENTER)
            stop.add_css_class("destructive-action")
            stop.connect("clicked", lambda _b, sid=st["stream"]: self._act("audio.stop", stream=sid))
            row.add_suffix(stop)
            self._add(row)
        sources = [d for d in self.devices if d["capture"]]
        outputs = [d for d in self.devices if d["play"]]
        if sources and outputs:
            self._add(self._send_row(sources, outputs))

    def _send_row(self, sources, outputs):
        row = Adw.ActionRow(title="Envoyer le son")
        src = Gtk.DropDown.new_from_strings([d["label"] for d in sources])
        dst = Gtk.DropDown.new_from_strings([d["label"] for d in outputs])
        if len(outputs) > 1 and outputs[0]["device"] == sources[0]["device"]:
            dst.set_selected(1)
        for w in (src, dst):
            w.set_valign(Gtk.Align.CENTER)
        go = Gtk.Button(label="Envoyer", valign=Gtk.Align.CENTER)
        go.add_css_class("suggested-action")
        go.connect("clicked", lambda _b: self._act(
            "audio.send", source=sources[src.get_selected()]["device"],
            target=outputs[dst.get_selected()]["device"]))
        row.add_suffix(src)
        row.add_suffix(Gtk.Label(label="→"))
        row.add_suffix(dst)
        row.add_suffix(go)
        return row

    def _act(self, method, **params):
        def done(_res, error):
            if error is not None:
                self.toast(str(error))
            self.refresh()
        self.runner(lambda: self.call(method, **params), done)


class NetworkPage(MachinesPage):
    """Ordre du web : Appareils, (Son partagé), Travaux, Lancer une commande, Ajouter un appareil,
    Secours Ricochet. Les machines du relais vont dans les fiches des appareils."""

    def __init__(self, toast=None, default_cwd=None, runner=None, backend=None, mesh_api=None,
                 sound=None):
        api = mesh_api or MeshApi()
        self.mesh = MeshGroup(toast=toast, runner=runner, api=api, on_limit=self._limit,
                              on_status=self._status)
        self.sound = sound if sound is not None else SoundGroup(toast=toast)
        self._mesh_api, self._runner = api, runner
        super().__init__(toast=toast, runner=runner, backend=backend, default_cwd=default_cwd,
                         first_groups=(self.mesh, self.sound))
        self.set_title("Réseau")

    def _limit(self, machine_id, limite):
        self.save_limit(machine_id, limite)

    def page_groups(self, first_groups=()):
        self.add_device = AddDeviceGroup(self, toast=self.toast, runner=self._runner, api=self._mesh_api)
        self.add_device.on_change = self.mesh.refresh
        self.relay_group.set_title("Secours Ricochet")
        return (*first_groups, self.jobs_group, self.launch_group, self.add_device, self.relay_group)

    def _status(self, st):
        self.add_device.set_server(st.get("server"))

    def settings_loaded(self):
        s = self.settings or {}
        self.add_device.set_ricochet(s.get("relay") and s.get("token_set") and s.get("operator_set"))

    def draw_machines(self, ov):
        super().draw_machines(ov)      # garde la liste des cibles de « Lancer une commande »
        self.mesh.set_machines(self.machines)
