package com.mawena.ccs.reseau

import com.mawena.ccs.donnees.Identifiants
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Jeton d'appareil après Portier (`/api/app-token`), liste et révocation des accès. */
class ApiHttpTest {
    private val serveur = MockWebServer()
    private val api = ApiHttp(OkHttpClient())

    @Before fun avant() = serveur.start()
    @After fun apres() = serveur.shutdown()

    private fun base() = serveur.url("/").toString()
    private fun portier() = Identifiants(base(), "c", cookies = "portier=abc")

    @Test
    fun jetonDonneParLeServeur() = runBlocking {
        serveur.enqueue(MockResponse().setBody("""{"token":"APP-1"}"""))
        assertEquals("APP-1", api.jetonAppli(portier(), "Pixel 4 XL"))
        val r = serveur.takeRequest()
        assertEquals("/api/app-token", r.path)
        assertEquals("POST", r.method)
        assertEquals("portier=abc", r.getHeader("Cookie"))
        assertEquals("""{"name":"Pixel 4 XL"}""", r.body.readUtf8())
    }

    @Test
    fun serveurPasEncoreAJour() = runBlocking {
        serveur.enqueue(MockResponse().setResponseCode(404))
        assertNull(api.jetonAppli(portier(), "Pixel 4 XL"))
        serveur.enqueue(MockResponse().setResponseCode(401))
        assertNull(api.jetonAppli(portier(), "Pixel 4 XL"))
        serveur.enqueue(MockResponse().setBody("""{}"""))
        assertNull(api.jetonAppli(portier(), "Pixel 4 XL"))
    }

    @Test
    fun jetonEtCookiesEnvoyesEnsemble() = runBlocking {
        serveur.enqueue(MockResponse().setBody("""{"tokens":[{"id":"x","kind":"app","name":"Pixel 4 XL","last_used":1.0}]}"""))
        val l = api.acces(portier().copy(jeton = "APP-1"))!!
        assertEquals("Pixel 4 XL", l.tokens[0].name)
        val r = serveur.takeRequest()
        assertEquals("Bearer APP-1", r.getHeader("Authorization"))
        assertEquals("portier=abc", r.getHeader("Cookie"))
        serveur.enqueue(MockResponse().setResponseCode(401))
        assertNull(api.acces(Identifiants(base(), "c", jeton = "APP-1")))
    }

    @Test
    fun revocation() = runBlocking {
        serveur.enqueue(MockResponse().setBody("""{"revoked":true}"""))
        assertEquals(Revocation.Faite, api.revoquer(portier(), "x"))
        assertEquals("""{"token_id":"x"}""", serveur.takeRequest().body.readUtf8())
        serveur.enqueue(MockResponse().setBody("""{"revoked":false}"""))
        assertTrue(api.revoquer(portier(), "x") is Revocation.Refusee)
    }
}
