"""Groupe « Téléphone » des Réglages : notifications ntfy sur le téléphone.

    from .phone_group import PhoneGroup
    page.add(PhoneGroup(self.s, self.save, toast=window.toast))

`settings` est le dictionnaire des réglages de la page (le groupe lit et écrit sa section
`phone`, complétée par `phone.config`) ; `save()` est appelé après chaque changement.
Désactivé par défaut : le canal secret n'est créé qu'à la première activation (ou par
« Nouveau canal »). Le lien d'abonnement est copiable ; si le module `qrcode` est
installé, un QR code s'affiche aussi (dessiné sans PIL, depuis la matrice du code).
« Essayer » envoie un vrai message de test (`phone.send_test`, dans un fil) : en test,
`sender` et `run` sont injectés, aucun réseau.
"""

import threading

from gi.repository import Adw, Gdk, GLib, Gtk

from .. import phone

CENTER = Gtk.Align.CENTER
QR_MODULE_PX = 5
QR_BORDER = 3


def qr_texture(text):
    """Texture du QR code de `text`, ou None si `qrcode` est absent ou échoue."""
    try:
        import qrcode
        qr = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(text)
        qr.make(fit=True)
        matrix = qr.get_matrix()
    except Exception:  # noqa: BLE001 — module absent ou version inattendue : lien seul
        return None
    n = len(matrix) + 2 * QR_BORDER
    size = n * QR_MODULE_PX
    rows = []
    for y in range(size):
        my = y // QR_MODULE_PX - QR_BORDER
        line = bytearray()
        for x in range(size):
            mx = x // QR_MODULE_PX - QR_BORDER
            dark = 0 <= my < len(matrix) and 0 <= mx < len(matrix) and matrix[my][mx]
            line += b"\x00\x00\x00" if dark else b"\xff\xff\xff"
        rows.append(bytes(line))
    return Gdk.MemoryTexture.new(size, size, Gdk.MemoryFormat.R8G8B8, GLib.Bytes.new(b"".join(rows)), size * 3)


def qr_available():
    try:
        import qrcode  # noqa: F401
        return True
    except ImportError:
        return False


