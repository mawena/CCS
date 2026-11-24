package com.mawena.ccs.son

import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import androidx.core.content.ContextCompat
import com.mawena.ccs.logique.Audio
import com.mawena.ccs.reseau.CcsClient
import com.mawena.ccs.reseau.EnvoiAudio
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.EtatReseau
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.Inet4Address
import java.net.NetworkInterface

/**
 * Son partagé sur le réseau maillé (phase 42, `docs/audio.md`) : ce téléphone s'annonce au pont
 * du serveur toutes les 30 s tant que l'appli est connectée (sortie toujours, source sur Android
 * 10+), suit l'événement `audio` et lance le service qui joue ([ServiceReception]) ou celui qui
 * capte et émet ([ServiceEmission]). Le son passe en UDP direct entre adresses 100.64.x.
 */
class SonPartage(private val ctx: Context, private val client: CcsClient, private val portee: CoroutineScope) {
    /** Nom et adresse sous lesquels ce téléphone est annoncé. */
    data class Identite(val device: String, val ip: String, val label: String)

    /** Flux que ce téléphone joue. */
    data class Reception(val flux: String, val source: String, val nomSource: String, val port: Int, val canaux: Int)

    /** Où ce téléphone envoie son son. */
    data class Destination(val flux: String, val cible: String, val nomCible: String, val ip: String, val port: Int)

    sealed interface Capture {
        data object Arretee : Capture
        /** Accord donné, `audio.send` en cours. */
        data class Preparation(val nomCible: String) : Capture
        data class Envoi(val destination: Destination) : Capture
    }

    /** Demande d'accord MediaProjection, traitée par l'activité ; [destination] : flux déjà ouvert par un autre appareil. */
    data class DemandeAccord(val cible: String, val nomCible: String, val destination: Destination? = null)

    private val _identite = MutableStateFlow<Identite?>(null)
    val identite: StateFlow<Identite?> = _identite.asStateFlow()

    /** Lecteurs du téléphone rapportés au pont et pilotés à distance (phase 42). */
    val lecteurs = LecteursTelephone(ctx, client, portee, identite)

    /** Pourquoi ce téléphone n'est pas annoncé (pas d'adresse maillée, refus du pont), sinon null. */
    private val _probleme = MutableStateFlow<String?>(null)
    val probleme: StateFlow<String?> = _probleme.asStateFlow()

    private val _reception = MutableStateFlow<Reception?>(null)
    val reception: StateFlow<Reception?> = _reception.asStateFlow()

    private val _capture = MutableStateFlow<Capture>(Capture.Arretee)
    val capture: StateFlow<Capture> = _capture.asStateFlow()

    /** Accord à demander (lu et remis à null par l'activité). */
    val demandeAccord = MutableStateFlow<DemandeAccord?>(null)

