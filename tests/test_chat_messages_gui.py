"""Liste des messages du chat : bulles, cartes d'outils, autorisations, tâches, historique."""

import unittest

from tests.helpers import gui_ready

GTK = gui_ready()

if GTK:
    from gi.repository import GLib, Gtk
    from ccs_app import chat_protocol as proto
    from ccs_app import chat_quote as quote, preview
    from ccs_app.gui.chat_messages import (MessageList, PermissionCard, TodosCard, ToolCard, ToolGroup, edit_info,
                                           open_bubble_menu, selected_text)


def pump(ms=50):
    ctx = GLib.MainContext.default()
    end = GLib.get_monotonic_time() + ms * 1000
    while GLib.get_monotonic_time() < end:
        while ctx.iteration(False):
            pass


def settle(cond, ms=2000):
    """Fait tourner la boucle jusqu'à ce que `cond()` soit vraie (machine chargée : l'allocation
    GTK peut prendre plus que quelques centaines de ms) ; renvoie sa dernière valeur."""
    end = GLib.get_monotonic_time() + ms * 1000
    while not cond() and GLib.get_monotonic_time() < end:
        pump(20)
    return cond()


def descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from descendants(child)
        child = child.get_next_sibling()


def labels(widget):
    return [w.get_label() for w in descendants(widget) if isinstance(w, Gtk.Label)]


