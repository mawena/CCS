package com.mawena.ccs.logique

import com.mawena.ccs.reseau.Machine
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AppareilsTest {
    private val serveur = Machine(id = "vps", name = "VPS", online = true, local = true)
    private val maille = Machine(id = "lp-work", name = "PC du bureau", online = true, ipMaille = "100.64.0.2")
    private val tunnel = Machine(id = "laptop", online = true, tunnel = true)
    private val horsLigne = Machine(id = "vieux", name = "Vieux PC", online = false, ipMaille = "100.64.0.9")
    private val sansChemin = Machine(id = "isole", online = true)

    @Test
    fun joignableParLeReseauMailleOuLeTunnel() {
        assertTrue(Appareils.joignable(maille))
        assertTrue(Appareils.joignable(tunnel))
        assertFalse(Appareils.joignable(horsLigne))
        assertFalse(Appareils.joignable(sansChemin))
        assertFalse(Appareils.joignable(serveur))     // le serveur lui-même n'est pas une puce de PC
    }

    @Test
    fun raisonDUnAppareilInjoignable() {
        assertEquals("", Appareils.raison(maille))
        assertEquals("hors ligne", Appareils.raison(horsLigne))
        assertEquals("ni réseau maillé ni tunnel", Appareils.raison(sansChemin))
    }

    @Test
    fun listeServeurDAbordSansLaMachineLocale() {
        val l = Appareils.liste(listOf(serveur, maille, horsLigne, tunnel, maille.copy(name = "doublon")))
        assertEquals(listOf("", "lp-work", "vieux", "laptop"), l.map { it.id })
        assertEquals(Appareils.NOM_SERVEUR, l[0].nom)
        assertTrue(l[0].serveur && l[0].joignable)
        assertEquals("PC du bureau", l[1].nom)
        assertEquals("laptop", l[3].nom)          // pas de nom : l'identifiant
        assertFalse(l[2].joignable)
        assertEquals("hors ligne", l[2].raison)
    }

    @Test
    fun appareilInitial() {
        val l = Appareils.liste(listOf(maille, horsLigne))
        assertEquals("", Appareils.initial(null, l))
        assertEquals("", Appareils.initial("", l))
        assertEquals("lp-work", Appareils.initial("lp-work", l))
        assertEquals("vieux", Appareils.initial("vieux", l))           // tenté : message et Réessayer
        assertEquals("", Appareils.initial("disparu", l))              // plus dans la liste : le serveur
        assertEquals("lp-work", Appareils.initial("lp-work", Appareils.liste(emptyList())))   // liste pas encore lue
    }

    @Test
    fun nomEtPartageDeConnexion() {
        val l = Appareils.liste(listOf(maille))
        assertEquals("PC du bureau", Appareils.nom("lp-work", l))
        assertEquals("Serveur CCS", Appareils.nom("", l))
        assertEquals("inconnu", Appareils.nom("inconnu", l))
        assertTrue(Appareils.partageConnexion("", ""))
        assertTrue(Appareils.partageConnexion("lp-work", "lp-work"))
        assertFalse(Appareils.partageConnexion("", "lp-work"))      // serveur pendant qu'on pilote un PC
        assertFalse(Appareils.partageConnexion("lp-work", ""))
    }

    @Test
    fun messageInjoignable() {
        assertEquals("PC du bureau injoignable : lp-work est hors ligne.",
            Appareils.messageInjoignable("lp-work", "PC du bureau", "lp-work est hors ligne."))
        assertEquals("PC du bureau injoignable : pas de réponse par le réseau maillé ni le tunnel.",
            Appareils.messageInjoignable("lp-work", "PC du bureau", "La machine pilotée est injoignable."))
        assertEquals("PC du bureau injoignable : pas de réponse.", Appareils.messageInjoignable("lp-work", "PC du bureau", " "))
        assertEquals("Serveur injoignable.", Appareils.messageInjoignable("", "Serveur CCS", "Serveur injoignable."))
    }

    @Test
    fun argumentDeRoute() {
        assertEquals("", Appareils.versRoute(null))
        assertEquals("@", Appareils.versRoute(""))
        assertEquals("@lp-work", Appareils.versRoute("lp-work"))
        assertNull(Appareils.deRoute(null))
        assertNull(Appareils.deRoute(""))
        assertEquals("", Appareils.deRoute("@"))
        assertEquals("lp-work", Appareils.deRoute("@lp-work"))
    }
}
