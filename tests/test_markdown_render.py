"""Analyse du Markdown (sans GTK)."""

import unittest

from ccs_app.markdown_render import (Code, Heading, Image, Item, ListBlock, Paragraph, Quote,
                                     Rule, Span, Table, parse, to_pango)


class MarkdownRenderTest(unittest.TestCase):
    def test_headings_lists_code(self):
        blocks = parse("# Titre\n\n- a\n- b\n\n3. x\n4. y\n\n```python\nprint(1)\n```\n")
        self.assertEqual(blocks[0], Heading(1, [Span("Titre")]))
        self.assertEqual(blocks[1], ListBlock(False, 1, [Item(None, [Paragraph([Span("a")])]),
                                                         Item(None, [Paragraph([Span("b")])])]))
        self.assertTrue(blocks[2].ordered)
        self.assertEqual(blocks[2].start, 3)
        self.assertEqual(blocks[3], Code("python", "print(1)"))

    def test_nested_quote_rule_image(self):
        blocks = parse("> cité\n\n---\n\n![logo](img/a.png)\n")
        self.assertEqual(blocks, [Quote([Paragraph([Span("cité")])]), Rule(), Image("img/a.png", "logo")])

    def test_task_items(self):
        lst = parse("- [x] fait\n- [ ] à faire\n- normal")[0]
        self.assertEqual([i.checked for i in lst.items], [True, False, None])
        self.assertEqual(lst.items[0].blocks[0].spans[0].text, "fait")

    def test_table_alignment(self):
        t = parse("| a | b | c |\n|:--|:-:|--:|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |\n")[0]
        self.assertIsInstance(t, Table)
        self.assertEqual(t.align, ["left", "center", "right"])
        self.assertEqual([c[0].text for c in t.header], ["a", "b", "c"])
        self.assertEqual(len(t.rows), 2)
        self.assertEqual(t.rows[1][2][0].text, "6")

    def test_inline_marks_and_links(self):
        spans = parse("**g** *i* `c` ~~s~~ [lien](https://x.org)")[0].spans
        marks = {s.text: s for s in spans if s.text.strip()}
        self.assertTrue(marks["g"].bold)
        self.assertTrue(marks["i"].italic)
        self.assertTrue(marks["c"].code)
        self.assertTrue(marks["s"].strike)
        self.assertEqual(marks["lien"].link, "https://x.org")
        self.assertIn('<a href="https://x.org">lien</a>', to_pango(spans))

    def test_pango_escapes_angle_brackets(self):
        self.assertEqual(to_pango(parse("a<b & c>d")[0].spans), "a&lt;b &amp; c&gt;d")
        self.assertEqual(to_pango([Span("<x>", code=True)]), "<tt>&lt;x&gt;</tt>")

    def test_crlf_and_empty_text(self):
        self.assertEqual(parse(""), [])
        self.assertEqual(parse("a\r\n\r\nb\r\n"), [Paragraph([Span("a")]), Paragraph([Span("b")])])


if __name__ == "__main__":
    unittest.main()