class PhoneGroup(Adw.PreferencesGroup):
    def __init__(self, settings, save, toast=None, sender=None, run=None):
        super().__init__(title="Téléphone",
                         description="Reçois sur ton téléphone, via ntfy, l'état de tes sessions : "
                                     "le nom du projet et l'état, jamais le contenu des conversations.")
        self.s, self.save, self.toast = settings, save, toast or (lambda _text: None)
        self.sender = sender or phone.send_test     # (réglages) -> (réussi, texte)
        self.run = run or self._in_thread           # exécuteur de l'essai (tests : appel direct)
        self._updating = True
        cfg = phone.config(self.s)
        self.enabled = Adw.SwitchRow(title="Notifications sur le téléphone",
                                     subtitle="Désactivées par défaut. « Ne pas déranger » s'applique aussi.",
                                     active=cfg["enabled"])
        self.enabled.connect("notify::active", self.on_enabled)
        self.add(self.enabled)

        self.server = Adw.EntryRow(title="Serveur ntfy", text=cfg["server"], show_apply_button=True)
        self.server.connect("apply", self.on_server)
        self.add(self.server)

        self.topic = Adw.ActionRow(title="Canal secret", use_markup=False, subtitle_selectable=True)
        self.new_button = Gtk.Button(label="Nouveau canal", valign=CENTER,
                                     tooltip_text="Tire un nouveau canal au hasard (l'ancien cesse de marcher)")
        self.new_button.connect("clicked", lambda *_: self.new_topic())
        self.topic.add_suffix(self.new_button)
        self.add(self.topic)

        self.link = Adw.ActionRow(title="Lien d'abonnement", use_markup=False, subtitle_selectable=True,
                                  subtitle_lines=2)
        self.copy_button = Gtk.Button(icon_name="edit-copy-symbolic", valign=CENTER, css_classes=["flat"],
                                      tooltip_text="Copier le lien")
        self.copy_button.connect("clicked", lambda *_: self.copy_link())
        self.link.add_suffix(self.copy_button)
        self.add(self.link)

        self.qr_row = Adw.ActionRow(title="QR code", subtitle="À scanner avec l'application ntfy")
        self.qr = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=False, margin_top=8, margin_bottom=8)
        self.qr_row.add_suffix(self.qr)
        self.add(self.qr_row)

        self.try_row = Adw.ActionRow(title="Essayer", subtitle="Envoie un message de test au téléphone")
        self.try_button = Gtk.Button(label="Essayer", valign=CENTER)
        self.try_button.connect("clicked", lambda *_: self.try_now())
        self.try_row.add_suffix(self.try_button)
        self.add(self.try_row)

        self.events = {}
        for key, label in phone.EVENTS:
            row = Adw.SwitchRow(title=label, active=cfg["events"][key])
            row.connect("notify::active", self.on_event, key)
            self.events[key] = row
            self.add(row)
        self._updating = False
        self.refresh()

    # ---- état affiché -----------------------------------------------------------

    def cfg(self):
        return phone.config(self.s)

    def refresh(self):
        cfg = self.cfg()
        url = phone.subscribe_url(cfg)
        self.topic.set_subtitle(cfg["topic"] or "Aucun canal : active les notifications ou crée-en un")
        self.link.set_subtitle(url or "—")
        self.copy_button.set_sensitive(url is not None)
        self.try_button.set_sensitive(url is not None)
        texture = qr_texture(url) if url else None
        self.qr.set_paintable(texture)
        self.qr_row.set_visible(texture is not None)
        for row in (self.server, self.topic, self.link, self.try_row, *self.events.values()):
            row.set_sensitive(cfg["enabled"] or row in (self.server, self.topic, self.link, self.try_row))

    def _store(self, **changes):
        """Écrit la section `phone` complète (valeurs par défaut comprises) puis enregistre."""
        cfg = self.cfg()
        cfg.update(changes)
        self.s["phone"] = cfg
        self.save()
        self.refresh()

    # ---- actions ----------------------------------------------------------------

    def on_enabled(self, row, _pspec):
        if self._updating:
            return
        on = row.get_active()
        topic = self.cfg()["topic"]
        self._store(enabled=on, topic=topic or (phone.new_topic() if on else ""))

    def on_server(self, row):
        text = row.get_text().strip()
        if not phone.valid_server(text):
            self.toast("Serveur invalide : une adresse http:// ou https://")
            row.set_text(self.cfg()["server"])
            return
        self._store(server=phone.base_url(text))

    def new_topic(self):
        self._store(topic=phone.new_topic())
        self.toast("Nouveau canal créé : abonne de nouveau ton téléphone")

    def on_event(self, row, _pspec, key):
        if self._updating:
            return
        events = dict(self.cfg()["events"])
        events[key] = row.get_active()
        self._store(events=events)

    def copy_link(self):
        url = phone.subscribe_url(self.cfg())
        if url is None:
            return False
        self.get_clipboard().set(url)
        self.toast("Lien copié")
        return True

    def try_now(self):
        """Message de test dans un fil ; le résultat revient dans un toast."""
        self.try_button.set_sensitive(False)
        settings = {"phone": self.cfg()}

        def work():
            try:
                ok, text = self.sender(settings)
            except Exception as e:  # noqa: BLE001 — jamais d'exception dans le fil
                ok, text = False, f"Envoi impossible ({type(e).__name__})."
            GLib.idle_add(self._tried, ok, text)
        self.run(work)

    def _tried(self, _ok, text):
        self.try_button.set_sensitive(phone.subscribe_url(self.cfg()) is not None)
        self.toast(text)
        return False

    @staticmethod
    def _in_thread(work):
        threading.Thread(target=work, name="ccs-essai-telephone", daemon=True).start()
