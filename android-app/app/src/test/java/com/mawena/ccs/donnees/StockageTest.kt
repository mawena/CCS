package com.mawena.ccs.donnees

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

private class PrefsMemoire : Preferences {
    val valeurs = HashMap<String, String>()
    override fun lire(cle: String) = valeurs[cle]
    override fun ecrire(cle: String, valeur: String?) {
        if (valeur == null) valeurs.remove(cle) else valeurs[cle] = valeur
    }
}

/** Chiffreur de test : XOR (seul compte l'aller-retour). */
private class ChiffreurXor : Chiffreur {
    override fun chiffrer(clair: ByteArray) = ByteArray(clair.size) { (clair[it].toInt() xor 0x5A).toByte() }
    override fun dechiffrer(chiffre: ByteArray) = chiffrer(chiffre)
}

class StockageTest {
    @Test
    fun normalisation() {
        assertEquals("https://ccs.mawena.cloud", Adresse.normaliser("ccs.mawena.cloud"))
        assertEquals("https://ccs.mawena.cloud", Adresse.normaliser("  https://ccs.mawena.cloud/  "))
        assertEquals("http://192.168.1.5:8420", Adresse.normaliser("http://192.168.1.5:8420/"))
        assertEquals("https://hote.fr/ccs", Adresse.normaliser("https://hote.fr/ccs/?a=1#b"))
        assertEquals("https://ccs.mawena.cloud", Adresse.normaliser("HTTPS://CCS.Mawena.Cloud"))
    }

    @Test
    fun adressesRefusees() {
        listOf("", "   ", "ftp://hote", "https://", "http://moi:secret@hote", "a b.fr").forEach {
            assertNull(it, Adresse.normaliser(it))
        }
    }

    @Test
    fun webSocketVersUneMachine() {
        assertEquals("https://ccs.mawena.cloud/api/ws?protocol=1", Adresse.ws("https://ccs.mawena.cloud").toString())
        assertEquals("https://ccs.mawena.cloud/api/ws?protocol=1&machine=pc-bureau", Adresse.ws("https://ccs.mawena.cloud", "pc-bureau").toString())
        assertEquals("https://hote.fr/ccs/api/ws?protocol=1&machine=pc%20de%20Charles", Adresse.ws("https://hote.fr/ccs/", "pc de Charles").toString())
    }

    @Test
    fun oreilleDeJarvis() {
        val fp = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_abcde"
        assertEquals("https://ccs.mawena.cloud/api/jarvis/oreille?fp=$fp", Adresse.oreilleJarvis("https://ccs.mawena.cloud/", fp).toString())
        assertEquals("http://192.168.1.5:8420/api/jarvis/oreille?fp=$fp", Adresse.oreilleJarvis("http://192.168.1.5:8420", fp).toString())
    }

    @Test
    fun appairageJarvisChiffre() {
        val prefs = PrefsMemoire()
        val c = CoffreJarvis(prefs, ChiffreurXor())
        assertNull(c.lire())
        val a = com.mawena.ccs.logique.AppairageJarvis("e1", "jeton", "f".repeat(43), "Maison", "b")
        c.ecrire(a)
        assertEquals(a, c.lire())
        assertEquals(false, prefs.valeurs["jarvis"]!!.contains("jeton"))
        c.ecrire(null)
        assertNull(c.lire())
    }

    @Test
    fun cheminsDeLApi() {
        assertEquals("https://ccs.mawena.cloud/api/ws", Adresse.api("https://ccs.mawena.cloud", "api/ws").toString())
        assertEquals("https://hote.fr/ccs/api/health", Adresse.api("https://hote.fr/ccs", "/api/health").toString())
    }

    @Test
    fun adresseParDefautPuisEnregistree() {
        val prefs = PrefsMemoire()
        val s = StockageAdresse(prefs)
        assertEquals(Adresse.PAR_DEFAUT, s.lire())
        assertEquals("https://ccs.exemple.fr", s.ecrire("ccs.exemple.fr"))
        assertEquals("https://ccs.exemple.fr", StockageAdresse(prefs).lire())
        assertNull(s.ecrire("ftp://non"))
        assertEquals("https://ccs.exemple.fr", s.lire())
        s.reinitialiser()
        assertEquals(Adresse.PAR_DEFAUT, s.lire())
    }

    @Test
    fun adresseAbimeeRevientAuDefaut() {
        val prefs = PrefsMemoire().apply { valeurs["serveur"] = "n'importe quoi" }
        assertEquals(Adresse.PAR_DEFAUT, StockageAdresse(prefs).lire())
    }

    @Test
    fun coffreAllerRetourEtChiffre() {
        val prefs = PrefsMemoire()
        val coffre = Coffre(prefs, ChiffreurXor())
        assertNull(coffre.lire())
        val i = Identifiants("https://ccs.mawena.cloud", "charles", jeton = "secret-123")
        coffre.ecrire(i)
        assertEquals(i, coffre.lire())
        assert(!prefs.valeurs.values.single().contains("secret-123"))
        coffre.ecrire(null)
        assertNull(coffre.lire())
    }

    @Test
    fun coffreIllisibleDonneRien() {
        val prefs = PrefsMemoire().apply { valeurs["identifiants"] = "@@pas du base64@@" }
        assertNull(Coffre(prefs, ChiffreurXor()).lire())
    }
}

class RecentsTest {
    @Test
    fun huitDossiersAuPlusLePlusRecentDabord() {
        val r = DossiersRecents(PrefsMemoire())
        assertEquals(emptyList<String>(), r.lire())
        (1..10).forEach { r.retenir("/d$it") }
        r.retenir("/d5")
        r.retenir("  ")
        val l = r.lire()
        assertEquals(8, l.size)
        assertEquals(listOf("/d5", "/d10", "/d9"), l.take(3))
    }
}
