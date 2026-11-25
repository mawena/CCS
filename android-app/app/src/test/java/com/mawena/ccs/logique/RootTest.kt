package com.mawena.ccs.logique

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class RootTest {
    private val t0 = 1_800_000_000_000L   // horloge du téléphone (ms)

    private fun ask(id: String, essais: Int = 3, erreur: String? = null, expire: Double? = t0 / 1000.0 + 300) = buildJsonObject {
        put("id", id); put("machine", "lp-work"); put("command", "apt install htop")
        expire?.let { put("expires_at", it) }
        put("tries_left", essais)
        erreur?.let { put("error", it) }
    }

    private fun statut(kept: Boolean, restant: Long = 0, pending: JsonObject? = null) = buildJsonObject {
        put("machine", "lp-work"); put("kept", kept); put("remaining", restant)
        if (kept) put("expires_at", t0 / 1000.0 + restant) else put("expires_at", JsonNull)
        put("pending", pending ?: JsonNull)
    }

    @Test
    fun demandeLueEtEcheanceLocale() {
        val e = Root.apresDemande(EtatRoot(), ask("a1"), t0)
        val d = e.demande!!
        assertEquals("a1", d.id)
        assertEquals("lp-work", d.machine)
        assertEquals("apt install htop", d.commande)
        assertEquals(3, d.essais)
        assertNull(d.erreur)
        assertEquals(t0 + 300_000, d.echeanceMs)
    }

    @Test
    fun horlogesDecaleesRetombentSurCinqMinutes() {
        // pont en retard d'une heure (échéance déjà passée pour le téléphone) ou très en avance
        assertEquals(t0 + Root.DEMANDE_MS, Root.echeance(t0 / 1000.0 - 3600, t0, Root.DEMANDE_MS))
        assertEquals(t0 + Root.DEMANDE_MS, Root.echeance(t0 / 1000.0 + 7200, t0, Root.DEMANDE_MS))
        assertEquals(t0 + Root.DEMANDE_MS, Root.echeance(null, t0, Root.DEMANDE_MS))
        assertEquals(t0 + 120_000, Root.echeance(t0 / 1000.0 + 120, t0, Root.DEMANDE_MS))
    }

    @Test
    fun demandeSansIdentifiantIgnoree() {
        val e = EtatRoot()
        assertSame(e, Root.apresDemande(e, buildJsonObject { put("machine", "x") }, t0))
    }

    @Test
    fun mauvaisMotDePasseRevientAvecErreurEtEssais() {
        var e = Root.apresDemande(EtatRoot(), ask("a1"), t0)
        e = Root.envoiEnCours(e, "a1")
        assertTrue(e.envoi)
        // le pont rediffuse la demande avec l'erreur, puis répond à root.answer
        e = Root.apresDemande(e, ask("a1", essais = 2, erreur = "Mot de passe refusé (essai 1 sur 3)."), t0)
        e = Root.apresReponse(e, "a1", false, "Mot de passe refusé (essai 1 sur 3).")
        assertFalse(e.envoi)
        assertEquals(2, e.demande!!.essais)
        assertEquals("Mot de passe refusé (essai 1 sur 3).", e.demande!!.erreur)
        assertEquals("Mot de passe refusé (essai 1 sur 3).", e.avis)
        assertEquals("2 essais restants.", Root.texteEssais(2))
        assertEquals("Dernier essai.", Root.texteEssais(1))
    }

    @Test
    fun regleeFermeSeulementLaBonneDemande() {
        val e = Root.apresDemande(EtatRoot(), ask("a1"), t0)
        assertSame(e, Root.apresReglee(e, buildJsonObject { put("id", "autre"); put("ok", true) }))
        assertNull(Root.apresReglee(e, buildJsonObject { put("id", "a1"); put("ok", false) }).demande)
    }

    @Test
    fun reponseAccepteeFerme() {
        var e = Root.envoiEnCours(Root.apresDemande(EtatRoot(), ask("a1"), t0), "a1")
        e = Root.apresReponse(e, "a1", true, null)
        assertNull(e.demande)
        assertFalse(e.envoi)
        // réponse d'une ancienne demande : sans effet sur la nouvelle
        val f = Root.apresDemande(EtatRoot(), ask("b2"), t0)
        assertSame(f, Root.apresReponse(f, "a1", false, "x"))
    }

    @Test
    fun statutRetrouveDemandeEtGarde() {
        val e = Root.apresStatut(EtatRoot(), statut(true, 1800, ask("p1")), t0)
        assertEquals("p1", e.demande!!.id)
        val g = e.garde!!
        assertEquals("lp-work", g.machine)
        assertEquals(t0 + 1_800_000, g.finMs)
        assertEquals("Root gardé sur lp-work, 30 min", Root.texteGarde(g, t0))
        // plus rien côté pont
        val f = Root.apresStatut(e, statut(false), t0)
        assertNull(f.demande)
        assertNull(f.garde)
    }

    @Test
    fun statutGardeLEnvoiEnCours() {
        val e = Root.envoiEnCours(Root.apresDemande(EtatRoot(), ask("a1"), t0), "a1")
        val f = Root.apresStatut(e, statut(false, pending = ask("a1")), t0)
        assertTrue(f.envoi)
        assertEquals("a1", f.demande!!.id)
    }

    @Test
    fun oubliEfaceLaGarde() {
        val e = Root.apresStatut(EtatRoot(), statut(true, 600, ask("a1")), t0)
        val expire = Root.apresOubli(e, buildJsonObject { put("machine", "lp-work"); put("reason", "expired") })
        assertNull(expire.garde)
        assertNotNull(expire.demande)
        val oubli = Root.apresOubli(e, buildJsonObject { put("machine", "lp-work"); put("reason", "forget") })
        assertNull(oubli.garde)
        assertNull(oubli.demande)
    }

    @Test
    fun echeancesPassees() {
        val e = Root.apresStatut(EtatRoot(), statut(true, 600, ask("a1", expire = t0 / 1000.0 + 60)), t0)
        assertSame(e, Root.apresTemps(e, t0 + 30_000))
        val f = Root.apresTemps(e, t0 + 61_000)
        assertNull(f.demande)
        assertNotNull(f.garde)
        assertNull(Root.apresTemps(f, t0 + 601_000).garde)
    }

    @Test
    fun minutesEtTextes() {
        assertEquals(0L, Root.minutes(0))
        assertEquals(1L, Root.minutes(1))
        assertEquals(1L, Root.minutes(60_000))
        assertEquals(2L, Root.minutes(60_001))
        assertEquals("Root gardé, 5 min", Root.texteGarde(GardeRoot("", t0 + 300_000), t0))
        assertEquals("pc a lancé en root : ls /root", Root.texteUsage(UsageRoot("pc", "ls /root")))
        assertEquals("pc a lancé une commande root", Root.texteUsage(UsageRoot("pc", "")))
        assertEquals("Une machine", Root.lireUsage(buildJsonObject { put("command", "x") }).machine)
    }

    @Test
    fun erreursDuPont() {
        assertTrue(Root.demandePerdue("introuvable"))
        assertFalse(Root.demandePerdue("conflit"))
        assertEquals("Un autre appareil a répondu : vérification en cours.", Root.texteErreur("conflit", "x"))
        assertEquals("message du pont", Root.texteErreur("autre", "message du pont"))
        assertEquals("Réponse non envoyée.", Root.texteErreur(null, null))
    }

    @Test
    fun machineDuLien() {
        val ms = listOf(
            com.mawena.ccs.reseau.Machine(id = "vps", name = "srv-mawena-cloud", local = true),
            com.mawena.ccs.reseau.Machine(id = "lp-work", name = "PC du bureau"),
        )
        assertEquals("lp-work" to "PC du bureau", Root.cibleLien("lp-work", "", ms))
        assertEquals("lp-work" to "PC du bureau", Root.cibleLien("pc du bureau", "", ms))
        assertNull(Root.cibleLien("lp-work", "lp-work", ms))
        // ce serveur : identifiant vide
        assertEquals("" to "", Root.cibleLien("vps", "lp-work", ms))
        assertNull(Root.cibleLien("vps", "", ms))
        assertNull(Root.cibleLien("inconnue", "", ms))
        assertNull(Root.cibleLien(null, "", ms))
    }
}
