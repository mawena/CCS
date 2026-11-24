"""Page « Machines » des Réglages : les machines du relais Ricochet (charge, mémoire, outils,
places et limite), les commandes lancées dessus (`ccs distant lancer`), le lancement d'une
commande et les réglages du relais. Même contenu que la page web `#/machines`, en plus simple.

Les appels au moteur (`distant`, `distant_jobs`) sont lents (réseau, fichiers) : ils tournent dans
un fil, le résultat revient dans l'interface. Rechargement toutes les 5 s tant que la page est
affichée ; le journal d'un travail, toutes les 3 s tant que sa fenêtre est ouverte.
Le jeton du relais n'est jamais affiché : seulement « jeton enregistré » ou « aucun jeton ».
"""

import os
import shlex

from gi.repository import Adw, GLib, Gtk

from .servers_group import _threaded

REFRESH_S = 5
LOG_S = 3
ACTIVE = ("waiting", "scheduled", "sending", "running")
LABELS = {"waiting": "attente", "scheduled": "programmé", "sending": "envoi", "running": "en cours",
          "done": "fini", "failed": "échec", "stopped": "arrêté"}
WHEN = (("", "Maintenant"), ("nuit", "Cette nuit"), ("heure", "À une heure…"))


class Backend:
    """Les fonctions du moteur (contrat de la phase 21), importées au premier appel."""

    def overview(self):
        from .. import distant
        return distant.machines_overview()

    def jobs(self):
        from .. import distant_jobs
        return distant_jobs.list_jobs()

    def stop(self, job_id):
        from .. import distant_jobs
        return distant_jobs.stop(job_id)

    def log(self, job_id):
        from .. import distant_jobs
        return distant_jobs.read_log(job_id, tail=20000)

    def start(self, command, cwd, machine=None, when=""):
        from .. import distant_jobs
        return distant_jobs.start(command, cwd, machine=machine, when=when)

    def settings(self):
        from .. import distant
        return distant.client_settings()

    def configure(self, relay=None, token=None):
        from .. import distant
        return distant.save_client(relay=relay, token=token)

    def set_limit(self, machine_id, limite):
        from .. import distant
        return distant.set_limit(machine_id, limite)