@unittest.skipUnless(GTK, "tests graphiques : CCS_GUI_TESTS=1 avec xvfb-run")
class MessageListTest(unittest.TestCase):
    def test_user_bubble_and_streamed_answer(self):
        ml = MessageList()
        ml.add_user("Bonjour", ())
        ml.start_assistant("m1")
        ml.append_delta("m1", "Salut ")
        ml.append_delta("m1", "**toi**")
        ml.finish_assistant("m1", "Salut **toi**")
        pump()
        self.assertEqual(ml.built_count, 2)
        self.assertIn("Bonjour", labels(ml.box))
        self.assertTrue(any("toi" in (t or "") for t in labels(ml.box)))

    def test_text_after_a_tool_goes_in_a_new_bubble(self):
        ml = MessageList()
        ml.finish_assistant("m1", "Avant")
        ml.add_tool(proto.ToolUse("t1", "Bash", {"command": "ls"}))
        ml.append_delta("m1", "Après")
        ml.finish_assistant("m1", "Après")
        self.assertEqual(ml.built_count, 3)

    def test_tool_card_result_and_diff_signal(self):
        seen = []
        ml = MessageList(on_diff=lambda *a: seen.append(a))
        card = ml.add_tool(proto.ToolUse("t1", "Edit", {
            "file_path": "/p/a.py", "old_string": "a\nb\n", "new_string": "a\nc\nd\n"}))
        self.assertTrue(card.running)
        self.assertEqual(card.edit[3:], (2, 1))                  # +2 −1
        self.assertIn("+2", labels(card))
        ml.set_tool_result(proto.ToolResult("t1", "ok", False))
        self.assertFalse(card.running)
        self.assertTrue(card.has_css_class("done"))
        card.main.emit("clicked")
        self.assertEqual(seen, [("/p/a.py", "a\nb\n", "a\nc\nd\n")])

    def test_tool_detail_built_only_when_opened(self):
        """Une carte repliée ne construit ni la commande ni le résultat (mémoire)."""
        ml = MessageList()
        card = ml.add_tool(proto.ToolUse("t1", "Bash", {"command": "ls -la"}))
        ml.set_tool_result(proto.ToolResult("t1", "fichier1\nfichier2", False))
        self.assertIsNone(card.detail.get_first_child())
        self.assertNotIn("fichier1\nfichier2", labels(card))
        card.toggle(True)
        self.assertIn("$ ls -la", labels(card))
        self.assertTrue(any("fichier1" in t for t in labels(card)))

    def test_failed_tool_is_marked_and_opened(self):
        ml = MessageList()
        card = ml.add_tool(proto.ToolUse("t1", "Bash", {"command": "false"}))
        ml.set_tool_result(proto.ToolResult("t1", "boom", True))
        self.assertTrue(card.has_css_class("error"))
        self.assertTrue(card.revealer.get_reveal_child())
        self.assertIn("boom", labels(card))

    def test_write_counts_lines_and_multiedit(self):
        self.assertEqual(edit_info("Write", {"file_path": "/x", "content": "1\n2\n3"})[3:], (3, 0))
        info = edit_info("MultiEdit", {"file_path": "/x", "edits": [
            {"old_string": "a", "new_string": "b"}, {"old_string": "c", "new_string": "c\nd"}]})
        self.assertEqual(info[3:], (2, 1))
        self.assertIsNone(edit_info("Read", {"file_path": "/x"}))

    def test_permission_card_answers(self):
        ml = MessageList()
        got = []
        req = proto.PermissionRequest("r1", "Bash", "Bash", {"command": "touch x"},
                                      [{"type": "addRules"}], "Crée un fichier", None)
        card = ml.add_permission(req, lambda *a: got.append(a))
        self.assertIn("touch x", labels(card))
        self.assertTrue(card.always.get_visible())
        card.reason.set_text("non merci")
        card.deny.emit("clicked")
        card.allow.emit("clicked")                              # déjà répondu : sans effet
        self.assertEqual(got, [("r1", "deny", "non merci")])
        self.assertTrue(card.answered)

    def test_permission_card_without_rules_has_no_always(self):
        card = PermissionCard(proto.PermissionRequest("r", "Bash", "Bash", {"command": "ls"}), lambda *a: None)
        self.assertFalse(card.always.get_visible())

    def test_todos_card_updates(self):
        ml = MessageList()
        ml.set_todos(proto.Todos((("Lire", "completed"), ("Écrire", "in_progress"), ("Tester", "pending"))))
        card = ml._todos
        self.assertIsInstance(card, TodosCard)
        self.assertIn("Tâches · 1/3", labels(card))
        ml.set_todos(proto.Todos((("Lire", "completed"), ("Écrire", "completed"), ("Tester", "completed"))))
        self.assertIs(ml._todos, card)
        self.assertIn("Tâches · 3/3", labels(card))
        self.assertEqual(ml.built_count, 1)

    def test_notice_with_action(self):
        ml = MessageList()
        done = []
        w = ml.add_notice("Erreur", "error", action=("Relancer", lambda: done.append(1)))
        self.assertTrue(w.has_css_class("error"))
        next(b for b in descendants(w) if isinstance(b, Gtk.Button)).emit("clicked")
        self.assertEqual(done, [1])

    def test_busy_row_follows_state(self):
        ml = MessageList()
        ml.set_busy(True, "Claude travaille…")
        self.assertTrue(ml.busy_row.get_visible())
        ml.add_user("x", ())
        self.assertIs(ml.box.get_last_child(), ml.busy_row)     # la roue reste en bas
        ml.set_busy(False)
        self.assertFalse(ml.busy_row.get_visible())

    def test_thousand_messages_build_lazily(self):
        history = []
        for i in range(500):
            history.append(preview.Message(preview.USER, f"question {i}"))
            history.append(preview.Message(preview.ASSISTANT, f"réponse {i}"))
        ml = MessageList()
        ml.load_history(history)
        self.assertEqual(len(history), 1000)
        self.assertLess(ml.built_count, 200)
        self.assertLess(ml.row_count(), 200)
        ml._load_more()                                         # défilement vers le haut
        self.assertEqual(ml.built_count, 100)
        self.assertIs(ml.box.get_last_child(), ml.busy_row)

    def test_history_with_tools_and_new_messages_after(self):
        ml = MessageList()
        ml.load_history([
            preview.Message(preview.USER, "fais ça"),
            preview.Message(preview.TOOL, "", tool=preview.ToolCall("Read", "a.py", "t1", "contenu", False)),
            preview.Message(preview.ASSISTANT, "fait"),
        ])
        self.assertEqual(ml.built_count, 3)
        ml.add_user("merci", ())
        pump()
        texts = labels(ml.box)
        self.assertLess(texts.index("fait"), texts.index("merci"))



