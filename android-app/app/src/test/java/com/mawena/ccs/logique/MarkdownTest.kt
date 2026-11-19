package com.mawena.ccs.logique

import com.mawena.ccs.logique.Markdown.Segment
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MarkdownTest {
    @Test
    fun blocs() {
        val b = Markdown.analyser(
            """
            # Titre

            Un paragraphe
            sur deux lignes.

            - un
            - deux
              - imbriqué
            1. premier
            2. second

            ```kotlin
            val x = 1
            ```

            > cité

            | a | b |
            |---|---|
            | 1 | `x|y` |

            ---
            """.trimIndent(),
        )
        assertEquals(Markdown.Titre(1, listOf(Segment("Titre"))), b[0])
        assertEquals(Markdown.Paragraphe(listOf(Segment("Un paragraphe sur deux lignes."))), b[1])
        val l = b[2] as Markdown.Liste
        assertEquals(listOf(0, 0, 1, 0, 0), l.elements.map { it.niveau })
        assertEquals(listOf("•", "•", "•", "1.", "2."), l.elements.map { it.marque })
        assertEquals(Markdown.Code("kotlin", "val x = 1"), b[3])
        assertEquals(Markdown.Citation(listOf(Markdown.Paragraphe(listOf(Segment("cité"))))), b[4])
        val t = b[5] as Markdown.Tableau
        assertEquals(2, t.entetes.size)
        assertEquals(listOf(Segment("x|y", code = true)), t.lignes[0][1])
        assertEquals(Markdown.Regle, b[6])
    }

    @Test
    fun codeNonFermePendantLaReponse() {
        val b = Markdown.analyser("Voici :\n```py\nprint(1)\nprint(2")
        assertEquals(Markdown.Code("py", "print(1)\nprint(2"), b[1])
    }

    @Test
    fun enLigne() {
        assertEquals(
            listOf(Segment("a "), Segment("gras", gras = true), Segment(" et "), Segment("ital", italique = true), Segment(" "), Segment("code", code = true)),
            Markdown.enLigne("a **gras** et *ital* `code`"),
        )
        assertEquals(listOf(Segment("lien", lien = "https://x.fr/a")), Markdown.enLigne("[lien](https://x.fr/a)"))
        assertEquals(
            listOf(Segment("voir "), Segment("https://x.fr/a_(b)", lien = "https://x.fr/a_(b)"), Segment(".")),
            Markdown.enLigne("voir https://x.fr/a_(b)."),
        )
        assertEquals(listOf(Segment("un_nom_de_variable")), Markdown.enLigne("un_nom_de_variable"))
        assertEquals(listOf(Segment("2 * 3 * 4")), Markdown.enLigne("2 * 3 * 4"))
        assertEquals(listOf(Segment("**pas fermé")), Markdown.enLigne("**pas fermé"))
        assertEquals(listOf(Segment("tout", gras = true, italique = true)), Markdown.enLigne("***tout***"))
        assertEquals(listOf(Segment("barré", barre = true)), Markdown.enLigne("~~barré~~"))
        assertEquals(listOf(Segment("*étoile*")), Markdown.enLigne("\\*étoile\\*"))
    }

    @Test
    fun casesACocher() {
        val l = Markdown.analyser("- [x] fait\n- [ ] à faire")[0] as Markdown.Liste
        assertEquals(listOf(true, false), l.elements.map { it.coche })
    }

    @Test
    fun colorationSimple() {
        val code = "val s = \"x\" // note\nfun f() = 42"
        val j = Coloration.jetons(code, "kotlin")
        fun genre(mot: String) = j.first { code.substring(it.debut, it.fin) == mot }.genre
        assertEquals(Coloration.Genre.MotCle, genre("val"))
        assertEquals(Coloration.Genre.Chaine, genre("\"x\""))
        assertEquals(Coloration.Genre.Commentaire, genre("// note"))
        assertEquals(Coloration.Genre.Nombre, genre("42"))
        assertEquals(Coloration.Genre.MotCle, genre("fun"))
        val sh = Coloration.jetons("echo a#b # vrai", "bash")
        assertEquals(1, sh.count { it.genre == Coloration.Genre.Commentaire })
        val d = Coloration.jetons("@@ -1 +1 @@\n-a\n+b", "diff").map { it.genre }
        assertEquals(listOf(Coloration.Genre.Titre, Coloration.Genre.Retrait, Coloration.Genre.Ajout), d)
        assertTrue(Coloration.jetons("SELECT x FROM t", "sql").count { it.genre == Coloration.Genre.MotCle } == 2)
    }
}
