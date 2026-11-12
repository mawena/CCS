"""Barre du chat, sous la zone de saisie : modèle, effort, ultracode et droits à gauche
(cliquables), contexte utilisé et compte à droite (informatifs)."""

import dataclasses

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GObject, Gtk  # noqa: E402

from .. import chat_options  # noqa: E402
from ..chat_options import ChatOptions  # noqa: E402
from .chat_messages import install_css  # noqa: E402

CONTEXT_CRIT = 90
DANGER_TITLE = "Claude pourra tout faire sans rien demander"
DANGER_TEXT = "À réserver à un dossier jetable ou à une machine isolée."
DANGEROUS = "bypassPermissions"
ULTRACODE_TIP = ("Ultracode : Claude orchestre des workflows pour les grosses tâches (effort très élevé). "
                 "Réglage de session, pas un niveau d'effort.")
ULTRACODE_OFF_TIP = "Ultracode demande un modèle qui accepte l'effort « très élevé »."


def _esc(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _css(css):
    provider = Gtk.CssProvider()
    if hasattr(provider, "load_from_string"):
        provider.load_from_string(css)
    else:
        provider.load_from_data(css.encode())
    return provider


class Picker(Gtk.MenuButton):
    """Bouton compact « Titre  valeur » qui ouvre une liste de choix (certains grisés)."""

    def __init__(self, title, on_pick):
        super().__init__(direction=Gtk.ArrowType.UP, css_classes=["flat", "ccs-barbtn"])
        self.title, self.on_pick = title, on_pick
        self.rows = {}
        self.value = None
        self.text = Gtk.Label()
        self.set_child(self.text)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=4, margin_bottom=4,
                           margin_start=4, margin_end=4)
        self.box.append(Gtk.Label(label=title, xalign=0, css_classes=["ccs-subtle", "caption"], margin_start=8,
                                  margin_bottom=2))
        self.popover = Gtk.Popover(child=self.box)
        self.set_popover(self.popover)

    def set_items(self, items):
        """`items` : [(valeur, libellé, utilisable, infobulle)]."""
        child = self.box.get_first_child().get_next_sibling()
        while child is not None:
            nxt = child.get_next_sibling()
            self.box.remove(child)
            child = nxt
        self.rows = {}
        for value, label, usable, tip in items:
            check = Gtk.Image(icon_name="object-select-symbolic", opacity=0.0)
            line = Gtk.Box(spacing=8)
            line.append(check)
            line.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            button = Gtk.Button(child=line, css_classes=["flat"], sensitive=usable, tooltip_text=tip or None)
            button.check = check
            button.label = label
            button.connect("clicked", lambda _b, v=value: self._pick(v))
            self.rows[value] = button
            self.box.append(button)
        self.refresh()

    def _pick(self, value):
        self.popover.popdown()
        self.on_pick(value)

    def set_value(self, value):
        self.value = value
        self.refresh()

    def refresh(self):
        for value, button in self.rows.items():
            button.check.set_opacity(1.0 if value == self.value else 0.0)
        row = self.rows.get(self.value)
        shown = row.label if row else (str(self.value) if self.value else "")
        self.text.set_markup(f"<span alpha='65%'>{_esc(self.title)}</span>  <b>{_esc(shown)}</b>")


