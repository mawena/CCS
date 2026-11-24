package com.mawena.ccs.logique

import com.mawena.ccs.logique.Lecteurs.Action
import com.mawena.ccs.logique.Lecteurs.Commande
import com.mawena.ccs.logique.Lecteurs.Session
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LecteursTest {
    private val spotify = Session(
        paquet = "com.spotify.music", nomAppli = "Spotify", etat = Lecteurs.ETAT_LECTURE,
        actions = Lecteurs.ACTION_LECTURE or Lecteurs.ACTION_PAUSE or Lecteurs.ACTION_SUIVANT or
            Lecteurs.ACTION_PRECEDENT or Lecteurs.ACTION_DEPLACER,
        titre = " Titre ", artiste = "Artiste", positionMs = 61_500, dureeMs = 200_000,
        volume = 5, volumeMax = 10, controleVolume = Lecteurs.VOLUME_ABSOLU,
    )

    private fun cmd(command: String, value: Any? = null, device: String = "pixel", player: String = "com.spotify.music"): JsonObject =
        buildJsonObject {
            put("action", "control"); put("device", device); put("player", player); put("command", command)
            when (value) {
                is String -> put("value", value)
                is Number -> put("value", value)
                null -> put("value", JsonNull)
            }
        }

    @Test fun statuts() {
        assertEquals("Playing", Lecteurs.statut(Lecteurs.ETAT_LECTURE))
        assertEquals("Playing", Lecteurs.statut(Lecteurs.ETAT_CHARGEMENT))
        assertEquals("Paused", Lecteurs.statut(Lecteurs.ETAT_PAUSE))
        assertEquals("Stopped", Lecteurs.statut(Lecteurs.ETAT_ARRETE))
        assertEquals("Stopped", Lecteurs.statut(7))
        assertEquals("Stopped", Lecteurs.statut(null))
    }

    @Test fun lecteurAuFormatDuPont() {
        val l = Lecteurs.lecteur("com.spotify.music", spotify)
        assertEquals("com.spotify.music", l["id"]!!.jsonPrimitive.content)
        assertEquals("Spotify", l["name"]!!.jsonPrimitive.content)
        assertEquals("Playing", l["status"]!!.jsonPrimitive.content)
        assertEquals("Titre", l["title"]!!.jsonPrimitive.content)
        assertEquals(61.5, l["position"]!!.jsonPrimitive.double, 1e-9)
        assertEquals(200.0, l["length"]!!.jsonPrimitive.double, 1e-9)
        assertEquals(50, l["volume"]!!.jsonPrimitive.int)
        for (k in listOf("can_play", "can_pause", "can_next", "can_prev", "can_seek", "can_control"))
            assertTrue(k, l[k]!!.jsonPrimitive.boolean)
    }

    @Test fun actionsAbsentesEtVolumeFixe() {
        val s = Session(paquet = "org.lecteur", etat = Lecteurs.ETAT_PAUSE, volume = 3, volumeMax = 15)
        val l = Lecteurs.lecteur("org.lecteur", s)
        assertEquals("lecteur", l["name"]!!.jsonPrimitive.content)
        assertEquals(JsonNull, l["volume"])
        assertEquals(JsonNull, l["position"])
        assertEquals(JsonNull, l["length"])
        assertTrue(l["can_play"]!!.jsonPrimitive.boolean)
        assertTrue(l["can_next"]!!.jsonPrimitive.boolean)
        assertFalse(l["can_seek"]!!.jsonPrimitive.boolean)
        // seule la bascule annoncée : lecture et pause possibles, pas suivant
        val b = Lecteurs.lecteur("x", s.copy(actions = Lecteurs.ACTION_BASCULE))
        assertTrue(b["can_play"]!!.jsonPrimitive.boolean)
        assertTrue(b["can_pause"]!!.jsonPrimitive.boolean)
        assertFalse(b["can_next"]!!.jsonPrimitive.boolean)
    }

    @Test fun identifiantsDedoublonnes() {
        val ids = Lecteurs.identifier(listOf(spotify, spotify, Session(paquet = "a b!c"), Session(paquet = "")))
            .map { it.first }
        assertEquals(listOf("com.spotify.music", "com.spotify.music.2", "a_b_c"), ids)
        val beaucoup = Lecteurs.identifier((1..30).map { Session(paquet = "p$it") })
        assertEquals(Lecteurs.MAX_LECTEURS, beaucoup.size)
    }

    @Test fun idsParIndex() {
        // même ordre que les contrôleurs : null pour un paquet inutilisable, rang conservé
        assertEquals(listOf("a", null, "a.2", "b"), Lecteurs.ids(listOf("a", "", "a", "b")))
        val beaucoup = Lecteurs.ids((1..20).map { "p$it" })
        assertEquals(20, beaucoup.size)
        assertEquals(Lecteurs.MAX_LECTEURS, beaucoup.count { it != null })
        assertNull(beaucoup.last())
    }

    @Test fun positionExtrapolee() {
        assertEquals(12_000L, Lecteurs.position(10_000, 1_000, 1f, 3_000, joue = true))
        assertEquals(10_000L, Lecteurs.position(10_000, 1_000, 1f, 3_000, joue = false))
        assertEquals(11_000L, Lecteurs.position(10_000, 1_000, 1f, 3_000, joue = true, dureeMs = 11_000))
        assertNull(Lecteurs.position(-1, 0, 1f, 0, joue = false))
    }

    @Test fun instantaneSansPosition() {
        val a = Lecteurs.instantane(Lecteurs.rapport(listOf(spotify)))
        assertEquals(a, Lecteurs.instantane(Lecteurs.rapport(listOf(spotify.copy(positionMs = 90_000)))))
        assertNotEquals(a, Lecteurs.instantane(Lecteurs.rapport(listOf(spotify.copy(etat = Lecteurs.ETAT_PAUSE)))))
    }

    @Test fun commandesSimples() {
        assertEquals(Commande.Lecture("com.spotify.music"), Lecteurs.lireCommande(cmd("play"), "pixel"))
        assertEquals(Commande.Pause("com.spotify.music"), Lecteurs.lireCommande(cmd("pause"), "pixel"))
        assertEquals(Commande.Bascule("com.spotify.music"), Lecteurs.lireCommande(cmd("toggle"), "pixel"))
        assertEquals(Commande.Suivant("com.spotify.music"), Lecteurs.lireCommande(cmd("next"), "pixel"))
        assertEquals(Commande.Precedent("com.spotify.music"), Lecteurs.lireCommande(cmd("prev"), "pixel"))
        assertNull(Lecteurs.lireCommande(cmd("play", device = "autre"), "pixel"))
        assertNull(Lecteurs.lireCommande(cmd("eject"), "pixel"))
        assertNull(Lecteurs.lireCommande(cmd("play", player = "../x"), "pixel"))
        val refresh = buildJsonObject { put("action", "players_refresh"); put("device", "pixel") }
        assertNull(Lecteurs.lireCommande(refresh, "pixel"))
    }

    @Test fun deplacement() {
        assertEquals(Commande.Deplacer("com.spotify.music", 10.0), Lecteurs.lireCommande(cmd("seek"), "pixel"))
        assertEquals(Commande.Deplacer("com.spotify.music", -10.0), Lecteurs.lireCommande(cmd("seek", -10.0), "pixel"))
        assertEquals(Commande.Deplacer("com.spotify.music", 30.0), Lecteurs.lireCommande(cmd("seek", "+30"), "pixel"))
        assertNull(Lecteurs.lireCommande(cmd("seek", 99_999), "pixel"))
        assertEquals(71_500L, Lecteurs.positionVisee(61_500, 10.0, 200_000))
        assertEquals(0L, Lecteurs.positionVisee(5_000, -10.0, 200_000))
        assertEquals(200_000L, Lecteurs.positionVisee(195_000, 10.0, 200_000))
    }

    @Test fun volume() {
        val abs = Lecteurs.lireCommande(cmd("volume", 40.0), "pixel") as Commande.Volume
        assertFalse(abs.relatif)
        assertEquals(40, Lecteurs.volumeVise(abs, 70))
        val plus = Lecteurs.lireCommande(cmd("volume", "+5"), "pixel") as Commande.Volume
        assertTrue(plus.relatif)
        assertEquals(55, Lecteurs.volumeVise(plus, 50))
        val moins = Lecteurs.lireCommande(cmd("volume", "-10"), "pixel") as Commande.Volume
        assertEquals(0, Lecteurs.volumeVise(moins, 5))
        assertNull(Lecteurs.volumeVise(plus, null))
        assertEquals(100, Lecteurs.volumeVise(Commande.Volume("x", 140.0, false), null))
        assertNull(Lecteurs.lireCommande(cmd("volume"), "pixel"))
        assertNull(Lecteurs.lireCommande(cmd("volume", "fort"), "pixel"))
        assertEquals(8, Lecteurs.cran(50, 15))
        assertEquals(15, Lecteurs.cran(100, 15))
        assertEquals(0, Lecteurs.cran(50, 0))
    }

    @Test fun actions() {
        assertEquals(Action.PAUSE, Lecteurs.action(Commande.Bascule("x"), Lecteurs.ETAT_LECTURE))
        assertEquals(Action.LECTURE, Lecteurs.action(Commande.Bascule("x"), Lecteurs.ETAT_PAUSE))
        assertEquals(Action.LECTURE, Lecteurs.action(Commande.Bascule("x"), null))
        assertEquals(Action.SUIVANT, Lecteurs.action(Commande.Suivant("x"), null))
        assertEquals(Action.DEPLACER, Lecteurs.action(Commande.Deplacer("x", 1.0), null))
        assertEquals(Action.VOLUME, Lecteurs.action(Commande.Volume("x", 1.0, false), null))
    }
}
