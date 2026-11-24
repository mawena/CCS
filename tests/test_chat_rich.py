"""Chat riche, partie commune : blocs ```ccs et reconnaissance des médias (ccs_app/chat_rich.py)."""
import unittest

from ccs_app import chat_rich


class ChatRichTest(unittest.TestCase):
    def test_parse_block(self):
        self.assertEqual(chat_rich.parse_block('{"type":"choix","options":["A"]}')["type"], "choix")
        for bad in ("{pas du json", '{"type":"inconnu"}', '{"type":"choix","options":[]}', "[1]",
                    '{"type":"carte"}', '{"type":"cartes","items":[]}', None):
            self.assertIsNone(chat_rich.parse_block(bad), bad)

    def test_media_kind(self):
        self.assertEqual([chat_rich.media_kind(s) for s in ("a.MOV", "a.txt", "x.opus#t=3", "s.mp3?x=1", "")],
                         ["video", None, "audio", "audio", None])

    def test_cards_and_links(self):
        spec = {"type": "cartes", "items": [{"titre": "A"}, {"pas": 1}, "x"]}
        self.assertEqual(chat_rich.cards_of(spec), [{"titre": "A"}])
        self.assertEqual(chat_rich.cards_of({"type": "carte", "titre": "B"})[0]["titre"], "B")
        self.assertEqual(chat_rich.web_link("javascript:alert(1)"), "")
        self.assertEqual(chat_rich.web_link(" https://ex.com "), "https://ex.com")
        self.assertEqual(chat_rich.option_of({"label": "Voir"}), {"label": "Voir", "message": "Voir", "lien": ""})


if __name__ == "__main__":
    unittest.main()
