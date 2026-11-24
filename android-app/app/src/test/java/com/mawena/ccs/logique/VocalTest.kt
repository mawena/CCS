package com.mawena.ccs.logique

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class VocalTest {
    @Test
    fun blocsDeCodeRemplaces() {
        val t = Vocal.pourLecture(
            """
            Voici le correctif :

            ```kotlin
            val x = 1 // * # [a](b)
            ```

            C'est tout.
            """.trimIndent(),
        )
        assertEquals("Voici le correctif :\n\nBloc de code.\n\nC'est tout.", t)
    }

    @Test
    fun blocDeCodeNonFermeEtTildes() {
        assertEquals("Début\nBloc de code.", Vocal.pourLecture("Début\n```\nreste du code\n**pas lu**"))
        assertEquals("A\nBloc de code.\nB", Vocal.pourLecture("A\n~~~\n```\n~~~\nB"))
    }

    @Test
    fun titresEtEmphase() {
        assertEquals("Titre.\nDu gras et de l'italique.", Vocal.pourLecture("## Titre\nDu **gras** et de l'*italique*."))
        assertEquals("Fin !", Vocal.pourLecture("# Fin ! #"))
        assertEquals("Souligné et nom_de_variable", Vocal.pourLecture("__Souligné__ et nom_de_variable"))
        assertEquals("barré", Vocal.pourLecture("~~barré~~"))
    }

    @Test
    fun liensEtImages() {
        assertEquals("Voir la doc et le schéma.", Vocal.pourLecture("Voir [la doc](https://exemple.fr/doc) et ![le schéma](a.png)."))
        assertEquals("Adresse : lien", Vocal.pourLecture("Adresse : https://ccs.mawena.cloud/x?y=1"))
        assertEquals("Ici : lien", Vocal.pourLecture("Ici : <https://exemple.fr>"))
        assertEquals("Lance ccs root status", Vocal.pourLecture("Lance `ccs root status`"))
    }

    @Test
    fun listesCitationsTableaux() {
        val t = Vocal.pourLecture(
            """
            - un
            * deux
            1. trois
            - [x] fait
            > cité
            ---
            | a | b |
            |---|:-:|
            | 1 | 2 |
            """.trimIndent(),
        )
        assertEquals("un.\ndeux.\ntrois.\nfait.\ncité\n\na, b.\n1, 2.", t)
    }

    @Test
    fun lignesVidesReduites() {
        assertEquals("A\n\nB", Vocal.pourLecture("\n\nA\n\n\n\n---\n\nB\n\n"))
    }

    @Test
    fun decoupage() {
        assertEquals(listOf("court"), Vocal.decouper("  court  ", 100))
        val texte = "Première phrase. Deuxième phrase un peu plus longue. Troisième."
        val m = Vocal.decouper(texte, 30)
        assertTrue(m.all { it.length <= 30 })
        assertEquals("Première phrase.", m.first())
        assertEquals(texte.replace(" ", ""), m.joinToString("").replace(" ", ""))
        assertEquals(listOf("Paragraphe un", "Paragraphe deux"), Vocal.decouper("Paragraphe un\n\nParagraphe deux", 20))
        assertEquals(listOf("abcde", "fghij", "k"), Vocal.decouper("abcdefghijk", 5))
    }

    @Test
    fun dictee() {
        assertEquals("bonjour", Vocal.ajouterDictee("", " bonjour "))
        assertEquals("Salut bonjour", Vocal.ajouterDictee("Salut", "bonjour"))
        assertEquals("Salut\nbonjour", Vocal.ajouterDictee("Salut\n", "bonjour"))
        assertEquals("Salut", Vocal.ajouterDictee("Salut", "  "))
    }

    @Test
    fun derniereReponseDuTour() {
        val fil = listOf(
            ElementFil.MsgToi("u1", "question"),
            ElementFil.MsgClaude("c1", "je regarde", fini = true),
            ElementFil.Note("n1", "info"),
            ElementFil.MsgClaude("c2", "voilà la réponse", fini = true),
            ElementFil.Usage("t1", "1 000 tokens"),
        )
        assertEquals("c2", Vocal.derniereReponse(fil)?.cle)
        assertNull(Vocal.derniereReponse(fil + ElementFil.MsgToi("u2", "autre")))
        assertNull(Vocal.derniereReponse(emptyList()))
    }
}