@unittest.skipUnless(GTK, "tests graphiques : CCS_GUI_TESTS=1 avec xvfb-run")
class MessageListBehaviourTest(unittest.TestCase):
    def test_busy_row_shows_elapsed_time(self):
        ml = MessageList()
        ml.set_busy(True, "Lecture…")
        ml._busy_started -= 12
        ml._tick_busy()
        self.assertIn("12 s", ml.busy_label.get_label())
        self.assertIn("Lecture…", ml.busy_label.get_label())
        ml.set_busy(True, "Commande…")                  # même tour : le compteur continue
        self.assertIn("12 s", ml.busy_label.get_label())
        ml.set_busy(False)
        ml.set_busy(True, "Lecture…")                   # nouveau tour : repart de zéro
        self.assertNotIn("12 s", ml.busy_label.get_label())

    def test_turn_footer(self):
        ml = MessageList()
        ml.add_turn_footer(42.4, 0.123)
        self.assertIn("42 s", ml._last_footer.get_label())
        self.assertTrue(ml._last_footer.get_label().endswith("0,12 $ éq."))
        ml.add_turn_footer(125, None)
        self.assertIn("2 min 05 s", ml._last_footer.get_label())

    def test_copy_answer(self):
        ml = MessageList()
        copied = []
        ml._to_clipboard = copied.append
        ml.finish_assistant("m1", "Voici **la** réponse")
        bubble = ml._segs["m1"].bubble
        bubble.copy_button.emit("clicked")
        self.assertEqual(copied, ["Voici **la** réponse"])

    def test_long_user_message_is_folded(self):
        ml = MessageList()
        ml.add_user("\n".join(f"ligne {i}" for i in range(60)), ())
        outer = ml._last
        label = next(w for w in descend(outer) if isinstance(w, Gtk.Label) and "ligne 0" in w.get_label())
        more = next(w for w in descend(outer) if isinstance(w, Gtk.Button) and w.get_label() == "Afficher tout")
        self.assertLessEqual(label.get_label().count("\n"), 14)    # texte réellement affiché
        self.assertNotIn("ligne 59", label.get_label())
        more.emit("clicked")
        self.assertIn("ligne 59", label.get_label())
        self.assertEqual(more.get_label(), "Replier")
        more.emit("clicked")
        self.assertNotIn("ligne 59", label.get_label())
        ml.add_user("court", ())
        self.assertFalse(any(isinstance(w, Gtk.Button) for w in descend(ml._last)
                             if isinstance(w, Gtk.Button) and w.get_label() == "Afficher tout"))


def descend(widget):
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        out.append(w)
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    return out

def shown(ml, width=640, height=360):
    win = Gtk.Window(default_width=width, default_height=height)
    win.set_child(ml)
    win.present()
    pump(150)
    return win


def at_bottom(ml, tolerance=4):
    adj = ml.get_vadjustment()
    return adj.get_upper() - adj.get_page_size() - adj.get_value() <= tolerance


def fill(ml, n, prefix="ligne"):
    for i in range(n):
        ml.add_user(f"{prefix} {i}", ())


def widget_visible_in_view(ml, widget):
    """Le widget est alloué et sa fin est dans la zone visible (un widget plus haut que la
    vue ne peut pas y tenir en entier : on regarde son bas, là où arrive le nouveau texte)."""
    if widget.get_height() <= 0:
        return False
    ok, rect = widget.compute_bounds(ml)
    if not ok:
        return False
    top, bottom = rect.get_y(), rect.get_y() + rect.get_height()
    if rect.get_height() > ml.get_height():
        return 0 < bottom <= ml.get_height() + 1
    return top >= -1 and bottom <= ml.get_height() + 1


def head_text(group):
    """Texte de l'en-tête d'un groupe d'actions (replié ou non)."""
    return " | ".join(labels(group.header))


def groups_of(ml):
    return [w for w in descendants(ml.box) if isinstance(w, ToolGroup)]