    private val _changements = MutableSharedFlow<Unit>(extraBufferCapacity = 1, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    /** Un flux a commencé ou fini : l'écran Son relit `audio.list`. */
    val changements: SharedFlow<Unit> = _changements.asSharedFlow()

    private val _erreurs = MutableSharedFlow<String>(extraBufferCapacity = 4, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val erreurs: SharedFlow<String> = _erreurs.asSharedFlow()

    /** Envoi demandé par un autre appareil, en attente de l'accord (notification). */
    @Volatile private var emitEnAttente: Destination? = null
    private var nomConnu: String? = null
    private var ipNommee: String? = null

    /** Ce téléphone sait capter le son des autres applis (AudioPlaybackCapture, Android 10+). */
    val saitCapter: Boolean get() = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q

    init {
        portee.launch {
            client.etat.collectLatest { e ->
                if (e !is EtatConnexion.Connecte) return@collectLatest
                while (true) {
                    annoncer()
                    delay(Audio.ANNONCE_MS)
                }
            }
        }
        portee.launch {
            client.evenements("audio").collect { d ->
                val moi = _identite.value?.device ?: return@collect
                val ev = Audio.lireEvenement(d, moi) ?: return@collect
                traiter(ev)
                _changements.tryEmit(Unit)
            }
        }
    }

    // ---- annonce -----------------------------------------------------------------------------

    private fun adressesLocales(): List<String> = runCatching {
        NetworkInterface.getNetworkInterfaces()?.toList().orEmpty()
            .filter { it.isUp }
            .flatMap { it.inetAddresses.toList() }
            .filterIsInstance<Inet4Address>()
            .mapNotNull { it.hostAddress }
    }.getOrDefault(emptyList())

    /** `audio.announce` (relu toutes les 30 s) ; le nom vient du pair maillé qui a notre adresse. */
    suspend fun annoncer() {
        val ip = Audio.ipMaille(adressesLocales())
        if (ip == null) {
            _probleme.value = "Pas d'adresse du réseau maillé (100.64.x) : Tailscale est-il connecté sur ce téléphone ?"
            return
        }
        val nom = nomConnu?.takeIf { ipNommee == ip } ?: run {
            val etat = runCatching { client.appeler("network.status", EtatReseau.serializer()) }.getOrNull()
            Audio.nomAppareil(etat, ip, Build.MODEL.orEmpty()).also { if (etat != null) { nomConnu = it; ipNommee = ip } }
        }
        val label = Build.MODEL.orEmpty().ifBlank { nom }.take(60)
        val ancien = _identite.value
        try {
            client.appeler("audio.announce", buildJsonObject {
                put("device", nom); put("label", label); put("ip", ip); put("port", Audio.PORT)
                put("play", true); put("capture", saitCapter); put("system", "android")
            })
            _identite.value = Identite(nom, ip, label)
            _probleme.value = null
            // nom changé (réseau maillé lu après coup) : l'ancien est oublié tout de suite
            if (ancien != null && ancien.device != nom) {
                runCatching { client.appeler("audio.forget", buildJsonObject { put("device", ancien.device) }) }
            }
        } catch (e: Exception) {
            _probleme.value = "Annonce refusée : ${e.message ?: "pont injoignable"}"
        }
    }

    /** Déconnexion volontaire : `audio.forget` (2 s au plus), flux locaux arrêtés. */
    suspend fun partir() {
        val moi = _identite.value
        if (moi != null) {
            withTimeoutOrNull(2_000) {
                runCatching { client.appeler("audio.forget", buildJsonObject { put("device", moi.device) }, 2_000) }
            }
        }
        _identite.value = null
        _reception.value = null
        _capture.value = Capture.Arretee
        emitEnAttente = null
        NotifsSon.retirerDemande(ctx)
    }

    // ---- événements --------------------------------------------------------------------------

    private fun traiter(ev: Audio.Evenement) {
        when (ev) {
            is Audio.Evenement.Recevoir -> {
                _reception.value = Reception(ev.flux, ev.source, ev.nomSource, ev.port, ev.canaux)
                demarrerReception()
            }
            is Audio.Evenement.Emettre -> {
                val d = Destination(ev.flux, ev.cible, ev.nomCible, ev.ip, ev.port)
                if (_capture.value != Capture.Arretee) {
                    _capture.value = Capture.Envoi(d)
                } else {
                    // envoi lancé depuis un autre appareil : Android veut un accord à chaque départ
                    emitEnAttente = d
                    NotifsSon.demandeEnvoi(ctx, d)
                }
            }
            is Audio.Evenement.Arreter -> {
                if (_reception.value?.flux == ev.flux) _reception.value = null
                if ((_capture.value as? Capture.Envoi)?.destination?.flux == ev.flux) _capture.value = Capture.Arretee
                if (emitEnAttente?.flux == ev.flux) {
                    emitEnAttente = null
                    NotifsSon.retirerDemande(ctx)
                }
            }
        }
    }

    private fun demarrerReception() {
        try {
            ContextCompat.startForegroundService(ctx, Intent(ctx, ServiceReception::class.java))
        } catch (e: Exception) {
            // démarrage en arrière-plan refusé (Android 12+) : il faudra toucher la notification
            Log.w(TAG, "service de réception", e)
            _reception.value?.let { NotifsSon.demandeEcoute(ctx, it) }
        }
    }

    /** Appli rouverte (notification « Touchez pour écouter ») : relance la réception en attente. */
    fun reprendre() {
        if (_reception.value != null) demarrerReception()
        NotifsSon.retirerEcoute(ctx)
    }

    /** La réception s'est arrêtée d'elle-même (10 s sans paquet, port pris). */
    fun receptionFinie(flux: String, erreur: String?) {
        if (_reception.value?.flux == flux) _reception.value = null
        erreur?.let { _erreurs.tryEmit(it) }
        _changements.tryEmit(Unit)
    }

    // ---- envoi ---------------------------------------------------------------------------------

    /** Écran Son → « Envoyer le son de ce téléphone vers… » : l'activité demande l'accord. */
    fun envoyerVers(cible: String, nomCible: String) {
        demandeAccord.value = DemandeAccord(cible, nomCible)
    }

    /** Notification « Touchez pour envoyer le son vers X » touchée. */
    fun accepterEnvoi(d: Destination) {
        demandeAccord.value = DemandeAccord(d.cible, d.nomCible, d)
    }

    /** Accord MediaProjection donné : service d'émission, puis `audio.send` (ou le flux déjà ouvert). */
    fun accordObtenu(demande: DemandeAccord, code: Int, donnees: Intent) {
        NotifsSon.retirerDemande(ctx)
        _capture.value = Capture.Preparation(demande.nomCible)
        try {
            ContextCompat.startForegroundService(ctx, ServiceEmission.intention(ctx, code, donnees))
        } catch (e: Exception) {
            Log.w(TAG, "service d'émission", e)
            _capture.value = Capture.Arretee
            _erreurs.tryEmit("Envoi impossible : ${e.message ?: "service refusé"}")
            return
        }
        val deja = demande.destination?.takeIf { it.flux == emitEnAttente?.flux }
        emitEnAttente = null
        if (deja != null) {
            _capture.value = Capture.Envoi(deja)
            return
        }
        portee.launch {
            val moi = _identite.value?.device
            try {
                if (moi == null) throw IllegalStateException("ce téléphone n'est pas annoncé")
                val r = client.appeler("audio.send", EnvoiAudio.serializer(), buildJsonObject {
                    put("source", moi); put("target", demande.cible)
                })
                // l'événement `emit` a pu arriver avant la réponse : même flux, rien ne change
                if (_capture.value is Capture.Preparation) {
                    _capture.value = Capture.Envoi(Destination(r.stream, demande.cible, demande.nomCible, r.ip, r.port))
                }
            } catch (e: Exception) {
                _capture.value = Capture.Arretee
                _erreurs.tryEmit("Envoi impossible : ${e.message ?: "pont injoignable"}")
            }
            _changements.tryEmit(Unit)
        }
    }

    fun accordRefuse() {
        emitEnAttente = null
        _erreurs.tryEmit("Envoi annulé : accord de capture refusé.")
    }

    /** La capture s'est arrêtée (projection retirée, erreur) : prévient le pont. */
    fun emissionFinie(erreur: String?) {
        val flux = (_capture.value as? Capture.Envoi)?.destination?.flux
        _capture.value = Capture.Arretee
        erreur?.let { _erreurs.tryEmit(it) }
        if (flux != null) portee.launch { arreterFlux(flux) }
        _changements.tryEmit(Unit)
    }

    /** Bouton Arrêter (notification, écran) d'un flux de ce téléphone. */
    fun arreterReception() {
        val flux = _reception.value?.flux ?: return
        _reception.value = null
        portee.launch { arreterFlux(flux) }
    }

    fun arreterEmission() {
        val flux = (_capture.value as? Capture.Envoi)?.destination?.flux
        _capture.value = Capture.Arretee
        if (flux != null) portee.launch { arreterFlux(flux) }
    }

    /** `audio.stop {stream}` (silencieux : le flux a pu finir entre-temps). */
    suspend fun arreterFlux(flux: String) {
        runCatching { client.appeler("audio.stop", buildJsonObject { put("stream", flux) }) }
        _changements.tryEmit(Unit)
    }

    companion object {
        private const val TAG = "SonPartage"
    }
}