def duration(seconds):
    s = max(0, round(seconds))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {s % 3600 // 60:02d}"


def _num(x, digits=1):
    return f"{x:.{digits}f}".replace(".", ",")


def machine_subtitle(m):
    if not m.get("online"):
        parts = ["hors ligne"]
    else:
        parts = ["en ligne"]
        if m.get("cores"):
            parts.append(f"charge {_num(m.get('load', 0) / m['cores'], 2)}/cœur ({m['cores']} cœurs)")
        if m.get("mem_total"):
            parts.append(f"mémoire {_num(m.get('mem_used', 0) / 2**30)}/{_num(m['mem_total'] / 2**30, 0)} Go")
    places = f"places {m.get('running', 0)}/{m.get('limit', 2)}"
    if m.get("waiting"):
        places += f", {m['waiting']} en attente"
    parts.append(places)
    parts.append(", ".join(m.get("tools") or []) or "outils pas encore inventoriés")
    return " · ".join(parts)


def job_subtitle(j, now=None):
    now = GLib.get_real_time() / 1e6 if now is None else now
    state = j.get("state", "")
    parts = [LABELS.get(state, state), j.get("machine") or "machine à choisir"]
    if j.get("started"):
        parts.append(duration((j.get("ended") or now) - j["started"]))
    if j.get("code") is not None:
        parts.append(f"code {j['code']}")
    if j.get("cwd"):
        parts.append(j["cwd"].replace(os.path.expanduser("~"), "~", 1))
    line = " · ".join(parts)
    return f"{line}\n{j['why']}" if j.get("why") else line


class MachinesPage(Adw.PreferencesPage):
    def __init__(self, toast=None, runner=None, backend=None, default_cwd=None, first_groups=()):
        super().__init__(title="Machines", icon_name="network-server-symbolic")
        for group in first_groups:       # onglet Réseau : le réseau maillé avant les machines
            self.add(group)
        self.toast = toast or (lambda _t: None)
        self.runner = runner or _threaded
        self.backend = backend or Backend()
        self.machines = []
        self.jobs = []
        self.settings = None
        self.last_alert = None
        self.log_dialog = None
        self._timer = None
        self._loading = False
        self._machine_rows = []
        self._job_rows = []

        self.machines_group = Adw.PreferencesGroup(title="Machines")
        self.jobs_group = Adw.PreferencesGroup(title="Travaux")
        self.add(self.machines_group)
        self.add(self.jobs_group)
        self.add(self._launch_group(default_cwd or os.path.expanduser("~")))
        self.add(self._relay_group())

        self.connect("map", lambda _w: self.start_refresh())
        self.connect("unmap", lambda _w: self.stop_refresh())
        self.refresh()
        self.load_settings()

    # ---- rechargement ----------------------------------------------------------------------

    def start_refresh(self):
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(REFRESH_S, self._tick)
        self.refresh()

    def stop_refresh(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self):
        self.refresh()
        return True

    def refresh(self):
        if self._loading:
            return
        self._loading = True

        def work():
            out = {}
            for key, call in (("overview", self.backend.overview), ("jobs", self.backend.jobs)):
                try:
                    out[key] = call()
                except Exception as e:  # noqa: BLE001 — montrée dans la page
                    out[key] = e
            return out
        self.runner(work, self._loaded)

    def _loaded(self, result, error):
        self._loading = False
        if error is not None:
            result = {"overview": error, "jobs": error}
        self.draw_machines(result["overview"])
        self.draw_jobs(result["jobs"])

    # ---- machines --------------------------------------------------------------------------

    def _editing_limit(self):
        root = self.get_root()
        focus = root.get_focus() if root is not None and hasattr(root, "get_focus") else None
        return focus is not None and focus.is_ancestor(self.machines_group)

    def draw_machines(self, ov):
        if self._editing_limit():
            return                       # pas de redessin sous les doigts
        for row in self._machine_rows:
            self.machines_group.remove(row)
        self._machine_rows = []
        if isinstance(ov, Exception):
            self.machines_group.set_description(str(ov))
            self.machines = []
        else:
            message = ov.get("message") or ("" if ov.get("configured", True)
                                            else "Relais Ricochet non configuré : remplis ses réglages plus bas.")
            self.machines_group.set_description(message)
            self.machines = ov.get("machines") or []
        for m in self.machines:
            name = m.get("name") or m.get("id")
            row = Adw.ActionRow(title=name + (" (ce serveur)" if m.get("local") else ""),
                                subtitle=machine_subtitle(m), use_markup=False, subtitle_lines=3)
            spin = Gtk.SpinButton.new_with_range(1, 8, 1)
            spin.set_value(m.get("limit") or 2)
            spin.set_valign(Gtk.Align.CENTER)
            spin.set_tooltip_text(f"Travaux à la fois sur {name}")
            spin.connect("value-changed", lambda s, mid=m.get("id"): self.save_limit(mid, s.get_value_as_int()))
            row.add_suffix(spin)
            row.limit = spin
            self.machines_group.add(row)
            self._machine_rows.append(row)
        if not self.machines and not isinstance(ov, Exception) and ov.get("configured", True):
            row = Adw.ActionRow(title="Aucune machine sur le relais")
            self.machines_group.add(row)
            self._machine_rows.append(row)
        self._fill_targets()

    def save_limit(self, machine_id, limite):
        def done(_r, error):
            if error is not None:
                self.toast(str(error))
            else:
                self.toast("Limite enregistrée")
            self.refresh()
        self.runner(lambda: self.backend.set_limit(machine_id, limite), done)

    # ---- travaux ---------------------------------------------------------------------------

    def draw_jobs(self, jobs):
        for row in self._job_rows:
            self.jobs_group.remove(row)
        self._job_rows = []
        if isinstance(jobs, Exception):
            self.jobs_group.set_description(str(jobs))
            return
        self.jobs = list(jobs or [])
        active = [j for j in self.jobs if j.get("state") in ACTIVE]
        done = [j for j in self.jobs if j.get("state") not in ACTIVE]
        self.jobs_group.set_description(f"{len(active)} en cours ou à venir, {len(done)} finis"
                                        if self.jobs else "Aucune commande lancée pour l'instant.")
        for j in active + done:
            row = Adw.ActionRow(title=j.get("text", ""), subtitle=job_subtitle(j), use_markup=False,
                                subtitle_lines=3, title_lines=1)
            log = Gtk.Button(label="Journal", valign=Gtk.Align.CENTER, css_classes=["flat"])
            log.connect("clicked", lambda _b, job=j: self.open_log(job))
            row.add_suffix(log)
            if j.get("state") in ACTIVE:
                stop = Gtk.Button(label="Arrêter", valign=Gtk.Align.CENTER, css_classes=["destructive-action"])
                stop.connect("clicked", lambda _b, job=j: self.ask_stop(job))
                row.add_suffix(stop)
                row.stop = stop
            row.log = log
            self.jobs_group.add(row)
            self._job_rows.append(row)

    def ask_stop(self, job):
        running = job.get("state") in ("running", "sending")
        alert = Adw.AlertDialog(heading="Arrêter ce travail ?",
                                body=(f"« {job.get('text')} » sera arrêtée sur {job.get('machine') or 'la machine'}."
                                      if running else f"« {job.get('text')} » ne sera pas lancée."))
        alert.add_response("cancel", "Garder")
        alert.add_response("stop", "Arrêter")
        alert.set_response_appearance("stop", Adw.ResponseAppearance.DESTRUCTIVE)
        alert.set_close_response("cancel")
        alert.connect("response", lambda _d, r: r == "stop" and self.stop_job(job["id"]))
        self.last_alert = alert
        if self.get_root() is not None:
            alert.present(self)

    def stop_job(self, job_id):
        def done(ok, error):
            if error is not None or not ok:
                self.toast(str(error) if error else "Ce travail n'existe plus")
            else:
                self.toast("Travail arrêté")
            self.refresh()
        self.runner(lambda: self.backend.stop(job_id), done)

    def open_log(self, job):
        view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            top_margin=8, bottom_margin=8, left_margin=8, right_margin=8)
        scroller = Gtk.ScrolledWindow(child=view, vexpand=True, hexpand=True)
        toolbar = Adw.ToolbarView(content=scroller)
        toolbar.add_top_bar(Adw.HeaderBar())
        dialog = Adw.Dialog(title=job.get("text", "Journal"), child=toolbar, content_width=640, content_height=480)
        dialog.view = view
        state = {"timer": None, "busy": False}

        def load():
            if state["busy"]:
                return True
            state["busy"] = True

            def done(text, error):
                state["busy"] = False
                view.get_buffer().set_text(str(error) if error else (text or "Pas encore de journal."))
                adj = scroller.get_vadjustment()
                GLib.idle_add(lambda: (adj.set_value(adj.get_upper()), False)[1])
            self.runner(lambda: self.backend.log(job["id"]), done)
            return True

        def closed(_d):
            if state["timer"] is not None:
                GLib.source_remove(state["timer"])
                state["timer"] = None
            if self.log_dialog is dialog:
                self.log_dialog = None
        dialog.connect("closed", closed)
        dialog.timer = state
        self.log_dialog = dialog
        load()
        state["timer"] = GLib.timeout_add_seconds(LOG_S, load)
        if self.get_root() is not None:
            dialog.present(self)
        return dialog

    # ---- lancer une commande ---------------------------------------------------------------

    def _launch_group(self, cwd):
        g = Adw.PreferencesGroup(title="Lancer une commande",
                                 description="Une ligne de shell, lancée dans le dossier sur la machine choisie.")
        self.f_command = Adw.EntryRow(title="Commande")
        self.f_folder = Adw.EntryRow(title="Dossier", text=cwd)
        self.f_target = Adw.ComboRow(title="Machine", model=Gtk.StringList.new(["La moins chargée"]))
        self._targets = [None]
        self.f_when = Adw.ComboRow(title="Quand", model=Gtk.StringList.new([w[1] for w in WHEN]))
        self.f_time = Adw.EntryRow(title="Heure (HH:MM)", visible=False)
        self.f_when.connect("notify::selected", lambda *_a: self.f_time.set_visible(self.f_when.get_selected() == 2))
        self.f_error = Gtk.Label(css_classes=["error"], wrap=True, xalign=0, visible=False)
        self.b_start = Gtk.Button(label="Lancer", css_classes=["suggested-action"], halign=Gtk.Align.END, margin_top=8)
        self.b_start.connect("clicked", lambda _b: self.submit())
        for w in (self.f_command, self.f_folder, self.f_target, self.f_when, self.f_time):
            g.add(w)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=6)
        box.append(self.f_error)
        box.append(self.b_start)
        g.add(box)
        return g

    def _fill_targets(self):
        keep = self._targets[self.f_target.get_selected()] if self.f_target.get_selected() < len(self._targets) else None
        online = [m for m in self.machines if m.get("online")]
        self._targets = [None] + [m.get("id") for m in online]
        self.f_target.set_model(Gtk.StringList.new(["La moins chargée"] + [m.get("name") or m.get("id") for m in online]))
        self.f_target.set_selected(self._targets.index(keep) if keep in self._targets else 0)

    def _say(self, text):
        self.f_error.set_text(text)
        self.f_error.set_visible(bool(text))

    def submit(self):
        self._say("")
        line = self.f_command.get_text().strip()
        cwd = os.path.expanduser(self.f_folder.get_text().strip() or "~")
        if not line:
            return self._say("Écris la commande à lancer.")
        try:
            shlex.split(line)  # vérification seulement : la ligne part entière au shell
        except ValueError as e:
            return self._say(f"Commande mal formée : {e}")
        command = [line]
        if not os.path.isdir(cwd):
            return self._say("Ce dossier n'existe pas.")
        when = WHEN[self.f_when.get_selected()][0]
        if when == "heure":
            when = self.f_time.get_text().strip()
            if not when:
                return self._say("Indique l'heure (HH:MM).")
        machine = self._targets[self.f_target.get_selected()] if self.f_target.get_selected() < len(self._targets) else None

        def done(_id, error):
            self.b_start.set_sensitive(True)
            if error is not None:
                return self._say(str(error))
            self.f_command.set_text("")
            self.toast("Commande programmée" if when else "Commande lancée")
            self.refresh()
        self.b_start.set_sensitive(False)
        self.runner(lambda: self.backend.start(command, cwd, machine=machine, when=when), done)

    # ---- relais ----------------------------------------------------------------------------

    def _relay_group(self):
        g = Adw.PreferencesGroup(title="Relais Ricochet")
        self.f_relay = Adw.EntryRow(title="Adresse du relais")
        self.f_token = Adw.PasswordEntryRow(title="Jeton")
        self.token_row = Adw.ActionRow(title="Jeton", subtitle="…")
        self.b_save = Gtk.Button(label="Enregistrer", valign=Gtk.Align.CENTER)
        self.b_save.connect("clicked", lambda _b: self.save_relay())
        g.set_header_suffix(self.b_save)
        for w in (self.f_relay, self.f_token, self.token_row):
            g.add(w)
        self.relay_group = g
        return g

    def load_settings(self):
        def done(s, error):
            if error is not None:
                self.relay_group.set_description(str(error))
                return
            self.settings = s
            self.f_relay.set_text(s.get("relay") or "")
            self.f_token.set_text("")
            self.token_row.set_subtitle("Jeton enregistré" if s.get("token_set") else "Aucun jeton")
            self.relay_group.set_description(f"Fichier : {s.get('path', '')} · limite par défaut : "
                                             f"{s.get('default_limit', 2)} travaux à la fois par machine")
        self.runner(self.backend.settings, done)

    def save_relay(self):
        relais = self.f_relay.get_text().strip()
        jeton = self.f_token.get_text()
        kwargs = {}
        if relais != ((self.settings or {}).get("relay") or ""):
            kwargs["relay"] = relais
        if jeton:
            kwargs["token"] = jeton
        if not kwargs:
            self.toast("Rien à changer")
            return

        def done(_r, error):
            if error is not None:
                self.relay_group.set_description(str(error))
                return
            self.f_token.set_text("")
            self.toast("Enregistré")
            self.load_settings()
            self.refresh()
        self.runner(lambda: self.backend.configure(**kwargs), done)