@unittest.skipUnless(GTK, "tests graphiques : CCS_GUI_TESTS=1 avec xvfb-run")
class ToolGroupTest(unittest.TestCase):
    def three_reads(self, ml, finish=True):
        cards = [ml.add_tool(proto.ToolUse(f"t{i}", "Read", {"file_path": f"/p/f{i}.py"})) for i in range(3)]
        if finish:
            for i in range(3):
                ml.set_tool_result(proto.ToolResult(f"t{i}", "ok", False))
        return cards

    def test_three_actions_make_one_group(self):
        ml = MessageList()
        self.three_reads(ml)
        groups = groups_of(ml)
        self.assertEqual(len(groups), 1)
        self.assertIn("3 actions", head_text(groups[0]))
        self.assertIn("3 lectures", head_text(groups[0]))
        self.assertEqual(ml.row_count(), 1)

    def test_running_header_shows_current_action_and_count(self):
        ml = MessageList()
        self.three_reads(ml, finish=False)
        group = groups_of(ml)[0]
        self.assertTrue(group.running)
        self.assertIn("Lecture de /p/f2.py", head_text(group))
        self.assertIn("3 actions", head_text(group))

    def test_text_between_actions_splits_groups(self):
        ml = MessageList()
        for i in range(2):
            ml.add_tool(proto.ToolUse(f"a{i}", "Bash", {"command": "ls"}))
        ml.finish_assistant("m1", "Je continue")
        for i in range(2):
            ml.add_tool(proto.ToolUse(f"b{i}", "Bash", {"command": "ls"}))
        self.assertEqual(len(groups_of(ml)), 2)
        self.assertEqual(ml.row_count(), 3)

    def test_error_is_visible_in_collapsed_header(self):
        ml = MessageList()
        self.three_reads(ml, finish=False)
        ml.set_tool_result(proto.ToolResult("t0", "ok", False))
        ml.set_tool_result(proto.ToolResult("t1", "boom", True))
        ml.set_tool_result(proto.ToolResult("t2", "ok", False))
        group = groups_of(ml)[0]
        self.assertFalse(group.revealer.get_reveal_child())
        self.assertIn("1 erreur", head_text(group))
        self.assertTrue(group.has_css_class("error"))

    def test_edit_counts_are_added(self):
        ml = MessageList()
        ml.add_tool(proto.ToolUse("e1", "Edit", {"file_path": "/p/a", "old_string": "a\n", "new_string": "a\nb\nc\n"}))
        ml.add_tool(proto.ToolUse("e2", "Write", {"file_path": "/p/b", "content": "1\n2\n3"}))
        ml.add_tool(proto.ToolUse("r", "Read", {"file_path": "/p/c"}))
        for t in ("e1", "e2", "r"):
            ml.set_tool_result(proto.ToolResult(t, "ok", False))
        group = groups_of(ml)[0]
        self.assertIn("2 modifications (+5 −0)", head_text(group))

    def test_permission_never_enters_a_group(self):
        ml = MessageList()
        ml.add_tool(proto.ToolUse("t1", "Bash", {"command": "ls"}))
        ml.add_permission(proto.PermissionRequest("r1", "Bash", "Bash", {"command": "rm x"}), lambda *a: None)
        ml.add_tool(proto.ToolUse("t2", "Bash", {"command": "ls"}))
        self.assertEqual(groups_of(ml), [])
        self.assertEqual(ml.row_count(), 3)

    def test_single_action_stays_a_plain_card(self):
        ml = MessageList()
        card = ml.add_tool(proto.ToolUse("t1", "Bash", {"command": "ls"}))
        self.assertEqual(groups_of(ml), [])
        self.assertIs(card.get_parent(), ml.box)

    def test_subagent_card_stays_alone(self):
        ml = MessageList()
        ml.add_tool(proto.ToolUse("t1", "Read", {"file_path": "/p/a"}))
        task = ml.add_tool(proto.ToolUse("k", "Task", {"description": "Explorer"}))
        ml.add_tool(proto.ToolUse("t2", "Read", {"file_path": "/p/b"}))
        self.assertEqual(groups_of(ml), [])
        self.assertIs(task.get_parent(), ml.box)
        task.append(Gtk.Button(label="Voir le sous-agent"))       # comme chat_tab

    def test_set_tool_result_reaches_a_card_in_a_group(self):
        ml = MessageList()
        cards = self.three_reads(ml, finish=False)
        ml.set_tool_result(proto.ToolResult("t1", "contenu", False))
        self.assertFalse(cards[1].running)
        self.assertTrue(cards[0].running)
        self.assertIs(ml._tools["t1"], cards[1])
        self.assertEqual(cards[1].result_text, "contenu")
        cards[1].toggle(True)                                # détail construit au dépliage
        self.assertIn("contenu", labels(cards[1]))

    def test_group_folds_itself_at_the_end(self):
        ml = MessageList()
        self.three_reads(ml, finish=False)
        group = groups_of(ml)[0]
        group.toggle(True)
        self.assertTrue(group.revealer.get_reveal_child())
        for i in range(3):
            ml.set_tool_result(proto.ToolResult(f"t{i}", "ok", False))
        self.assertFalse(group.running)
        self.assertFalse(group.revealer.get_reveal_child())

    def test_click_unfolds_and_shows_the_cards(self):
        ml = MessageList()
        cards = self.three_reads(ml)
        group = groups_of(ml)[0]
        group.main.emit("clicked")
        self.assertTrue(group.revealer.get_reveal_child())
        self.assertTrue(all(isinstance(c, ToolCard) for c in cards))

    def test_history_actions_are_grouped(self):
        ml = MessageList()
        tool = lambda i: preview.Message(preview.TOOL, "", tool=preview.ToolCall("Read", f"a{i}.py", f"h{i}", "x", False))
        ml.load_history([preview.Message(preview.USER, "go"), tool(1), tool(2), tool(3),
                         preview.Message(preview.ASSISTANT, "fini")])
        groups = groups_of(ml)
        self.assertEqual(len(groups), 1)
        self.assertIn("3 actions", head_text(groups[0]))
        self.assertEqual(ml.built_count, 3)


