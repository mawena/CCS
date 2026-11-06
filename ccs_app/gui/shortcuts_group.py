"""Groupe « Raccourcis clavier » des Réglages : raccourcis globaux du bureau GNOME.

Une ligne par action de `shortcuts.ACTIONS` : interrupteur (installe / retire le
raccourci personnalisé), raccourci affiché, bouton « Modifier » (capture de la
combinaison : Échap annule, Retour arrière désactive), avertissement de conflit.
Sur un autre bureau, le groupe affiche les commandes à associer à la main.

    from .shortcuts_group import ShortcutsGroup
    page.add(ShortcutsGroup(toast=window.toast))

Tout passe par `ccs_app.shortcuts` (moteur `backend` injectable, vrais réglages par
défaut). Le groupe suit les changements faits ailleurs (Paramètres › Clavier, `ccs
raccourcis`) tant qu'il est affiché.
"""

from gi.repository import Adw, Gdk, GLib, Gtk

from .. import shortcuts

CENTER = Gtk.Align.CENTER


def _names(conflicts):
    return ", ".join(c.describe() for c in conflicts)


class ShortcutRow(Adw.ActionRow):
    """Ligne d'une action : ⚠, raccourci, « Modifier », interrupteur."""

    def __init__(self, group, act):
        super().__init__(use_markup=False)  # noms de raccourcis personnalisés : pas de balisage
        self.group, self.action, self.item = group, act, None
        self._updating = False
        self.set_title(act.label)
        self.warning = Gtk.Image(icon_name="dialog-warning-symbolic", valign=CENTER, visible=False,
                                 css_classes=["warning"])
        self.accel = Gtk.ShortcutLabel(disabled_text="Aucun", valign=CENTER)
        self.accel_text = Gtk.Label(valign=CENTER, visible=False, css_classes=["dim-label"])
        self.edit = Gtk.Button(label="Modifier", valign=CENTER, css_classes=["flat"],
                               tooltip_text="Choisir une autre combinaison")
        self.edit.connect("clicked", lambda *_: group.capture(self))
        self.switch = Gtk.Switch(valign=CENTER)
        self.switch.connect("notify::active", self.on_switch)
        for w in (self.warning, self.accel, self.accel_text, self.edit, self.switch):
            self.add_suffix(w)
        self.set_activatable_widget(self.switch)

    def update(self, item):
        self.item = item
        self._updating = True
        self.switch.set_active(item.installed)
        self._updating = False
        binding = item.binding or ""
        gtk_ok = bool(binding) and Gtk.accelerator_parse(binding)[0]
        self.accel.set_accelerator(binding if gtk_ok else "")
        self.accel.set_visible(gtk_ok or not binding)
        self.accel_text.set_label(item.binding_label)
        self.accel_text.set_visible(bool(binding) and not gtk_ok)  # Above_Tab… : libellé à nous
        self.accel.set_opacity(1.0 if item.installed else 0.55)
        if item.conflicts:
            prefix = "Déjà utilisé" if item.installed else "Raccourci par défaut déjà utilisé"
            text = f"{prefix} : {_names(item.conflicts)}"
            self.set_subtitle(text)
            self.warning.set_tooltip_text(text)
            self.warning.set_visible(True)
        else:
            self.warning.set_visible(False)
            self.set_subtitle(f"Commande à mettre à jour : {item.installed_command}" if item.outdated
                              else item.action.display)

    def on_switch(self, switch, _pspec):
        if not self._updating:
            self.group.toggle(self, switch.get_active())


