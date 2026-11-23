package com.mawena.ccs.jarvis

import com.mawena.ccs.donnees.Adresse
import com.mawena.ccs.donnees.Identifiants
import com.mawena.ccs.logique.ErreurJarvis
import com.mawena.ccs.logique.Jarvis
import com.mawena.ccs.logique.MessageCerveau
import com.mawena.ccs.reseau.authentifier
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString

/**
 * Un WebSocket `/api/jarvis/oreille` du serveur CCS (même jeton d'appareil ou cookies de Portier que
 * `/api/ws`). Le premier message (`hello` ou `pair`) part dès l'ouverture ; [ouvrir] rend la
 * première réponse du cerveau (`welcome`, `paired`) ou échoue (refus, relais en erreur, fermeture,
 * 30 s sans réponse). Ensuite, les messages arrivent dans [surMessage] et la fin dans [surFin]
 * (texte à montrer, ou null si la fermeture est normale), sur le fil de [portee] (principal).
 */
class LienJarvis(
    http: OkHttpClient,
    identifiants: Identifiants,
    empreinte: String,
    private val premier: String,
    private val portee: CoroutineScope,
) {
    var surMessage: (MessageCerveau) -> Unit = {}
    var surFin: (String?) -> Unit = {}

    /** Le cerveau a répondu : on peut parler. */
    var pret = false
        private set

    private val attente = CompletableDeferred<MessageCerveau>()
    private var relais: String? = null
    private var fini = false
    private val ws: WebSocket

    init {
        val requete = Request.Builder()
            .url(Adresse.oreilleJarvis(identifiants.serveur, empreinte))
            .authentifier(identifiants)
            .build()
        ws = http.newWebSocket(requete, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                webSocket.send(premier)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val m = Jarvis.lire(text)
                portee.launch { traiter(m) }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
                portee.launch { finir(code, reason) }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                portee.launch { finir(code, reason) }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                val statut = response?.code
                portee.launch {
                    when {
                        statut == 401 -> terminer("Session CCS refusée : reconnecte l'appli.")
                        statut == 403 -> terminer("Accès refusé par le serveur CCS.")
                        statut != null && statut >= 400 -> terminer("Erreur $statut du serveur CCS.")
                        else -> finir(1006, "")
                    }
                }
            }
        })
    }

    suspend fun ouvrir(): MessageCerveau = try {
        withTimeout(30_000) { attente.await() }
    } catch (e: TimeoutCancellationException) {
        fermer()
        throw ErreurJarvis("Jarvis ne répond pas (30 s).")
    }

    fun envoyer(texte: String) {
        if (!fini) ws.send(texte)
    }

    fun envoyer(octets: ByteArray) {
        if (!fini) ws.send(octets.toByteString())
    }

    /** Fermeture voulue : pas de message. */
    fun fermer() {
        if (fini) return
        fini = true
        pret = false
        ws.close(1000, null)
        if (!attente.isCompleted) attente.completeExceptionally(ErreurJarvis("Lien fermé."))
    }

    private fun traiter(m: MessageCerveau) {
        if (fini) return
        when (m) {
            is MessageCerveau.Relais -> relais = m.message      // la fermeture suit (4011 : Jarvis injoignable)
            is MessageCerveau.Refus ->
                if (!attente.isCompleted) {
                    attente.completeExceptionally(ErreurJarvis(Jarvis.texteRefus(m.motif, m.essais), m.motif))
                    fermer()
                } else {
                    surMessage(m)
                }
            is MessageCerveau.Bienvenue, is MessageCerveau.Appaire ->
                if (!attente.isCompleted) {
                    pret = true
                    attente.complete(m)
                } else {
                    surMessage(m)
                }
            else -> surMessage(m)
        }
    }

    private fun finir(code: Int, raison: String) {
        if (fini) return
        val normale = code == 1000 && relais == null
        terminer(if (normale && attente.isCompleted) null else Jarvis.texteFermeture(code, relais, raison))
    }

    private fun terminer(texte: String?) {
        if (fini) return
        fini = true
        val etaitPret = pret
        pret = false
        ws.cancel()
        if (!attente.isCompleted) {
            attente.completeExceptionally(ErreurJarvis(texte ?: "Connexion au relais de Jarvis perdue."))
        } else if (etaitPret) {
            surFin(texte)
        }
    }
}
