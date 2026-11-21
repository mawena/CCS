package com.mawena.ccs.logique

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Usage des tours et cache expiré (`ccs_app/token_use.py`, `tests/test_token_use.py`). */
class ConsommationTest {
    private fun ev(json: String): EvChat = EvChat.lire(Json.parseToJsonElement(json).jsonObject)

    // usage de RESULT dans tests/test_token_use.py, tel que le pont l'envoie
    private val usage = """{"input":4,"cache_read":35952,"cache_write":15423,"output":403,"cost_usd":0.0365,
        "model":"claude-opus-5-5","context":27100,"cache_ttl_s":3600}"""

    @Test
    fun formatDesTokens() {
        assertEquals("0", Consommation.jetons(0))
        assertEquals("403", Consommation.jetons(403))
        assertEquals("999", Consommation.jetons(999))
        assertEquals("1 k", Consommation.jetons(1000))
        assertEquals("36 k", Consommation.jetons(35_952))
        assertEquals("12 k", Consommation.jetons(12_345))
        assertEquals("2 k", Consommation.jetons(2500))           // arrondi de Python : demi au pair
        assertEquals("1000 k", Consommation.jetons(999_999))
        assertEquals("1,2 M", Consommation.jetons(1_234_567))
        assertEquals("1,0 M", Consommation.jetons(1_000_000))
        assertEquals("0", Consommation.jetons(-5))
    }

    @Test
    fun resumeCommeLeBureau() {
        val u = UsageTour.lire(Json.parseToJsonElement(usage))!!
        assertEquals("36 k lus · 15 k écrits · 403 produits · 0,04 $", Consommation.resume(u))
        assertEquals("", Consommation.resume(null))
        // coût nul omis, rien de lu omis
        assertEquals("50 écrits · 5 produits", Consommation.resume(UsageTour(entree = 50, produits = 5)))
        assertEquals("1,2 M lus · 0 produits", Consommation.resume(UsageTour(cacheLu = 1_234_567)))
    }

    @Test
    fun lectureDeLUsage() {
        val u = UsageTour.lire(Json.parseToJsonElement(usage))!!
        assertEquals(UsageTour(4, 35952, 15423, 403, 0.0365, 27100, 3600, "claude-opus-5-5"), u)
        assertNull(UsageTour.lire(Json.parseToJsonElement("{}")))
        assertNull(UsageTour.lire(null))
        assertNull(UsageTour.lire(Json.parseToJsonElement("\"x\"")))
    }

    @Test
    fun tourAvecEtSansUsage() {
        val t = ev("""{"type":"TurnResult","ok":true,"subtype":"success","cost_usd":1.5,"text":"","is_limit":false,
            "interrupted":false,"usage":$usage}""") as EvChat.Tour
        assertEquals(403L, t.usage!!.produits)
        assertEquals(27100L, t.usage!!.contexte)
        val vide = ev("""{"type":"TurnResult","ok":true,"subtype":"success","usage":{}}""") as EvChat.Tour
        assertNull(vide.usage)
        assertNull((ev("""{"type":"TurnResult","ok":true}""") as EvChat.Tour).usage)
    }

    @Test
    fun lectureDuCacheExpire() {
        val c = ev("""{"type":"CacheExpired","context":200000,"ttl_s":3600,"rewrite_usd":1.6,"text":"Cache expiré : rien depuis 1 h"}""")
        assertEquals(EvChat.CacheExpire(200_000, 3600, 1.6, "Cache expiré : rien depuis 1 h"), c)
        val sansPrix = ev("""{"type":"CacheExpired","context":30000,"ttl_s":300,"rewrite_usd":null,"text":"x"}""") as EvChat.CacheExpire
        assertNull(sansPrix.reecritureUsd)
    }

    @Test
    fun filLigneDUsageEtCacheExpire() {
        val f = FilChat()
        f.recevoir(1, ev("""{"type":"AssistantText","msg_id":"m1","text":"Fait."}"""))
        f.recevoir(2, ev("""{"type":"TurnResult","ok":true,"subtype":"success","usage":$usage}"""))
        val ligne = f.fil.elements.last() as ElementFil.Usage
        assertEquals("36 k lus · 15 k écrits · 403 produits · 0,04 $", ligne.texte)
        assertEquals(27100L, f.dernierUsage!!.contexte)
        assertNull(f.cacheExpire)

        f.recevoir(3, ev("""{"type":"CacheExpired","context":200000,"ttl_s":3600,"rewrite_usd":1.6,"text":"Cache expiré."}"""))
        val note = f.fil.elements.last() as ElementFil.Note
        assertEquals("Cache expiré.", note.texte)
        assertEquals(ActionNote.CacheExpire, note.action)
        assertEquals(200_000L, f.cacheExpire!!.contexte)
        // message ordinaire : confirmation ; commande `/…` : rien
        assertEquals(200_000L, Consommation.confirmationCache("Et maintenant ?", f.cacheExpire))
        assertNull(Consommation.confirmationCache("/compact", f.cacheExpire))
        assertEquals("Le cache a expiré : ce message relira 200 k tokens au prix fort.", Consommation.texteConfirmation(200_000))

        // un tour fini lève la confirmation ; sans usage, pas de ligne
        val avant = f.fil.taille
        f.recevoir(4, ev("""{"type":"TurnResult","ok":true,"subtype":"success"}"""))
        assertNull(f.cacheExpire)
        assertNull(Consommation.confirmationCache("Et maintenant ?", f.cacheExpire))
        assertEquals(avant, f.fil.taille)
        assertTrue(LigneFil.de(f.fil.elements).isNotEmpty())
    }

    @Test
    fun niveauDuContexte() {
        assertEquals(NiveauContexte.Vert, Consommation.niveau(74_999))
        assertEquals(NiveauContexte.Orange, Consommation.niveau(75_000))
        assertEquals(NiveauContexte.Orange, Consommation.niveau(150_000))
        assertEquals(NiveauContexte.Rouge, Consommation.niveau(150_001))
        assertEquals(NiveauContexte.Orange, Consommation.niveau(60_000, Consommation.seuil(100_000)))
        assertEquals(NiveauContexte.Rouge, Consommation.niveau(110_000, Consommation.seuil(100_000)))
        assertEquals(150_000L, Consommation.seuil(null))
        assertEquals(150_000L, Consommation.seuil(0))
        assertEquals(NiveauContexte.Vert, Consommation.niveau(10_000, 0))
    }
}
