package com.mawena.ccs.reseau

import com.mawena.ccs.donnees.Adresse
import com.mawena.ccs.donnees.Identifiants
import com.mawena.ccs.donnees.Preferences
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong

sealed interface EtatConnexion {
    /** Pas démarré (pas d'identifiants) ou arrêté. */
    data object Arrete : EtatConnexion
    data class Connexion(val tentative: Int) : EtatConnexion
    data object Connecte : EtatConnexion
    /**
     * Coupé ; nouvel essai dans `attenteMs` (ou plus tôt sur [CcsClient.reessayer]).
     * `machineInjoignable` : le serveur répond, mais la machine pilotée non (fermeture 4010).
     */
    data class HorsLigne(val raison: String, val attenteMs: Long, val machineInjoignable: Boolean = false) : EtatConnexion
    /** Le serveur refuse les identifiants (jeton révoqué, session Portier finie) : se reconnecter. */
    data class Refuse(val raison: String) : EtatConnexion
}

/**
 * Client du WebSocket `/api/ws` : appels RPC suspendus (corrélés par id, avec délai), événements
 * poussés en Flow, reconnexion automatique (1 s, 2 s, 4 s… jusqu'à 30 s), état observable.
 *
 * Comme le client web (`ccs_app/web/api.js`) : un appel fait hors ligne attend dans la file et part
 * à la connexion ; un appel déjà envoyé quand la connexion tombe échoue (`hors_ligne`), car son sort
 * est inconnu. [reconnexions] signale chaque reconnexion pour que les écrans se rattachent.
 *
 * [machine] : machine pilotée (vide : ce serveur), gardée dans `prefs` ; la connexion passe alors par
 * le pont du serveur jusqu'à celui de l'autre machine (`?machine=<id>`), comme `setMachine` du web.
 */