@unittest.skipUnless(GTK, "tests graphiques : CCS_GUI_TESTS=1 avec xvfb-run")
class MessageListScrollTest(unittest.TestCase):
    def test_content_added_at_bottom_is_followed_and_allocated(self):
        ml = MessageList()
        win = shown(ml)
        fill(ml, 30)
        pump(200)
        self.assertGreater(ml.get_vadjustment().get_upper(), ml.get_height())
        self.assertTrue(at_bottom(ml))
        for kind in range(4):
            ml.add_tool(proto.ToolUse(f"t{kind}", "Bash", {"command": "ls"}))
            ml.add_user("nouveau", ())
            ml.add_notice("info")
            pump(200)
            self.assertTrue(settle(lambda: at_bottom(ml)), f"tour {kind}")
            self.assertTrue(settle(lambda: widget_visible_in_view(ml, ml._last)), f"tour {kind}")
        win.destroy()

    def test_streamed_text_keeps_following(self):
        ml = MessageList()
        win = shown(ml)
        fill(ml, 20)
        pump(200)
        ml.start_assistant("m1")
        for i in range(40):
            ml.append_delta("m1", f"Paragraphe {i} avec un peu de texte pour grandir.\n\n")
            pump(120)
            self.assertTrue(at_bottom(ml), f"delta {i}")
        pump(200)   # le dernier rendu (toutes les 90 ms) se place une image plus tard
        self.assertTrue(widget_visible_in_view(ml, ml._last))
        ml.finish_assistant("m1", "Fin")
        pump(200)
        self.assertTrue(at_bottom(ml))
        win.destroy()

    def test_scrolled_up_user_is_not_moved_and_gets_a_button(self):
        ml = MessageList()
        win = shown(ml)
        fill(ml, 40)
        pump(200)
        adj = ml.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size() - 600)
        pump(100)
        value = adj.get_value()
        self.assertFalse(ml.new_button.get_visible())
        ml.add_user("nouveau message", ())
        ml.add_tool(proto.ToolUse("t1", "Bash", {"command": "ls"}))
        pump(300)
        self.assertAlmostEqual(adj.get_value(), value, delta=1)
        self.assertTrue(ml.new_button.get_visible())
        ml.new_button.emit("clicked")
        pump(300)
        self.assertTrue(at_bottom(ml))
        self.assertFalse(ml.new_button.get_visible())
        win.destroy()

    def test_button_disappears_when_user_scrolls_back_down(self):
        ml = MessageList()
        win = shown(ml)
        fill(ml, 40)
        pump(200)
        adj = ml.get_vadjustment()
        adj.set_value(100)
        pump(100)
        ml.add_user("x", ())
        pump(200)
        self.assertTrue(ml.new_button.get_visible())
        adj.set_value(adj.get_upper() - adj.get_page_size())
        pump(100)
        self.assertFalse(ml.new_button.get_visible())
        win.destroy()

    def test_history_paging_keeps_position(self):
        history = []
        for i in range(300):
            history.append(preview.Message(preview.USER, f"question {i}"))
            history.append(preview.Message(preview.ASSISTANT, f"réponse {i}"))
        ml = MessageList()
        win = shown(ml)
        ml.load_history(history)
        pump(300)
        self.assertTrue(at_bottom(ml))
        adj = ml.get_vadjustment()
        # on remonte jusqu'en haut : un paquet se charge, le texte regardé ne bouge pas
        adj.set_value(adj.get_upper() - adj.get_page_size() - 400)
        pump(100)
        # première ligne visible = point de repère
        def first_visible():
            for w in ml.box:
                ok, r = w.compute_bounds(ml)
                if ok and r.get_y() + r.get_height() > 0 and w is not ml.busy_row:
                    return w, r.get_y()
        before_total = ml.built_count
        adj.set_value(0)
        pump(400)
        self.assertGreater(ml.built_count, before_total)
        # l'ancienne première ligne chargée n'a pas sauté : la valeur n'est pas revenue à 0
        self.assertGreater(adj.get_value(), 100)
        self.assertFalse(ml.new_button.get_visible())
        win.destroy()



