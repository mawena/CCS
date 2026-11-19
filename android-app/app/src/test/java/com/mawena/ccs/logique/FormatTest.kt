package com.mawena.ccs.logique

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FormatTest {
    private val t0 = 1_000_000.0

    @Test
    fun ilYAcommeLaVersionWeb() {
        assertEquals("", Format.ilYA(null, t0))
        assertEquals("", Format.ilYA(0.0, t0))
        assertEquals("à l'instant", Format.ilYA(t0 - 30, t0))
        assertEquals("à l'instant", Format.ilYA(t0 + 30, t0))          // horloges décalées
        assertEquals("il y a 5 min", Format.ilYA(t0 - 5 * 60 - 10, t0))
        assertEquals("il y a 3 h", Format.ilYA(t0 - 3 * 3600 - 59, t0))
        assertEquals("hier", Format.ilYA(t0 - 86400 - 5, t0))
        assertEquals("il y a 4 j", Format.ilYA(t0 - 4 * 86400, t0))
    }

    @Test
    fun nombreCourt() {
        assertEquals("999", Format.nombreCourt(999.4))
        assertEquals("12 k", Format.nombreCourt(12_345.0))
        assertEquals("1.2 M", Format.nombreCourt(1_234_567.0))
        assertEquals("3.0 G", Format.nombreCourt(3e9))
    }

    @Test
    fun cheminsCourts() {
        assertEquals("ccs", Format.base("/home/c/Work/ccs/"))
        assertEquals("", Format.base(null))
        assertEquals("~/Work/ccs", Format.court("/home/c/Work/ccs", "/home/c"))
        assertEquals("/srv/site", Format.court("/srv/site", "/home/c"))
        assertEquals("/home/cc", Format.court("/home/cc", "/home/c"))
    }

    @Test
    fun pourcentBorne() {
        assertEquals(0, Format.pourcent(-3.0))
        assertEquals(43, Format.pourcent(42.6))
        assertEquals(100, Format.pourcent(130.0))
    }

    @Test
    fun barresTrieesEtLimitees() {
        val d = (1..10).associate { "p$it" to it.toDouble() }
        val b = Format.barres(d, 55.0)
        assertEquals(8, b.size)
        assertEquals("p10", b.first().first)
        assertEquals(100 * 10 / 55.0, b.first().third, 1e-9)
        assertEquals(0.0, Format.barres(mapOf("a" to 1.0), 0.0).single().third, 0.0)
    }

    @Test
    fun rolesDesMessages() {
        assertEquals(Format.Role.Toi, Format.role("utilisateur"))
        assertEquals(Format.Role.Toi, Format.role("USER"))
        assertEquals(Format.Role.Claude, Format.role("assistant"))
        assertNull(Format.role("outil"))
        assertNull(Format.role("note"))
    }

    @Test
    fun etatsDesChats() {
        assertEquals("Claude travaille", EtatChat.de("busy").libelle)
        assertEquals("attend ta réponse", EtatChat.de("permission").libelle)
        assertEquals(EtatChat.Ton.Pret, EtatChat.de("idle").ton)
        assertEquals("arrêté", EtatChat.de("inconnu").libelle)
    }

    @Test
    fun dossiersProposesSansDoublonEtFiltres() {
        val home = "/home/c"
        val tous = dossiersProposes(
            recents = listOf("/home/c/Work/ccs"),
            connus = listOf("/home/c/Work/ccs", "/home/c/Work/site"),
            depots = listOf("/home/c/Work/site", "/srv/app"),
            saisie = "", home = home,
        )
        assertEquals(listOf("récent", "projet", "git"), tous.map { it.etiquette })
        assertEquals(listOf("/home/c/Work/ccs", "/home/c/Work/site", "/srv/app"), tous.map { it.chemin })
        val filtre = dossiersProposes(listOf("/home/c/Work/ccs"), emptyList(), listOf("/srv/app"), "~/work", home)
        assertEquals(listOf("/home/c/Work/ccs"), filtre.map { it.chemin })
        assertEquals(listOf("/srv/app"), dossiersProposes(emptyList(), emptyList(), listOf("/srv/app"), "APP", home).map { it.chemin })
    }
}