class CcsClient(
    private val http: OkHttpClient,
    private val portee: CoroutineScope,
    private val delaiAppelMs: Long = 30_000,
    private val attenteMinMs: Long = 1_000,
    private val attenteMaxMs: Long = 30_000,
    private val prefs: Preferences? = null,
) {
    private val _machine = MutableStateFlow(prefs?.lire(CLE_MACHINE).orEmpty())
    val machine: StateFlow<String> = _machine.asStateFlow()

    /** Nom affiché de la machine pilotée : « Ce serveur », ou son nom gardé au choix. */
    val nomMachine: String
        get() = _machine.value.let { m -> if (m.isEmpty()) CE_SERVEUR else prefs?.lire(CLE_NOM)?.ifBlank { null } ?: m }

    private val _etat = MutableStateFlow<EtatConnexion>(EtatConnexion.Arrete)
    val etat: StateFlow<EtatConnexion> = _etat.asStateFlow()

    private val _evenements = MutableSharedFlow<MessageRpc.Evenement>(
        extraBufferCapacity = 256, onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val evenements: SharedFlow<MessageRpc.Evenement> = _evenements.asSharedFlow()

    private val _reconnexions = MutableSharedFlow<Unit>(extraBufferCapacity = 1, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val reconnexions: SharedFlow<Unit> = _reconnexions.asSharedFlow()

    private val reveil = MutableSharedFlow<Unit>(extraBufferCapacity = 1, onBufferOverflow = BufferOverflow.DROP_OLDEST)

    private class Attente(val texte: String) {
        val resultat = CompletableDeferred<JsonElement>()
        @Volatile var envoye = false
    }

    private class Fin(val refus: Boolean, val raison: String, val machine: Boolean = false)

    private val attentes = ConcurrentHashMap<Long, Attente>()
    private val suivant = AtomicLong(1)
    private val verrou = Any()
    private var socket: WebSocket? = null     // ouvert, sous `verrou`
    private var boucle: Job? = null
    @Volatile private var dejaOuvert = false
    @Volatile private var identifiants: Identifiants? = null
    @Volatile private var generation = 0       // connexion courante : les écouteurs d'avant se taisent

    fun evenements(nom: String): Flow<JsonObject> = evenements.filter { it.nom == nom }.map { it.donnees }

    /** Se connecte (ou se reconnecte) avec ces identifiants. */
    @Synchronized
    fun demarrer(identifiants: Identifiants) {
        arreter()
        dejaOuvert = false
        lancer(identifiants)
    }

    @Synchronized
    fun arreter() {
        couper("Déconnecté.")
        identifiants = null
        _etat.value = EtatConnexion.Arrete
    }

    /**
     * Pilote une autre machine (`id` vide : ce serveur). Les appels en cours appartiennent à
     * l'ancienne : ils sont rejetés (`hors_ligne`) et la connexion repart tout de suite.
     */
    @Synchronized
    fun changerMachine(id: String, nom: String = id) {
        prefs?.ecrire(CLE_NOM, nom.takeIf { id.isNotEmpty() && it.isNotBlank() })
        if (id == _machine.value) return
        prefs?.ecrire(CLE_MACHINE, id.ifEmpty { null })
        _machine.value = id
        val i = identifiants ?: return
        if (boucle == null) return           // arrêté ou refusé : on garde le choix pour plus tard
        couper("Machine changée.")
        lancer(i)
    }

    private fun lancer(i: Identifiants) {
        identifiants = i
        _etat.value = EtatConnexion.Connexion(1)
        boucle = portee.launch { tourner(i) }
    }

    private fun couper(raison: String) {
        generation++
        boucle?.cancel()
        boucle = null
        synchronized(verrou) {
            socket?.close(1000, null)
            socket = null
        }
        echouerTout("hors_ligne", raison)
    }

    /** Nouvel essai tout de suite si la connexion attend (réseau revenu, appli au premier plan). */
    fun reessayer() {
        reveil.tryEmit(Unit)
    }

    suspend fun appeler(
        methode: String,
        params: JsonObject = JsonObject(emptyMap()),
        delaiMs: Long = delaiAppelMs,
    ): JsonElement {
        when (val e = _etat.value) {
            EtatConnexion.Arrete -> throw RpcException("hors_ligne", "Pas connecté.")
            is EtatConnexion.Refuse -> throw RpcException("refuse", e.raison)
            else -> Unit
        }
        if (attentes.size >= MAX_ATTENTES) throw RpcException("trop", "Trop de demandes en attente.")
        val id = suivant.getAndIncrement()
        val attente = Attente(CodecRpc.requete(id, methode, params))
        attentes[id] = attente
        synchronized(verrou) { socket?.let { envoyer(it, attente) } }
        try {
            return withTimeout(delaiMs) { attente.resultat.await() }
        } catch (e: TimeoutCancellationException) {
            throw RpcException("delai", "Pas de réponse du serveur.")
        } finally {
            attentes.remove(id)
        }
    }

    suspend fun <T> appeler(
        methode: String,
        lecteur: DeserializationStrategy<T>,
        params: JsonObject = JsonObject(emptyMap()),
    ): T = CodecRpc.json.decodeFromJsonElement(lecteur, appeler(methode, params))

    private fun envoyer(ws: WebSocket, a: Attente) {
        if (!a.envoye && ws.send(a.texte)) a.envoye = true
    }

    private fun echouerTout(code: String, message: String, seulementEnvoyes: Boolean = false) {
        for ((id, a) in attentes) {
            if (seulementEnvoyes && !a.envoye) continue
            attentes.remove(id)
            a.resultat.completeExceptionally(RpcException(code, message))
        }
    }

    private suspend fun tourner(identifiants: Identifiants) {
        var attente = attenteMinMs
        var tentative = 0
        while (true) {
            tentative++
            _etat.value = EtatConnexion.Connexion(tentative)
            val fin = CompletableDeferred<Fin>()
            val requete = Request.Builder()
                .url(Adresse.ws(identifiants.serveur, _machine.value))
                .authentifier(identifiants)
                .build()
            val ws = http.newWebSocket(requete, Ecouteur(fin, generation) {
                attente = attenteMinMs
                tentative = 0
            })
            val r = try {
                fin.await()
            } finally {
                ws.cancel()
                synchronized(verrou) { if (socket === ws) socket = null }
                echouerTout("hors_ligne", "Connexion perdue.", seulementEnvoyes = true)
            }
            if (r.refus) {
                echouerTout("refuse", r.raison)
                val moi = kotlinx.coroutines.currentCoroutineContext()[Job]
                synchronized(this) { if (boucle === moi) boucle = null }
                _etat.value = EtatConnexion.Refuse(r.raison)
                return
            }
            _etat.value = EtatConnexion.HorsLigne(r.raison, attente, r.machine)
            withTimeoutOrNull(attente) { reveil.first() }
            attente = (attente * 2).coerceAtMost(attenteMaxMs)
        }
    }

    private inner class Ecouteur(
        private val fin: CompletableDeferred<Fin>,
        private val gen: Int,
        private val ouvert: () -> Unit,
    ) : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            if (gen != generation) { webSocket.cancel(); return }
            ouvert()
            synchronized(verrou) {
                socket = webSocket
                attentes.entries.sortedBy { it.key }.forEach { envoyer(webSocket, it.value) }
            }
            _etat.value = EtatConnexion.Connecte
            if (dejaOuvert) _reconnexions.tryEmit(Unit)
            dejaOuvert = true
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            if (gen != generation) return
            when (val m = CodecRpc.decoder(text)) {
                is MessageRpc.Resultat -> attentes.remove(m.id)?.resultat?.complete(m.resultat)
                is MessageRpc.Echec -> m.id?.let { attentes.remove(it) }
                    ?.resultat?.completeExceptionally(RpcException(m.code, m.message))
                is MessageRpc.Evenement -> _evenements.tryEmit(m)
                null -> Unit
            }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(1000, null)
            fin.complete(fermeture(code, reason))
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            fin.complete(fermeture(code, reason))
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            val statut = response?.code
            fin.complete(
                when (statut) {
                    401 -> Fin(true, "Identifiants refusés par le serveur.")
                    403 -> Fin(true, "Accès refusé par le serveur.")
                    null -> Fin(false, "Serveur injoignable.")
                    else -> Fin(false, "Erreur $statut du serveur.")
                },
            )
        }
    }

    companion object {
        const val FERME_PAR_AUTH = 4001
        /** La machine pilotée est injoignable (hors ligne, tunnel coupé) : on retente plus tard. */
        const val MACHINE_INJOIGNABLE = 4010
        const val CE_SERVEUR = "Ce serveur"
        private const val MAX_ATTENTES = 100
        private const val CLE_MACHINE = "machine"
        private const val CLE_NOM = "machine-nom"

        private fun fermeture(code: Int, raison: String) = when (code) {
            FERME_PAR_AUTH -> Fin(true, "Session terminée.")
            MACHINE_INJOIGNABLE -> Fin(false, raison.ifBlank { "La machine pilotée est injoignable." }, machine = true)
            1011 -> Fin(false, "Pont injoignable sur le serveur.")
            1012 -> Fin(false, "Connexion au pont perdue.")
            else -> Fin(false, raison.ifBlank { "Connexion fermée." })
        }
    }
}
