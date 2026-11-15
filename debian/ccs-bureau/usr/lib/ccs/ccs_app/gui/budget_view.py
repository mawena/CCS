"""Groupe « Budgets par projet » de l'onglet Analyse.

    from .budget_view import BudgetGroup
    box.append(BudgetGroup(toast=window.toast))
    group.refresh()          # recalcule (dans un fil) et réaffiche

Une ligne par projet avec budget : dépensé, budget, pourcentage, part de la semaine et barre
de progression, boutons « Modifier » et « Supprimer ». « Ajouter un budget… » choisit un
dossier puis un montant. Le calcul (journaux de la semaine) passe par `compute`
(défaut `budget.status`) dans un fil ; en test, `run` et `compute` sont injectés.
Un budget ne bloque jamais rien.
"""

import threading

from gi.repository import Adw, GLib, Gtk

from .. import budget, costs
from ..project_accounts import short_path
from .common import empty_state

CENTER = Gtk.Align.CENTER


class BudgetGroup(Adw.PreferencesGroup):
    def __init__(self, toast=None, compute=None, run=None, parent=None):
        super().__init__(title="Budgets par projet",
                         description="Plafond hebdomadaire en équivalent dollars. Alerte à 80 % et à 100 %, "
                                     "rien n'est jamais bloqué.")
        self.toast = toast or (lambda _text: None)
        self.compute = compute or budget.status
        self.run = run or self._in_thread
        self.parent = parent            # fenêtre pour les dialogues (None : la fenêtre de la racine)
        self.rows = {}                  # dossier -> ligne
        self._shown = []
        self._generation = 0
        self.empty = empty_state("folder-symbolic", "Chargement…", compact=True)
        self.add(self.empty)
        add = Adw.ActionRow(title="Ajouter un budget…", activatable=True,
                            subtitle="Choisir un dossier de projet et un montant par semaine")
        add.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        add.connect("activated", lambda *_: self.choose_folder())
        self.add_row = add
        self.add(add)

    # ---- affichage --------------------------------------------------------------

    def refresh(self):
        """Recalcule dans un fil ; la dernière demande gagne."""
        self._generation += 1
        generation = self._generation

        def work():
            try:
                st, error = self.compute(), None
            except Exception as e:  # noqa: BLE001 — journaux illisibles : message dans le groupe
                st, error = None, str(e) or type(e).__name__
            GLib.idle_add(self._show, generation, st, error)
        self.run(work)

    def _show(self, generation, st, error):
        if generation != self._generation:
            return False
        for row in self._shown:
            self.remove(row)
        self._shown, self.rows = [], {}
        if error is not None or not st.rows:
            self.empty.set_title("Calcul impossible" if error else "Aucun budget défini")
            self.empty.set_description(error or "Ajoute un dossier de projet avec un montant par semaine.")
            self.empty.set_icon_name("dialog-error-symbolic" if error else "folder-symbolic")
            self.empty.set_visible(True)
            return False
        self.empty.set_visible(False)
        for r in st.rows:
            row = self._row(r)
            self.rows[r.cwd] = row
            self._shown.append(row)
            self.add(row)
        # La ligne d'ajout reste en dernier.
        self.remove(self.add_row)
        self.add(self.add_row)
        return False

    def _row(self, r):
        row = Adw.ActionRow(title=r.cwd.rsplit("/", 1)[-1] or r.cwd, use_markup=False,
                            subtitle=self.line(r), subtitle_lines=3, tooltip_text=short_path(r.cwd))
        bar = Gtk.ProgressBar(fraction=min(r.pct / 100.0, 1.0), valign=CENTER, width_request=80)
        if r.pct >= 100:
            bar.add_css_class("error")
        elif r.pct >= 80:
            bar.add_css_class("warning")
        row.add_suffix(bar)
        edit = Gtk.Button(icon_name="document-edit-symbolic", valign=CENTER, css_classes=["flat"],
                          tooltip_text="Modifier le budget")
        edit.connect("clicked", lambda *_: self.ask_amount(r.cwd, r.budget))
        delete = Gtk.Button(icon_name="user-trash-symbolic", valign=CENTER, css_classes=["flat"],
                            tooltip_text="Supprimer le budget")
        delete.connect("clicked", lambda *_: self.remove_budget(r.cwd))
        row.add_suffix(edit)
        row.add_suffix(delete)
        row.bar, row.edit_button, row.delete_button = bar, edit, delete
        return row

    @staticmethod
    def line(r):
        return (f"{costs.format_dollars(r.spent)} sur {costs.format_dollars(r.budget)} "
                f"({r.pct:.0f} %) · {r.share * 100:.0f} % de la consommation de la semaine")

    # ---- actions ----------------------------------------------------------------

    def set_amount(self, cwd, amount):
        """Enregistre le budget de `cwd` (montant en dollars) et réaffiche. True si enregistré."""
        try:
            budget.set_budget(cwd, amount)
        except (OSError, ValueError) as e:
            self.toast(f"Budget non enregistré : {e}")
            return False
        self.refresh()
        return True

    def remove_budget(self, cwd):
        try:
            budget.set_budget(cwd, None)
        except OSError as e:
            self.toast(f"Budget non supprimé : {e}")
            return False
        self.toast("Budget supprimé")
        self.refresh()
        return True

    def _window(self):
        root = self.get_root()
        return self.parent or (root if isinstance(root, Gtk.Window) else None)

    def ask_amount(self, cwd, current=None):
        """Dialogue du montant hebdomadaire (en dollars) pour `cwd`."""
        dialog = Adw.AlertDialog(heading="Budget de la semaine",
                                 body=f"{short_path(cwd)}\nMontant en équivalent dollars, par semaine.")
        entry = Gtk.Entry(text=core_fr(current) if current else "", placeholder_text="25", activates_default=True,
                          input_purpose=Gtk.InputPurpose.NUMBER)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Annuler")
        dialog.add_response("ok", "Enregistrer")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")

        def done(_d, response):
            if response != "ok":
                return
            amount = budget.parse_amount(entry.get_text())
            if amount is None:
                self.toast("Montant invalide : un nombre de dollars supérieur à 0")
            else:
                self.set_amount(cwd, amount)
        dialog.connect("response", done)
        dialog.present(self._window())
        return dialog

    def choose_folder(self):
        chooser = Gtk.FileDialog(title="Dossier du projet")

        def done(dlg, result):
            try:
                folder = dlg.select_folder_finish(result)
            except GLib.Error:
                return  # annulé
            if folder is not None and folder.get_path():
                self.ask_amount(folder.get_path(), budget.load().get(folder.get_path()))
        chooser.select_folder(self._window(), None, done)

    @staticmethod
    def _in_thread(work):
        threading.Thread(target=work, name="ccs-budget", daemon=True).start()


def core_fr(value):
    """Montant pré-rempli : « 25 » ou « 12,5 »."""
    return f"{value:g}".replace(".", ",")