@unittest.skipUnless(GTK, "tests graphiques : CCS_GUI_TESTS=1 avec xvfb-run")
class TrimTest(unittest.TestCase):
    """Longue session : le fil garde un nombre borné de lignes construites."""

    def fill(self, ml, n):
        for i in range(n):
            ml.add_tool(proto.ToolUse(f"t{i}", "Bash", {"command": f"echo {i}"}, None))
            ml.set_tool_result(proto.ToolResult(f"t{i}", "ok", False, None))
            ml.finish_assistant(f"m{i}", f"réponse {i}")

    def test_old_rows_dropped_and_references_released(self):
        from ccs_app.gui import chat_messages as cm
        asked = []
        ml = MessageList(on_older=lambda: asked.append(1))
        self.fill(ml, cm.LIVE_MAX)                    # 2 lignes par tour : au-delà du plafond
        self.assertGreater(ml.row_count(), cm.LIVE_MAX)
        dropped = ml.trim()
        self.assertEqual(ml.row_count(), cm.LIVE_KEEP + 1)       # + la ligne « plus anciens »
        self.assertEqual(dropped, 2 * cm.LIVE_MAX - cm.LIVE_KEEP)
        self.assertIn(f"{dropped} éléments plus anciens", " ".join(l or "" for l in labels(ml.box)))
        self.assertTrue(all(v.is_ancestor(ml.box) for v in ml._views))
        self.assertTrue(all(c.is_ancestor(ml.box) for c in ml._tools.values()))
        self.assertTrue(all(s.bubble.is_ancestor(ml.box) for s in ml._segs.values()))
        self.assertNotIn("t0", ml._tools)
        self.assertIn(f"t{cm.LIVE_MAX - 1}", ml._tools)
        ml.older_button.emit("clicked")
        self.assertEqual(asked, [1])
        self.fill(ml, cm.LIVE_MAX)                    # un second élagage cumule le compte
        more = ml.trim()
        self.assertIn(f"{dropped + more} éléments plus anciens", " ".join(l or "" for l in labels(ml.box)))

    def test_nothing_dropped_while_reading_above_or_below_the_cap(self):
        from ccs_app.gui import chat_messages as cm
        ml = MessageList()
        self.fill(ml, 10)
        self.assertEqual(ml.trim(), 0)
        self.fill(ml, cm.LIVE_MAX)
        ml._stick = False                             # on lit plus haut : rien ne bouge
        self.assertEqual(ml.trim(), 0)

    def test_reset_empties_the_thread(self):
        ml = MessageList()
        self.fill(ml, 5)
        ml.reset()
        self.assertEqual(ml.row_count(), 0)
        self.assertEqual((ml._views, ml._tools, ml._segs), ([], {}, {}))
        ml.add_user("encore", ())
        self.assertEqual(ml.row_count(), 1)