class ChatBar(Gtk.Box):
    """Signal `changed(ChatOptions)` à chaque choix de l'utilisateur (pas à `set_options`)."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (object,))}

    def __init__(self):
        super().__init__(spacing=4, css_classes=["ccs-chat-bar"], margin_start=12, margin_end=12, margin_bottom=8)
        install_css()
        self.options = ChatOptions()
        self._efforts_for = chat_options.efforts_for
        self._ultracode_possible = chat_options.ultracode_possible
        self._models = tuple(chat_options.MODELS)
        self._updating = False
        self.confirm_dangerous = self._ask_confirmation  # remplaçable (essais)

        self.model_picker = Picker("Modèle", self._pick_model)
        self.effort_picker = Picker("Effort", self._pick_effort)
        self.ultracode = Gtk.ToggleButton(label="⚡ Ultracode", css_classes=["flat", "ccs-barbtn"])
        self.ultracode.connect("toggled", self._on_ultracode)
        self.rights_picker = Picker("Droits", self._pick_rights)
        for w in (self.model_picker, self.effort_picker, self.ultracode, self.rights_picker):
            self.append(w)
        self.append(Gtk.Box(hexpand=True))

        self.gauge = Gtk.ProgressBar(valign=Gtk.Align.CENTER, width_request=64,
                                     css_classes=["ccs-gauge", "ccs-gauge-ok"])
        self.context_label = Gtk.Label(css_classes=["ccs-subtle"])
        self.context_box = Gtk.Box(spacing=6, visible=False, tooltip_text="Contexte utilisé de la conversation")
        self.context_box.append(self.context_label)
        self.context_box.append(self.gauge)
        self.dot = Gtk.Box(valign=Gtk.Align.CENTER, visible=False)
        self.account_label = Gtk.Label(css_classes=["ccs-subtle"])
        self.account_gauge = Gtk.ProgressBar(valign=Gtk.Align.CENTER, width_request=40, visible=False,
                                             css_classes=["ccs-gauge", "ccs-gauge-ok"])
        self.account_box = Gtk.Box(spacing=6, visible=False)
        for w in (self.dot, self.account_label, self.account_gauge):
            self.account_box.append(w)
        self.append(self.context_box)
        self.append(self.account_box)
        self.context_level = "ok"
        self.dot_color = None
        self._dot_provider = None
        self._rebuild()

    # ---- données -------------------------------------------------------------------------

    def set_choices(self, models, efforts_for, ultracode_possible):
        """Modèles proposés [(libellé, alias)] (ceux que Claude Code annonce) et règles par
        modèle : niveaux d'effort acceptés, ultracode possible."""
        self._models = tuple(models)
        self._efforts_for = efforts_for
        self._ultracode_possible = ultracode_possible
        self._rebuild()

    def set_options(self, options):
        """Affiche les options (sans signal) : réouverture d'un onglet, changement venu d'ailleurs."""
        self.options = options
        self._rebuild()

    def _rebuild(self):
        self._updating = True
        try:
            o = self.options
            self.model_picker.set_items([(v, label, True, None) for label, v in self._models])
            self.model_picker.set_value(o.model)
            allowed = set(self._efforts_for(o.model))
            self.effort_picker.set_items(
                [(None, "Automatique", True, None)] +
                [(e, chat_options.EFFORT_LABELS.get(e, e), e in allowed,
                  None if e in allowed else "Ce modèle n'accepte pas ce niveau")
                 for e in chat_options.EFFORTS])
            self.effort_picker.set_value(o.effort)
            possible = bool(self._ultracode_possible(o.model))
            self.ultracode.set_sensitive(possible)
            self.ultracode.set_active(bool(o.ultracode) and possible)
            self.ultracode.set_tooltip_text(ULTRACODE_TIP if possible else ULTRACODE_OFF_TIP)
            self.rights_picker.set_items([(v, label, True, None) for label, v in chat_options.RIGHTS])
            self.rights_picker.set_value(o.rights or "manual")
        finally:
            self._updating = False

    # ---- choix de l'utilisateur ----------------------------------------------------------

    def _change(self, **fields):
        options = dataclasses.replace(self.options, **fields)
        # un modèle qui n'accepte pas le niveau ou ultracode les fait retomber
        if options.effort and options.effort not in self._efforts_for(options.model):
            options = dataclasses.replace(options, effort=None)
        if options.ultracode and not self._ultracode_possible(options.model):
            options = dataclasses.replace(options, ultracode=False)
        if options == self.options:
            self._rebuild()
            return
        self.options = options
        self._rebuild()
        self.emit("changed", options)

    def _pick_model(self, value):
        self._change(model=value)

    def _pick_effort(self, value):
        self._change(effort=value)

    def _on_ultracode(self, button):
        if not self._updating:
            self._change(ultracode=button.get_active())

    def _pick_rights(self, value):
        if value == self.options.rights:
            return
        if value == DANGEROUS:
            self.confirm_dangerous(lambda: self._change(rights=value))
        else:
            self._change(rights=value)

    def _ask_confirmation(self, on_yes):
        dialog = Adw.AlertDialog(heading="Tout autoriser ?", body=f"{DANGER_TITLE}. {DANGER_TEXT}")
        dialog.add_response("cancel", "Annuler")
        dialog.add_response("allow", "Tout autoriser")
        dialog.set_response_appearance("allow", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, r: on_yes() if r == "allow" else self._rebuild())
        dialog.present(self.get_root())

    # ---- informations --------------------------------------------------------------------

    def set_context(self, percent, threshold_pct=None):
        """Contexte utilisé : vert, orange au-delà du seuil de l'alerte de contexte lourd,
        rouge à partir de 90 %."""
        percent = max(0, min(100, int(percent)))
        level = "ok"
        if percent >= CONTEXT_CRIT:
            level = "crit"
        elif threshold_pct is not None and percent >= threshold_pct:
            level = "warn"
        self.context_level = level
        for name in ("ok", "warn", "crit"):
            self.gauge.remove_css_class(f"ccs-gauge-{name}")
        self.gauge.add_css_class(f"ccs-gauge-{level}")
        self.gauge.set_fraction(percent / 100)
        self.context_label.set_label(f"Contexte {percent} %")
        self.context_box.set_visible(True)

    def set_account(self, name, color, usage=None):
        """Compte sous lequel tourne le chat : pastille de sa couleur, nom, jauge courte
        (`usage` en pour cent, facultatif)."""
        self.account_label.set_label(name or "")
        self.account_box.set_visible(bool(name))
        self.account_box.set_tooltip_text(f"Compte {name}" if name else None)
        self.dot.set_visible(bool(color))
        if color:
            self._paint_dot(color)
        self.account_gauge.set_visible(usage is not None)
        if usage is not None:
            self.account_gauge.set_fraction(max(0, min(100, usage)) / 100)

    def _paint_dot(self, color):
        if Gdk.Display.get_default() is None:
            return
        context = self.dot.get_style_context()
        if self._dot_provider is not None:
            context.remove_provider(self._dot_provider)
        self._dot_provider = _css(
            f"box {{ background-color: {color}; min-width: 10px; min-height: 10px; border-radius: 99px; }}")
        context.add_provider(self._dot_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 3)
        self.dot_color = color
