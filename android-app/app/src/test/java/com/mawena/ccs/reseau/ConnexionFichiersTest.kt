package com.mawena.ccs.reseau

import com.mawena.ccs.donnees.Identifiants
import com.mawena.ccs.donnees.Preferences
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Seconde connexion de l'onglet Fichiers : fixée sur un appareil, sans changer la machine pilotée. */
class ConnexionFichiersTest {
    private val serveur = MockWebServer()
    private val portee = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val http = OkHttpClient()

    private val echo = object : WebSocketListener() {
        override fun onMessage(webSocket: WebSocket, text: String) {
            val m = CodecRpc.json.parseToJsonElement(text).jsonObject
            val id = m["id"]!!.jsonPrimitive.content
            webSocket.send("""{"id": $id, "result": {"echo": "${m["method"]!!.jsonPrimitive.content}"}}""")
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(1000, null)
        }
    }

    private class PrefsMemoire : Preferences {
        val valeurs = HashMap<String, String>()
        override fun lire(cle: String) = valeurs[cle]
        override fun ecrire(cle: String, valeur: String?) {
            if (valeur == null) valeurs.remove(cle) else valeurs[cle] = valeur
        }
    }

    @Before
    fun avant() = serveur.start()

    @After
    fun apres() {
        portee.cancel()
        serveur.shutdown()
    }

    private fun identifiants() = Identifiants(serveur.url("/").toString(), "charles", jeton = "tok")

    private fun connexion(principal: CcsClient, prefs: Preferences? = null, ids: Identifiants? = null) = ConnexionFichiers(
        principal = principal,
        fabrique = { m -> CcsClient(http, portee).also { it.changerMachine(m) } },
        identifiants = { ids },
        prefs = prefs,
    )

    @Test
    fun machinePiloteeReutiliseLaConnexionPrincipale() {
        val principal = CcsClient(http, portee)
        val c = connexion(principal)
        val o = c.ouvrir("")
        assertSame(principal, o.client)
        assertFalse(o.propre)
        c.fermer()
        assertNull(c.ouverte.value)
        assertEquals(EtatConnexion.Arrete, principal.etat.value)   // jamais arrêtée par l'onglet
    }

    @Test
    fun autreAppareilAUneConnexionAPart() {
        val principal = CcsClient(http, portee)
        val prefs = PrefsMemoire()
        val c = connexion(principal, prefs)
        val o = c.ouvrir("lp-work")
        assertTrue(o.propre)
        assertNotSame(principal, o.client)
        assertEquals("lp-work", o.client.machine.value)
        assertEquals("", principal.machine.value)                  // machine pilotée inchangée
        assertEquals("lp-work", c.memorise)
        assertSame(o, c.ouvrir("lp-work"))                       // déjà ouvert : gardé
        assertSame(o.client, c.clientPour("lp-work"))
        val s = c.ouvrir("")
        assertSame(principal, s.client)
        assertEquals(EtatConnexion.Arrete, o.client.etat.value)    // l'ancien appareil est fermé
        assertEquals("", c.memorise)
        assertTrue(prefs.valeurs.isEmpty())
    }

    @Test
    fun serveurPendantQuOnPiloteUnPc() {
        val principal = CcsClient(http, portee).also { it.changerMachine("lp-work") }
        val c = connexion(principal)
        val o = c.ouvrir("")
        assertTrue(o.propre)
        assertEquals("", o.client.machine.value)
        assertSame(principal, c.ouvrir("lp-work").client)
        assertEquals(EtatConnexion.Arrete, o.client.etat.value)
    }

    @Test
    fun secondeConnexionFixeeSurLaMachine() = runBlocking {
        serveur.enqueue(MockResponse().withWebSocketUpgrade(echo))
        val principal = CcsClient(http, portee)
        val c = connexion(principal, ids = identifiants())
        val o = c.ouvrir("laptop")
        withTimeout(5_000) { o.client.etat.first { it is EtatConnexion.Connecte } }
        assertEquals("/api/ws?protocol=1&machine=laptop", serveur.takeRequest().path)
        val r = withTimeout(5_000) { o.client.appeler("files.roots") }
        assertEquals("files.roots", r.jsonObject["echo"]!!.jsonPrimitive.content)
        assertEquals("", principal.machine.value)
        assertEquals(EtatConnexion.Arrete, principal.etat.value)
        c.fermer()
        assertEquals(EtatConnexion.Arrete, o.client.etat.value)
    }
}