@unittest.skipUnless(GTK, "tests graphiques : CCS_GUI_TESTS=1 avec xvfb-run")
class FindTest(unittest.TestCase):
    def filled(self):
        ml = MessageList()
        ml.add_user("Où est l'Éléphant ?", ())
        ml.start_assistant("m1")
        ml.finish_assistant("m1", "L'éléphant est dans le **jardin**.")
        ml.add_user("Merci", ())
        pump()
        return ml

    def test_find_ignores_accents_and_case(self):
        ml = self.filled()
        self.assertEqual(ml.find("ELEPHANT"), 2)
        self.assertEqual(ml.find("jardin"), 1)
        self.assertEqual(ml.find("introuvable"), 0)
        self.assertEqual(ml.find(""), 0)

    def test_find_next_wraps(self):
        ml = self.filled()
        self.assertEqual(ml.find("e"), 3)
        self.assertEqual(ml.find_position(), 1)
        ml.find_next()
        self.assertEqual(ml.find_position(), 2)
        ml.find_next()
        ml.find_next()
        self.assertEqual(ml.find_position(), 1)       # reboucle
        ml.find_prev()
        self.assertEqual(ml.find_position(), 3)
        ml.find_clear()
        self.assertEqual((ml.find_position(), ml.find_count()), (0, 0))

    def test_find_in_tool_card(self):
        ml = MessageList()
        ml.add_user("lance", ())
        ml.add_tool(proto.ToolUse("t1", "Bash", {"command": "pytest -q tests/spécial"}))
        pump()
        self.assertEqual(ml.find("SPECIAL"), 1)
        self.assertEqual(ml.find("bash"), 1)          # le titre de la carte


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(GTK, "tests graphiques : CCS_GUI_TESTS=1 avec xvfb-run")
class ReplyTest(unittest.TestCase):
    """Répondre en citant un message : boutons du fil et bulle qui montre la citation."""

    def setUp(self):
        self.replies = []
        self.ml = MessageList(on_reply=lambda author, text: self.replies.append((author, text)))
        self.win = Gtk.Window()
        self.win.set_child(self.ml)
        self.win.present()
        self.addCleanup(self.win.destroy)

    def test_reply_button_on_an_answer(self):
        self.ml.finish_assistant("m1", "Deux options :\n\n- A\n- B")
        bubble = self.ml._segs["m1"].bubble
        self.assertEqual(bubble.hover_actions.get_opacity(), 0)          # visibles au survol seulement
        bubble.reply_button.emit("clicked")
        self.assertEqual(self.replies, [("claude", "Deux options :\n\n- A\n- B")])

    def test_copy_still_works_next_to_reply(self):
        copied = []
        self.ml._to_clipboard = copied.append
        self.ml.finish_assistant("m1", "Voici **la** réponse")
        self.ml._segs["m1"].bubble.copy_button.emit("clicked")
        self.assertEqual(copied, ["Voici **la** réponse"])

    def test_streamed_answer_quotes_its_latest_text(self):
        self.ml.start_assistant("m1")
        self.ml.append_delta("m1", "Début")
        self.ml.finish_assistant("m1", "Début et fin")
        self.ml._segs["m1"].bubble.reply_button.emit("clicked")
        self.assertEqual(self.replies, [("claude", "Début et fin")])

    def test_long_answer_is_cut(self):
        self.ml.finish_assistant("m1", "mot " * 600)
        self.ml._segs["m1"].bubble.reply_button.emit("clicked")
        self.assertEqual(self.replies, [("claude", quote.excerpt("mot " * 600))])
        self.assertTrue(self.replies[0][1].endswith("mot […]"))

    def test_selected_passage_is_quoted_alone(self):
        self.ml.finish_assistant("m1", "Première phrase. Deuxième phrase.")
        bubble = self.ml._segs["m1"].bubble
        label = next(w for w in descendants(bubble) if isinstance(w, Gtk.Label) and "Deuxième" in w.get_text())
        start = label.get_text().index("Deuxième")
        label.select_region(start, start + len("Deuxième phrase"))
        self.assertEqual(selected_text(bubble), "Deuxième phrase")
        bubble.reply_button.emit("clicked")
        self.assertEqual(self.replies, [("claude", "Deuxième phrase")])

    def test_user_bubble_hover_button_and_menu(self):
        row = self.ml.add_user("Ajoute un bouton", ())
        self.assertEqual(row.reply_hover.get_opacity(), 0)
        row.reply_hover.emit("clicked")
        open_bubble_menu(row, reply=self.ml._reply_from)
        row.reply_button.emit("clicked")
        self.assertEqual(self.replies, [("moi", "Ajoute un bouton")] * 2)
        self.assertFalse(hasattr(row, "rewind_button"))                  # pas de retour arrière ici

    def test_bubble_shows_the_quote_apart(self):
        text = quote.compose("claude", "A ou B ?\nChoisis.", "La B")
        row = self.ml.add_user(text, ())
        shown = labels(row)
        self.assertEqual(shown[:3], ["Claude", "A ou B ?\nChoisis.", "La B"])
        self.assertNotIn("> **Claude :**", " ".join(shown))
        # répondre à cette réponse : on cite « La B », pas ce qu'elle citait
        row.reply_hover.emit("clicked")
        self.assertEqual(self.replies, [("moi", "La B")])

    def test_quote_unfolds_on_click(self):
        row = self.ml.add_user(quote.compose("moi", "\n".join(f"ligne {i}" for i in range(12)), "suite"), ())
        box = next(w for w in descendants(row) if getattr(w, "quote_label", None) is not None)
        self.assertEqual(labels(row)[0], "Toi")
        folded = "ligne 0\nligne 1\nligne 2\nligne 3 …"
        self.assertEqual(box.quote_label.get_label(), folded)            # replié à la main (vraies lignes)
        gesture = next(c for c in box.observe_controllers() if isinstance(c, Gtk.GestureClick))
        gesture.emit("released", 1, 0, 0)
        self.assertEqual(box.quote_label.get_label().count("\n"), 11)
        gesture.emit("released", 1, 0, 0)
        self.assertEqual(box.quote_label.get_label(), folded)

    def test_short_quote_has_nothing_to_unfold(self):
        row = self.ml.add_user(quote.compose("claude", "A ou B ?", "La B"), ())
        box = next(w for w in descendants(row) if getattr(w, "quote_label", None) is not None)
        self.assertEqual(box.quote_label.get_label(), "A ou B ?")
        self.assertFalse([c for c in box.observe_controllers() if isinstance(c, Gtk.GestureClick)])

    def test_history_shows_the_quote_and_can_be_replied_to(self):
        self.ml.load_history([preview.Message(preview.ASSISTANT, "A ou B ?", msg_id="m0"),
                              preview.Message(preview.USER, quote.compose("claude", "A ou B ?", "La B"))])
        rows = list(self.ml._content_rows())
        self.assertEqual(labels(rows[1])[:3], ["Claude", "A ou B ?", "La B"])
        rows[0].reply_button.emit("clicked")
        self.assertEqual(self.replies, [("claude", "A ou B ?")])

    def test_no_reply_without_a_handler(self):
        ml = MessageList()                                               # fil d'un sous-agent
        ml.finish_assistant("m1", "texte")
        row = ml.add_user("demande", ())
        self.assertFalse(hasattr(ml._segs["m1"].bubble, "reply_button"))
        self.assertFalse(hasattr(row, "reply_hover"))
