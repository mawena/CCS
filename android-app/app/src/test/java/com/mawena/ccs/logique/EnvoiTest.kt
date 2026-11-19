package com.mawena.ccs.logique

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class EnvoiTest {
    @Test
    fun commandesSlashCommeLeWeb() {
        assertTrue(Envoi.estCommandeSlash("/clear"))
        assertTrue(Envoi.estCommandeSlash("  /compact garde le plan"))
        assertFalse(Envoi.estCommandeSlash("/1 n'est pas une commande"))
        assertFalse(Envoi.estCommandeSlash("lis /etc/hosts"))
        assertFalse(Envoi.estCommandeSlash("//commentaire"))
    }

    @Test
    fun commandeEnvoyeeSeule() {
        val cite = Citation.Cite(Citation.Auteur.Claude, "passage")
        val p = Envoi.preparer("  /clear ", 0, cite, listOf("note shell\n"))
        assertEquals(Envoi.Pret("/clear", "/clear", true), p)         // ni citation ni sortie `!`
        val img = Envoi.preparer("/clear", 1, null, emptyList())
        assertFalse(img.commande)                                       // avec une image : un message
    }

    @Test
    fun messageAvecCitationEtNotes() {
        val cite = Citation.Cite(Citation.Auteur.Moi, "ma question\n\nsuite")
        val p = Envoi.preparer("réponse", 0, cite, listOf("N1\n", "N2\n"))
        assertEquals("> **Moi :**\n> ma question\n>\n> suite\n\nréponse", p.montre)
        assertEquals("> **Moi :**\n> ma question\n>\n> suite\n\nN1\nN2\nréponse", p.envoye)
        assertFalse(p.commande)
    }

    @Test
    fun commandeShell() {
        assertEquals("ls -la", Envoi.commandeShell(" !ls -la ", 0))
        assertNull(Envoi.commandeShell("!", 0))
        assertNull(Envoi.commandeShell("!ls", 1))
        assertNull(Envoi.commandeShell("pas !ls", 0))
        assertEquals("J'ai lancé `ls` dans le dossier du projet (code 0) :\n```\na\n[sortie tronquée]\n```\n\n", Envoi.noteShell("ls", 0, "a", true))
    }

    @Test
    fun completion() {
        val c = listOf(CommandeSlash("clear"), CommandeSlash("compact"), CommandeSlash("context"), CommandeSlash("help"))
        assertEquals(listOf("compact", "context"), Envoi.completer("/co", c).map { it.nom })
        assertEquals(listOf("clear"), Envoi.completer("/lea", c).map { it.nom })
        assertTrue(Envoi.completer("/clear maintenant", c).isEmpty())
        assertTrue(Envoi.completer("bonjour", c).isEmpty())
    }

    @Test
    fun citationAllerRetour() {
        val t = Citation.composer(Citation.Auteur.Claude, "ligne 1\nligne 2", "ma réponse")
        val d = Citation.decouper(t)!!
        assertEquals(Citation.Auteur.Claude, d.auteur)
        assertEquals("ligne 1\nligne 2", d.texte)
        assertEquals("ma réponse", d.corps)
        assertEquals("ma réponse", Citation.texteSource(t))
        assertNull(Citation.decouper("> une citation ordinaire"))
        val long = "mot ".repeat(400)
        assertTrue(Citation.extrait(long).endsWith(Citation.COUPE))
        assertTrue(Citation.extrait(long).length <= Citation.MAX + Citation.COUPE.length)
        assertEquals("a b c", Citation.uneLigne("a\n  b\tc"))
    }

    @Test
    fun recherche() {
        assertEquals("ecole", Recherche.plier("École"))
        assertEquals(listOf(0, 2), Recherche.trouver(listOf("Créé hier", "rien", "CREE"), "cree"))
        assertEquals(0, Recherche.pas(2, 3, 1))
        assertEquals(2, Recherche.pas(0, 3, -1))
        assertEquals(-1, Recherche.pas(0, 0, 1))
    }

    @Test
    fun etiquettes() {
        assertEquals(listOf("important", "à relire"), Etiquettes.lire(" important , à   relire, Important,, "))
        val m = mapOf(
            "b" to EntreeEtiquettes(listOf("Zèbre", "important"), ts = 2.0),
            "a" to EntreeEtiquettes(listOf("Important"), ts = 1.0),
        )
        val g = Etiquettes.parEtiquette(m)
        assertEquals(listOf("Important", "Zèbre"), g.map { it.first })
        assertEquals(listOf("a", "b"), g[0].second.map { it.first })
    }

    @Test
    fun alerteDeContexte() {
        val ev = EvChat.Contexte(60, 120_000, 200_000, false)
        val d = AlerteContexte.decider(ev, true, 100_000, false)
        assertTrue(d.lourd)
        assertEquals(96_000L, d.gain)
        assertNull(AlerteContexte.decider(ev, true, 100_000, true).gain)      // une seule alerte
        assertFalse(AlerteContexte.decider(ev.copy(auto = true), true, 100_000, false).lourd)
        assertFalse(AlerteContexte.decider(ev, false, 100_000, false).lourd)
    }

    @Test
    fun diffParLignes() {
        val d = Diff.parLignes("a\nb\nc\n", "a\nB\nc\nd\n")
        assertEquals(
            listOf(Diff.Genre.Contexte, Diff.Genre.Retrait, Diff.Genre.Ajout, Diff.Genre.Contexte, Diff.Genre.Ajout),
            d.map { it.genre },
        )
        val multi = Diff.deOutil("MultiEdit", Json.parseToJsonElement(
            """{"file_path":"f","edits":[{"old_string":"x","new_string":"y"},{"old_string":"","new_string":"z"}]}""",
        ).jsonObject)!!
        assertEquals(Diff.Genre.Morceau, multi.lignes[2].genre)
        assertEquals(2, multi.ajouts)
        assertNull(Diff.deOutil("Read", Json.parseToJsonElement("""{"file_path":"f"}""").jsonObject))
        assertEquals(3, Diff.deOutil("Write", Json.parseToJsonElement("""{"file_path":"f","content":"1\n2\n3\n"}""").jsonObject)!!.ajouts)
    }

    @Test
    fun ciblesDesOutils() {
        fun o(s: String) = Json.parseToJsonElement(s).jsonObject
        assertEquals("ls -la", Outils.cible("Bash", o("""{"command":"ls -la\nautre"}""")))
        assertEquals("TODO dans src", Outils.cible("Grep", o("""{"pattern":"TODO","path":"src"}""")))
        assertEquals("Chercher", Outils.cible("Task", o("""{"description":"Chercher","prompt":"long"}""")))
        assertEquals("valeur", Outils.cible("Inconnu", o("""{"n":1,"x":"valeur"}""")))
        assertEquals("Commande", Outils.libelle("Bash"))
        assertEquals("mcp__x", Outils.libelle("mcp__x"))
    }
}
