package com.mawena.ccs.logique

import com.mawena.ccs.logique.ChatRiche.Source
import com.mawena.ccs.logique.Markdown.Segment
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatRicheTest {
    @Test
    fun media() {
        assertEquals(ChatRiche.Media.Audio, ChatRiche.media("son.MP3"))
        assertEquals(ChatRiche.Media.Video, ChatRiche.media("https://x.fr/v.webm?t=3#a"))
        assertNull(ChatRiche.media("image.png"))
        assertNull(ChatRiche.media("sans-extension"))
    }

    @Test
    fun resoudre() {
        assertEquals(Source.Url("https://x.fr/a.png"), ChatRiche.resoudre(" https://x.fr/a.png ", "/p"))
        assertEquals(Source.Chemin("/p/img/a.png"), ChatRiche.resoudre("./img/a.png", "/p"))
        assertEquals(Source.Chemin("/a.png"), ChatRiche.resoudre("../../a.png", "/p"))
        assertEquals(Source.Chemin("/tmp/s.mp3"), ChatRiche.resoudre("/tmp//s.mp3", "/p"))
        assertNull(ChatRiche.resoudre("http://x.fr/a.png", "/p"))
        assertNull(ChatRiche.resoudre("javascript:alert(1)", "/p"))
        assertNull(ChatRiche.resoudre("//hote/a.png", "/p"))
        assertNull(ChatRiche.resoudre("", "/p"))
    }

    @Test
    fun analyserValide() {
        val choix = ChatRiche.analyser("""{"type":"choix","question":"Lequel ?","options":["A",{"label":"B","message":"Prends B"}]}""")
        assertEquals(
            ChatRiche.Choix("Lequel ?", listOf(ChatRiche.Option("A", "A"), ChatRiche.Option("B", "Prends B"))),
            choix,
        )
        val carte = ChatRiche.analyser(
            """{"type":"carte","titre":"T","lien":"javascript:x","prix":12,"actions":[{"label":"Voir","lien":"https://x.fr"},""]}""",
        ) as ChatRiche.Carte
        assertEquals("", carte.lien)
        assertEquals("12", carte.prix)
        assertEquals(listOf(ChatRiche.Option("Voir", "Voir", "https://x.fr")), carte.actions)
        val cartes = ChatRiche.analyser("""{"type":"cartes","items":[{"titre":"a"},{"sans":"titre"}]}""") as ChatRiche.Cartes
        assertEquals(1, cartes.items.size)
        val f = ChatRiche.analyser(
            """{"type":"formulaire","titre":"Résa","champs":[{"nom":"n","label":"Nom"},{"label":"Taille","type":"liste","options":["S","M"]}]}""",
        ) as ChatRiche.Formulaire
        assertEquals("Envoyer", f.envoyer)
        assertEquals("S", ChatRiche.valeurInitiale(f.champs[1]))
        assertEquals("Résa\n- Nom : Ana\n- Taille : M", ChatRiche.messageFormulaire(f, mapOf("n" to " Ana ", "Taille" to "M")))
        assertEquals("Résa", ChatRiche.messageFormulaire(f, emptyMap()))
    }

    @Test
    fun analyserInvalide() {
        assertNull(ChatRiche.analyser("pas du json"))
        assertNull(ChatRiche.analyser("""["choix"]"""))
        assertNull(ChatRiche.analyser("""{"type":"inconnu"}"""))
        assertNull(ChatRiche.analyser("""{"type":"choix","options":[]}"""))
        assertNull(ChatRiche.analyser("""{"type":"formulaire"}"""))
        assertNull(ChatRiche.analyser("""{"type":"carte"}"""))
        assertNull(ChatRiche.analyser("""{"type":"cartes","items":[]}"""))
    }

    @Test
    fun imageMarkdown() {
        assertEquals(
            listOf(Segment("voir "), Segment("chat", lien = "img/c.png", image = true)),
            Markdown.enLigne("voir ![chat](img/c.png)"),
        )
        assertTrue(Markdown.enLigne("![](https://x.fr/a.png)").single().image)
    }
}
