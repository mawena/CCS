package com.mawena.ccs.reseau

import com.mawena.ccs.donnees.Identifiants
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Faux serveur : répond `{"echo": méthode}` à chaque appel et pousse un événement à l'ouverture. */
class CcsClientTest {
    private val serveur = MockWebServer()
    private val portee = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val http = OkHttpClient()

    /** Répond à la fermeture, sinon MockWebServer attend en vain à l'arrêt. */
    private open class Poli : WebSocketListener() {
        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(1000, null)
        }
    }

    private val faux = object : Poli() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            webSocket.send("""{"event": "notice", "data": {"texte": "bonjour"}}""")
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val m = CodecRpc.json.parseToJsonElement(text).jsonObject
            val id = m["id"]!!.jsonPrimitive.long
            val methode = m["method"]!!.jsonPrimitive.content
            if (methode == "boum") {
                webSocket.send("""{"id": $id, "error": {"code": "invalide", "message": "Non."}}""")
            } else {
                webSocket.send("""{"id": $id, "result": {"echo": "$methode"}}""")
            }
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

    @Test
    fun appelsEvenementsEtJeton() = runBlocking {
        serveur.enqueue(MockResponse().withWebSocketUpgrade(faux))
        val client = CcsClient(http, portee)
        val evenement = async(start = CoroutineStart.UNDISPATCHED) { withTimeout(5_000) { client.evenements("notice").first() } }
        client.demarrer(identifiants())
        // L'appel part dès l'ouverture, même lancé avant.
        val r = withTimeout(5_000) { client.appeler("accounts.cards") }
        assertEquals("accounts.cards", r.jsonObject["echo"]!!.jsonPrimitive.content)
        assertEquals("bonjour", evenement.await()["texte"]!!.jsonPrimitive.content)
        assertEquals(EtatConnexion.Connecte, client.etat.value)
        val requete = serveur.takeRequest()
        assertEquals("/api/ws", requete.path)
        assertEquals("Bearer tok", requete.getHeader("Authorization"))
        val e = runCatching { client.appeler("boum") }.exceptionOrNull() as RpcException
        assertEquals("invalide", e.code)
        client.arreter()
    }

    @Test
    fun jetonRefuseArreteLaConnexion() = runBlocking {
        serveur.enqueue(MockResponse().setResponseCode(401))
        val client = CcsClient(http, portee)
        client.demarrer(identifiants())
        val etat = withTimeout(5_000) { client.etat.first { it is EtatConnexion.Refuse } }
        assertTrue(etat is EtatConnexion.Refuse)
        val e = runCatching { client.appeler("accounts.cards") }.exceptionOrNull() as RpcException
        assertEquals("refuse", e.code)
    }

    @Test
    fun reconnexionApresCoupure() = runBlocking {
        serveur.enqueue(MockResponse().setResponseCode(502))
        serveur.enqueue(MockResponse().withWebSocketUpgrade(faux))
        val client = CcsClient(http, portee, attenteMinMs = 300, attenteMaxMs = 600)
        client.demarrer(identifiants())
        withTimeout(5_000) { client.etat.first { it is EtatConnexion.HorsLigne } }
        withTimeout(5_000) { client.etat.first { it is EtatConnexion.Connecte } }
        val r = withTimeout(5_000) { client.appeler("sessions.list") }
        assertEquals("sessions.list", r.jsonObject["echo"]!!.jsonPrimitive.content)
        client.arreter()
    }

    @Test
    fun delaiDepasse() = runBlocking {
        serveur.enqueue(MockResponse().withWebSocketUpgrade(Poli()))
        val client = CcsClient(http, portee)
        client.demarrer(identifiants())
        withTimeout(5_000) { client.etat.first { it is EtatConnexion.Connecte } }
        val e = runCatching { client.appeler("lent", delaiMs = 200) }.exceptionOrNull() as RpcException
        assertEquals("delai", e.code)
        client.arreter()
    }
}