class CaptureDialog(Adw.Dialog):
    """Attend une combinaison ; `on_done(accel)` reçoit le raccourci (format GTK) ou None
    (Retour arrière : désactiver). Pendant la capture, les raccourcis du bureau sont
    suspendus (comme dans Paramètres) pour que la combinaison arrive jusqu'ici."""

    def __init__(self, act, item, on_done):
        super().__init__(title=act.label, content_width=440)
        self.action, self.on_done = act, on_done
        self._surface = None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18,
                      margin_bottom=24, margin_start=24, margin_end=24)
        box.append(Gtk.Image(icon_name="preferences-desktop-keyboard-shortcuts-symbolic",
                             pixel_size=64, css_classes=["dim-label"]))
        box.append(Gtk.Label(label="Appuie sur la nouvelle combinaison", css_classes=["title-3"],
                             wrap=True, justify=Gtk.Justification.CENTER))
        box.append(Gtk.Label(label="Par exemple Super+Alt+C. Échap pour annuler, Retour arrière "
                                   "pour désactiver le raccourci.",
                             wrap=True, justify=Gtk.Justification.CENTER, css_classes=["dim-label"]))
        if item is not None and item.installed and item.binding:
            current = Gtk.Box(spacing=8, halign=CENTER)
            current.append(Gtk.Label(label="Actuel :", css_classes=["dim-label"]))
            current.append(Gtk.Label(label=item.binding_label))
            box.append(current)
        self.error = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, visible=False,
                               css_classes=["error"])
        box.append(self.error)
        view = Adw.ToolbarView(content=box)
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)
        self.connect("map", self._inhibit)
        self.connect("closed", self._restore)

    def on_key(self, _controller, keyval, _keycode, state):
        mods = Gdk.ModifierType(state) & Gtk.accelerator_get_default_mod_mask()
        if shortcuts.is_modifier_key(Gdk.keyval_name(keyval)):
            return True  # Super, Alt… : on attend la touche
        if not mods and keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if not mods and keyval == Gdk.KEY_BackSpace:
            self._finish(None)
            return True
        # Comme Paramètres : touche en minuscule, Maj gardée si elle changeait la casse.
        lower = Gdk.keyval_to_lower(keyval)
        if lower == Gdk.KEY_ISO_Left_Tab:
            lower = Gdk.KEY_Tab
        if lower != keyval:
            mods |= Gdk.ModifierType.SHIFT_MASK
        if lower == Gdk.KEY_Sys_Req and mods & Gdk.ModifierType.ALT_MASK:
            lower = Gdk.KEY_Print
        try:
            accel = shortcuts.parse_binding(Gtk.accelerator_name(lower, mods)).accel
        except shortcuts.ShortcutError as e:
            self.error.set_label(str(e))
            self.error.set_visible(True)
            return True
        self._finish(accel)
        return True

    def _finish(self, accel):
        self.close()
        self.on_done(accel)

    def _inhibit(self, *_):
        native = self.get_native()
        surface = native.get_surface() if native else None
        if isinstance(surface, Gdk.Toplevel):
            try:
                surface.inhibit_system_shortcuts(None)
                self._surface = surface
            except Exception:  # noqa: BLE001 — sans suspension, la capture marche quand même
                self._surface = None

    def _restore(self, *_):
        if self._surface is not None:
            try:
                self._surface.restore_system_shortcuts()
            except Exception:  # noqa: BLE001
                pass
            self._surface = None


