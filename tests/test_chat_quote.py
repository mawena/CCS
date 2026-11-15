"""Répondre en citant un message : format du message envoyé et sa relecture."""

import unittest

from ccs_app import chat_quote as quote

# Cas communs au bureau et au web (tests/test_web_chat.py les rejoue avec node).
SAMPLES = [
    ("claude", "Deux options :\n\n- A\n- B", "Prends la B"),
    ("moi", "Ajoute un bouton", "Finalement non"),
    ("claude", "> déjà une citation\nsuite", "ok"),
    ("claude", "```python\nprint('x')\n```", ""),
    ("moi", "  texte avec espaces  ", "réponse\n\nsur deux paragraphes"),
    ("claude", "ligne\r\nautre", "> la réponse commence par un chevron"),
]


class ComposeTest(unittest.TestCase):
    def test_quote_then_reply(self):
        self.assertEqual(quote.compose("claude", "Deux options :\n\n- A\n- B", "Prends la B"),
                         "> **Claude :**\n> Deux options :\n>\n> - A\n> - B\n\nPrends la B")
        self.assertEqual(quote.compose("moi", "Ajoute un bouton", "Finalement non"),
                         "> **Moi :**\n> Ajoute un bouton\n\nFinalement non")

    def test_quote_alone(self):
        self.assertEqual(quote.compose("claude", "texte"), "> **Claude :**\n> texte")

    def test_nothing_to_quote_gives_the_reply(self):
        self.assertEqual(quote.compose("claude", "   ", "réponse"), "réponse")
        self.assertEqual(quote.compose("inconnu", "texte", "réponse"), "réponse")
        self.assertEqual(quote.compose("claude", None, "réponse"), "réponse")


class SplitTest(unittest.TestCase):
    def test_round_trip(self):
        for author, quoted, body in SAMPLES:
            with self.subTest(quoted=quoted):
                got = quote.split(quote.compose(author, quoted, body))
                self.assertEqual(got, quote.Quote(author, quoted.replace("\r\n", "\n").strip(), body))

    def test_plain_messages_have_no_quote(self):
        for text in ("Bonjour", "> une citation tapée à la main\n\nsuite", "> **Claude :**", "> **Claude :**\n\ntexte",
                     "> **Quelqu'un :**\n> x\n\ny", "", None, 3, "texte\n> **Claude :**\n> x"):
            with self.subTest(text=text):
                self.assertIsNone(quote.split(text))

    def test_reply_right_after_the_quote(self):
        # sans ligne vide entre la citation et la réponse (texte modifié à la main)
        self.assertEqual(quote.split("> **Moi :**\n> a\nb"), quote.Quote("moi", "a", "b"))

    def test_reply_text(self):
        self.assertEqual(quote.reply_text("> **Claude :**\n> long passage\n\nPrends la B"), "Prends la B")
        self.assertEqual(quote.reply_text("sans citation"), "sans citation")
        # citation seule (envoyée avec une image) : rien d'autre à montrer
        self.assertEqual(quote.reply_text("> **Claude :**\n> seul"), "> **Claude :**\n> seul")

    def test_source_text_skips_the_nested_quote(self):
        self.assertEqual(quote.source_text("> **Claude :**\n> A ou B ?\n\nLa B"), "La B")
        self.assertEqual(quote.source_text("> **Claude :**\n> A ou B ?"), "A ou B ?")
        self.assertEqual(quote.source_text("message simple"), "message simple")


class ExcerptTest(unittest.TestCase):
    def test_short_text_is_kept(self):
        self.assertEqual(quote.excerpt("  bonjour \n"), "bonjour")
        self.assertEqual(quote.excerpt(None), "")

    def test_long_text_is_cut_between_words(self):
        text = "mot " * 400
        got = quote.excerpt(text)
        self.assertTrue(got.endswith("mot […]"), got[-20:])
        self.assertLessEqual(len(got), quote.QUOTE_MAX + len(quote.CUT_MARK))

    def test_long_word_is_cut_anyway(self):
        got = quote.excerpt("x" * 5000, 100)
        self.assertEqual(got, "x" * 100 + " […]")

    def test_selection_has_a_larger_limit(self):
        text = "a" * 3000
        self.assertEqual(quote.excerpt(text, quote.SELECTION_MAX), text)
        self.assertNotEqual(quote.excerpt(text), text)

    def test_one_line(self):
        self.assertEqual(quote.one_line("a\n\n  b\tc"), "a b c")
        self.assertEqual(quote.one_line("x" * 200, 10), "x" * 9 + "…")
        self.assertEqual(quote.one_line(None), "")

    def test_labels(self):
        self.assertEqual(quote.SHOWN, {"claude": "Claude", "moi": "Toi"})
        self.assertEqual(set(quote.LABELS), set(quote.SHOWN))


if __name__ == "__main__":
    unittest.main()
