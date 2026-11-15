"""Dialogue « Bilan de santé » : résultat de doctor.run_checks(), commandes à copier."""

from gi.repository import Adw, Gtk

from .. import doctor
from .common import in_thread

ICONS = {
    doctor.OK: ("emblem-ok-symbolic", "success", "Tout va bien"),
    doctor.AVERTISSEMENT: ("dialog-warning-symbolic", "warning", "Avertissement"),
    doctor.ERREUR: ("dialog-error-symbolic", "error", "Erreur"),
}


def plain_row(title, subtitle=""):
    """Ligne sans balisage Pango : « && », « < »… s'affichent tels quels. use_markup doit
    être désactivé avant de poser le texte (sinon GTK tente de l'analyser)."""
    row = Adw.ActionRow(use_markup=False)
    row.set_title(title)
    row.set_subtitle(subtitle)
    return row


class DoctorDialog(Adw.Dialog):
    """Liste des vérifications avec leur état ; « Copier la commande » pour chaque correctif.
    Le bilan tourne hors de l'interface (systemctl, dpkg-query, D-Bus…)."""

    def __init__(self, probes=None):
        super().__init__(title="Bilan de santé", content_width=600, content_height=680)
        self.probes = probes
        self.checks = []
        self.groups = []
        self.running = False

        header = Adw.HeaderBar()
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Relancer le bilan")
        self.refresh_btn.connect("clicked", lambda *_: self.run())
        header.pack_start(self.refresh_btn)
        self.copy_btn = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copier tout le bilan",
                                   sensitive=False)
        self.copy_btn.connect("clicked", self.copy_report)
        header.pack_end(self.copy_btn)

        self.page = Adw.PreferencesPage()
        self.toasts = Adw.ToastOverlay(child=self.page)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        self.set_child(view)
        self.run()

    # ---- bilan -----------------------------------------------------------------------

    def run(self):
        if self.running:
            return
        self.running = True
        self.refresh_btn.set_sensitive(False)
        self.show_waiting()

        def work():
            try:
                return doctor.run_checks(self.probes)
            except Exception as e:  # noqa: BLE001 — affiché plutôt qu'un sablier sans fin
                return e
        in_thread(work, self.loaded)

    def loaded(self, result):
        self.running = False
        self.refresh_btn.set_sensitive(True)
        if isinstance(result, Exception):
            self.clear()
            self.add_group(Adw.PreferencesGroup(title="Bilan impossible", description=str(result)))
            return
        self.checks = result
        self.copy_btn.set_sensitive(bool(result))
        self.render()

    # ---- rendu -------------------------------------------------------------------------

    def clear(self):
        for g in self.groups:
            self.page.remove(g)
        self.groups = []

    def add_group(self, group):
        self.page.add(group)
        self.groups.append(group)
        return group

    def show_waiting(self):
        self.clear()
        group = Adw.PreferencesGroup()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER,
                      margin_top=48)
        spinner = Adw.Spinner() if hasattr(Adw, "Spinner") else Gtk.Spinner(spinning=True)
        spinner.set_size_request(32, 32)
        box.append(spinner)
        box.append(Gtk.Label(label="Vérification en cours…", css_classes=["dim-label"]))
        group.add(box)
        self.add_group(group)

    def render(self):
        self.clear()
        worst = max((c.statut for c in self.checks), key=doctor.STATUTS.index, default=doctor.OK)
        icon, css, _ = ICONS[worst]
        summary = self.add_group(Adw.PreferencesGroup())
        row = plain_row(doctor.summary(self.checks),
                        "Les commandes proposées ne sont jamais lancées : copie-les dans un terminal."
                        if any(c.commande for c in self.checks) else "")
        row.add_prefix(Gtk.Image(icon_name=icon, css_classes=[css], pixel_size=32))
        summary.add(row)
        group = self.add_group(Adw.PreferencesGroup(title="Vérifications"))
        for c in self.checks:
            group.add(self.row(c))

    def row(self, check):
        icon, css, label = ICONS.get(check.statut, ICONS[doctor.AVERTISSEMENT])
        subtitle = check.detail + (f"\n→ {check.commande}" if check.commande else "")
        row = plain_row(check.nom, subtitle)
        row.set_subtitle_selectable(True)
        image = Gtk.Image(icon_name=icon, css_classes=[css], tooltip_text=label)
        image.update_property([Gtk.AccessibleProperty.LABEL], [label])
        row.add_prefix(image)
        if check.commande:
            btn = Gtk.Button(label="Copier la commande", valign=Gtk.Align.CENTER, css_classes=["flat"],
                             tooltip_text=check.commande)
            btn.connect("clicked", lambda *_, cmd=check.commande: self.copy(cmd, "Commande copiée"))
            row.add_suffix(btn)
        return row

    # ---- presse-papiers ----------------------------------------------------------------

    def copy(self, text, message):
        self.get_clipboard().set(text)
        self.toasts.add_toast(Adw.Toast(title=message, timeout=2))

    def copy_report(self, *_):
        if self.checks:
            self.copy(doctor.format_text(self.checks, couleur=False), "Bilan copié")


def show_doctor(parent, probes=None):
    """Ouvre le bilan de santé au-dessus de `parent` (fenêtre ou widget) ; renvoie le dialogue."""
    dialog = DoctorDialog(probes)
    dialog.present(parent)
    return dialog