class ShortcutsGroup(Adw.PreferencesGroup):
    """Groupe des Réglages. `backend` : moteur de `shortcuts` (défaut : vrais réglages
    GNOME) ; `toast(texte)` : message passager (défaut : `toast` de la fenêtre)."""

    def __init__(self, backend=None, toast=None):
        super().__init__(title="Raccourcis clavier",
                         description="Raccourcis du bureau GNOME : ils marchent même quand "
                                     "l'application est fermée. Tu les retrouves dans Paramètres "
                                     "› Clavier › Raccourcis personnalisés.")
        self._toast = toast
        self.rows = {}
        self.extra = []
        self.status = None
        self._watch = None
        self._pending = 0
        try:
            self.backend = backend if backend is not None else shortcuts.default_backend()
        except shortcuts.ShortcutError:
            self.backend = None  # status() le redira : « PyGObject (Gio) introuvable »
        self.update_btn = Gtk.Button(label="Mettre à jour les commandes", valign=CENTER, visible=False,
                                     css_classes=["flat"],
                                     tooltip_text="Des raccourcis lancent CCS depuis un autre endroit")
        self.update_btn.connect("clicked", self.on_update_commands)
        self.set_header_suffix(self.update_btn)
        self.connect("map", lambda *_: (self.start_watching(), self.refresh()))
        self.connect("unmap", lambda *_: self.stop_watching())
        self.refresh()

    # ---- état ----------------------------------------------------------------------

    def refresh(self):
        st = self.status = shortcuts.status(self.backend)
        if not st.support.ok:
            self._show_unsupported(st.support.message)
            return
        for row in self.extra:
            self.remove(row)
        self.extra = []
        for item in st.items:
            row = self.rows.get(item.id)
            if row is None:
                row = self.rows[item.id] = ShortcutRow(self, item.action)
                self.add(row)
            row.update(item)
        self.update_btn.set_visible(any(i.outdated for i in st.items))

    def _show_unsupported(self, message):
        for row in [*self.rows.values(), *self.extra]:
            self.remove(row)
        self.rows, self.extra = {}, []
        self.update_btn.set_visible(False)
        self.set_description(message)
        for act in shortcuts.ACTIONS:
            cmd = shortcuts.command_for(act)
            row = Adw.ActionRow(use_markup=False)
            row.set_title(act.label)
            row.set_subtitle(cmd)
            copy = Gtk.Button(icon_name="edit-copy-symbolic", valign=CENTER, css_classes=["flat"],
                              tooltip_text="Copier la commande")
            copy.connect("clicked", lambda b, c=cmd: (b.get_clipboard().set(c), self.toast("Commande copiée")))
            row.add_suffix(copy)
            self.extra.append(row)
            self.add(row)

    # ---- actions -------------------------------------------------------------------

    def toast(self, text):
        show = self._toast or getattr(self.get_root(), "toast", None)
        if show:
            show(text)

    def _apply(self, work):
        """Écrit (fonction de `shortcuts`), relit l'état, annonce le résultat ou l'erreur."""
        try:
            message = work()
        except shortcuts.ShortcutError as e:
            message = str(e)
        self.refresh()
        if message:
            self.toast(message)

    def _announce(self, item):
        if item.conflicts:
            return (f"{item.binding_label} est aussi utilisé par {_names(item.conflicts)} : "
                    f"choisis-en un autre avec « Modifier »")
        return f"{item.label} : {item.binding_label}"

    def toggle(self, row, on):
        act = row.action.id
        if on:
            self._apply(lambda: self._announce(shortcuts.install(act, backend=self.backend)))
        else:
            self._apply(lambda: shortcuts.remove(act, backend=self.backend)
                        and f"Raccourci retiré : {row.action.label}")

    def capture(self, row, present=True):
        """Ouvre le dialogue de capture pour `row` ; le renvoie (présenté ou non)."""
        def done(accel):
            act = row.action.id
            if accel is None:
                self._apply(lambda: shortcuts.remove(act, backend=self.backend)
                            and f"Raccourci retiré : {row.action.label}")
            else:
                self._apply(lambda: self._announce(shortcuts.set_binding(act, accel, backend=self.backend)))
        dialog = CaptureDialog(row.action, row.item, done)
        if present:
            dialog.present(self.get_root())
        return dialog

    def on_update_commands(self, *_):
        self._apply(lambda: (n := len(shortcuts.update_commands(backend=self.backend)))
                    and f"Commande mise à jour pour {n} raccourci{'s' if n > 1 else ''}")

    # ---- changements faits ailleurs --------------------------------------------------

    def start_watching(self):
        if self._watch is None and self.backend is not None:
            try:
                self._watch = self.backend.watch(self._changed)
            except Exception:  # noqa: BLE001 — sans suivi, l'état se relit à chaque affichage
                self._watch = None

    def stop_watching(self):
        if self._watch is not None:
            self.backend.unwatch(self._watch)
            self._watch = None
        if self._pending:
            GLib.source_remove(self._pending)
            self._pending = 0

    def _changed(self):
        if not self._pending:
            self._pending = GLib.idle_add(self._refresh_later)

    def _refresh_later(self):
        self._pending = 0
        self.refresh()
        return GLib.SOURCE_REMOVE
