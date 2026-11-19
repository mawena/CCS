package com.mawena.ccs.logique

import com.mawena.ccs.logique.Veilleur.Action
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.addJsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class VeilleurTest {
    private fun etat(e: String) = EvChat.Etat(e)
    private fun bash(id: String, cmd: String) = EvChat.Autorisation(id, "Bash", "", buildJsonObject { put("command", cmd) }, "", null)
    private fun question(id: String, q: String) = EvChat.Autorisation(
        id, "AskUserQuestion", "", buildJsonObject { putJsonArray("questions") { addJsonObject { put("question", q) } } }, "", null,
    )
    private val min = 60_000L

    @Test
    fun finDeTourApresTravail() {
        val v = Veilleur()
        v.connaitre("c1", "idle")
        assertEquals(listOf(Action.RetirerFin("c1")), v.recevoir("c1", etat("busy"), 0))
        v.recevoir("c1", EvChat.Texte("m1", "Voilà, **c'est fait**.", null), 0)
        val a = v.recevoir("c1", etat("idle"), 0)
        assertEquals(listOf(Action.FinTour("c1", "Voilà, c'est fait.", false)), a)
        // repos après repos (démarrage) : rien
        assertTrue(v.recevoir("c1", etat("idle"), 0).isEmpty())
        assertTrue(Veilleur().recevoir("c2", etat("idle"), 0).none { it is Action.FinTour })
    }

    @Test
    fun interruptionEtChatAfficheSansNotification() {
        val v = Veilleur()
        v.connaitre("c1", "idle")
        v.recevoir("c1", etat("busy"), 0)
        v.recevoir("c1", EvChat.Tour(false, "error", 0.0, "", false, true), 0)
        assertTrue(v.recevoir("c1", etat("idle"), 0).none { it is Action.FinTour })

        assertEquals(listOf(Action.RetirerTout("c1")), v.afficher("c1"))
        v.recevoir("c1", etat("busy"), 0)
        assertTrue(v.recevoir("c1", bash("r1", "ls")).none { it is Action.Attente })
        assertTrue(v.recevoir("c1", etat("idle"), 0).none { it is Action.FinTour })
        v.afficher(null)
        v.recevoir("c1", etat("busy"), 0)
        assertTrue(v.recevoir("c1", etat("idle"), 0).any { it is Action.FinTour })
    }

    private fun Veilleur.recevoir(chat: String, ev: EvChat) = recevoir(chat, ev, 0)

    @Test
    fun autorisationQuestionEtReglement() {
        val v = Veilleur()
        v.connaitre("c1", "busy")
        assertEquals(listOf(Action.Attente("c1", "r1", false, "Commande : git push")), v.recevoir("c1", bash("r1", "git push\nsuite"), 0))
        assertEquals(listOf(Action.Attente("c1", "r2", true, "Quel nom ?")), v.recevoir("c1", question("r2", "Quel nom ?"), 0))
        assertEquals(listOf(Action.RetirerAttente("c1", "r1")), v.recevoir("c1", EvChat.Reglee("r1", "allow"), 0))
        assertEquals(listOf("r2"), v.attentes("c1"))
        // le tour finit : les attentes restantes partent avec la notification de fin
        v.recevoir("c1", etat("permission"), 0)
        val fin = v.recevoir("c1", etat("idle"), 0)
        assertTrue(Action.RetirerAttente("c1", "r2") in fin)
        assertTrue(fin.any { it is Action.FinTour })
        assertTrue(v.attentes("c1").isEmpty())
    }

    @Test
    fun rappelUniqueApresLeSeuil() {
        val v = Veilleur()
        v.connaitre("c1", "busy")
        v.recevoir("c1", bash("r1", "rm x"), 0)
        assertEquals(10 * min, v.prochainRappel(10 * min))
        assertTrue(v.rappels(9 * min, 10 * min).isEmpty())
        assertEquals(listOf(Action.Rappel("c1", "r1", false, "Commande : rm x", 11)), v.rappels(11 * min, 10 * min))
        assertTrue(v.rappels(30 * min, 10 * min).isEmpty())          // une seule fois
        assertNull(v.prochainRappel(10 * min))
        assertTrue(v.rappels(30 * min, null).isEmpty())               // rappel coupé sur le serveur
    }

    @Test
    fun pasDeRappelPourLeChatAfficheNiApresReponse() {
        val v = Veilleur()
        v.recevoir("c1", bash("r1", "a"), 0)
        v.recevoir("c2", bash("r2", "b"), 0)
        v.afficher("c1")
        v.recevoir("c2", EvChat.Reglee("r2", "deny"), 0)
        assertTrue(v.rappels(20 * min, 10 * min).isEmpty())
        v.afficher(null)
        assertTrue(v.rappels(40 * min, 10 * min).isEmpty())           // vue à l'écran : comptée comme rappelée
    }

    @Test
    fun rejeuSilencieuxEtAttenteAncienne() {
        val v = Veilleur()
        val a = v.recevoir("c1", bash("r1", "make"), 0, silencieux = true)
        assertTrue(a.isEmpty())
        assertEquals(listOf("r1"), v.attentes("c1"))
        v.marquerAnciennes(15 * min, 10 * min)                          // service relancé : déjà vieille
        assertTrue(v.rappels(20 * min, 10 * min).isEmpty())
        // réglée pendant le rejeu : la notification éventuelle est retirée
        assertEquals(listOf(Action.RetirerAttente("c1", "r1")), v.recevoir("c1", EvChat.Reglee("r1", "allow"), 0, silencieux = true))
    }

    @Test
    fun chatsFermesEtEtatConnu() {
        val v = Veilleur()
        v.connaitre("c1", "permission")
        v.recevoir("c1", bash("r1", "x"), 0)
        v.connaitre("c2", "idle")
        assertEquals(listOf(Action.RetirerTout("c1")), v.garderSeulement(setOf("c2")))
        assertNull(v.etat("c1"))
        assertTrue(v.attentes("c1").isEmpty())
        v.connaitre("c2", "permission")
        v.recevoir("c2", bash("r2", "y"), 0)
        v.connaitre("c2", "idle")                                       // l'état lu fait foi : plus d'attente
        assertTrue(v.attentes("c2").isEmpty())
    }

    @Test
    fun resumeCourt() {
        assertEquals("Prêt pour la suite.", Veilleur.resumer("  "))
        assertEquals("a b", Veilleur.resumer("# a\n\n`b`"))
        val long = Veilleur.resumer("x".repeat(500))
        assertEquals(300, long.length)
        assertTrue(long.endsWith("…"))
    }
}
