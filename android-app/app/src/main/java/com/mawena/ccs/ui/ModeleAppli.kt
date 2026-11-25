package com.mawena.ccs.ui

import android.app.Application
import android.webkit.CookieManager
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.mawena.ccs.CcsAppli
import com.mawena.ccs.donnees.Identifiants
import com.mawena.ccs.reseau.EtatConnexion
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** Ce qu'une intention demande à l'appli : notification, raccourci. */
sealed interface DemandeAppli {
    data class OuvrirChat(val dest: DestChat) : DemandeAppli
    data object Sessions : DemandeAppli
    data object NouveauChat : DemandeAppli
    /** Écran « Parler à Jarvis » (raccourci, `ccs://jarvis`, QR code `jarvis://pair?…`). */
    data object Jarvis : DemandeAppli
    /** Écran « Son partagé » (notification d'un flux de son). */
    data object Son : DemandeAppli
}

/** État de l'appli : adresse du serveur, identifiants gardés, connexion. */
class ModeleAppli(appli: Application) : AndroidViewModel(appli) {
    val depot = (appli as CcsAppli).depot

    private val _adresse = MutableStateFlow(depot.adresse.lire())
    val adresse: StateFlow<String> = _adresse.asStateFlow()

    private val _identifiants = MutableStateFlow(depot.coffre.lire()?.takeIf { it.serveur == _adresse.value })
    val identifiants: StateFlow<Identifiants?> = _identifiants.asStateFlow()

    /** Pourquoi on est revenu à l'écran de connexion (jeton révoqué…), affiché une fois. */
    private val _avis = MutableStateFlow<String?>(null)
    val avis: StateFlow<String?> = _avis.asStateFlow()

    val etat: StateFlow<EtatConnexion> = depot.client.etat

    /** Coûts des conversations déjà lus (clé : chemin + date), demandés un à la fois. */
    val couts = java.util.concurrent.ConcurrentHashMap<String, com.mawena.ccs.reseau.Cout>()
    val fileCouts = kotlinx.coroutines.sync.Mutex()

    private val _theme = MutableStateFlow(depot.reglages.theme)
    val theme: StateFlow<com.mawena.ccs.donnees.Theme> = _theme.asStateFlow()

    /** Notification touchée, raccourci : traité par l'écran principal, puis remis à null. */
    val demande = MutableStateFlow<DemandeAppli?>(null)

    /** Partage Android en attente du choix d'un chat. */
    val partage = MutableStateFlow<com.mawena.ccs.logique.Partage?>(null)

    /** « Nouveau chat » demandé (raccourci) : l'écran Sessions ouvre la feuille. */
    val nouvelleSession = MutableStateFlow(false)

    private val _notifications = MutableStateFlow(depot.reglages.notifications)
    val notifications: StateFlow<Boolean> = _notifications.asStateFlow()

    fun changerNotifications(actives: Boolean) {
        depot.reglages.notifications = actives
        _notifications.value = actives
        com.mawena.ccs.notif.ServiceVeille.appliquer(getApplication())
    }

    private val _lireReponses = MutableStateFlow(depot.reglages.lireReponses)
    /** Réglage « Lire les réponses à voix haute » (propre à ce téléphone). */
    val lireReponses: StateFlow<Boolean> = _lireReponses.asStateFlow()

    fun changerLireReponses(actif: Boolean) {
        depot.reglages.lireReponses = actif
        _lireReponses.value = actif
    }

    /** Machine pilotée (vide : ce serveur) ; tout l'appli la suit, notifications comprises. */
    val machine: StateFlow<String> = depot.client.machine

    /**
     * Connexion de l'onglet Fichiers à un appareil (serveur ou PC du réseau maillé), à part de la
     * machine pilotée : elle n'en change pas. Fermée en quittant l'onglet.
     */
    val fichiers = com.mawena.ccs.reseau.ConnexionFichiers(
        principal = depot.client,
        fabrique = { m -> com.mawena.ccs.reseau.CcsClient(depot.http, depot.portee).also { it.changerMachine(m) } },
        identifiants = { _identifiants.value },
        prefs = depot.prefs,
    )

    override fun onCleared() {
        fichiers.fermer()
        super.onCleared()
    }

    /** Autres machines connues (dernière liste reçue, gardée si la connexion est coupée). */
    private val _machines = MutableStateFlow(lireMachines())
    val machines: StateFlow<List<com.mawena.ccs.reseau.Machine>> = _machines.asStateFlow()

    private fun lireMachines(): List<com.mawena.ccs.reseau.Machine> = runCatching {
        depot.prefs.lire(CLE_MACHINES)?.let {
            com.mawena.ccs.reseau.CodecRpc.json.decodeFromString(
                kotlinx.serialization.builtins.ListSerializer(com.mawena.ccs.reseau.Machine.serializer()), it,
            )
        }
    }.getOrNull().orEmpty()

    /**
     * Relit `machines.list` (onglet Réseau, connexion) ; rend la liste complète, ou null en cas
     * d'échec (l'ancienne liste des autres machines est alors gardée).
     */
    suspend fun rafraichirMachines(): com.mawena.ccs.reseau.ListeMachines? {
        val r = kotlinx.coroutines.withTimeoutOrNull(15_000) {
            runCatching { depot.client.appeler("machines.list", com.mawena.ccs.reseau.ListeMachines.serializer()) }.getOrNull()
        } ?: return null
        val autres = r.autres
        val memes = autres.map { it.id to it.name } == _machines.value.map { it.id to it.name }
        _machines.value = autres
        // relu toutes les 5 s par l'onglet Réseau : écrit seulement quand la liste change
        if (!memes) depot.prefs.ecrire(
            CLE_MACHINES,
            com.mawena.ccs.reseau.CodecRpc.json.encodeToString(
                kotlinx.serialization.builtins.ListSerializer(com.mawena.ccs.reseau.Machine.serializer()), autres,
            ),
        )
        return r
    }

    /** Sessions des autres machines (`machines.chats`), seulement quand le serveur est piloté. */
    private val _autresSessions = MutableStateFlow<List<com.mawena.ccs.reseau.SessionsMachine>>(emptyList())
    val autresSessions: StateFlow<List<com.mawena.ccs.reseau.SessionsMachine>> = _autresSessions.asStateFlow()
    private var travailAutres: kotlinx.coroutines.Job? = null

    /**
     * Relit en arrière-plan les sessions des autres machines (plusieurs secondes : ssh vers
     * chacune). Rien si une autre machine est pilotée (les requêtes lui sont relayées) ; un échec
     * (ancien serveur sans la méthode…) vide la liste.
     */
    fun rafraichirAutresSessions() {
        travailAutres?.cancel()
        if (machine.value.isNotEmpty()) {
            _autresSessions.value = emptyList()
            return
        }
        travailAutres = viewModelScope.launch {
            val r = runCatching {
                com.mawena.ccs.reseau.CodecRpc.json.decodeFromJsonElement(
                    com.mawena.ccs.reseau.SessionsMachines.serializer(),
                    depot.client.appeler("machines.chats", delaiMs = 60_000),
                )
            }.getOrNull()
            if (!isActive) return@launch   // relancé entre-temps : le nouvel appel décidera
            // machine changée pendant l'appel : ces sessions sont maintenant celles d'ailleurs
            _autresSessions.value = if (machine.value.isEmpty()) r?.machines.orEmpty() else emptyList()
        }
    }

    /**
     * Pilote la machine `id`, attend que la connexion relayée soit prête (30 s au plus) ; rend
     * false si elle ne l'est pas à temps.
     */
    suspend fun piloterEtAttendre(id: String, nom: String): Boolean {
        choisirMachine(id, nom)
        _autresSessions.value = emptyList()
        return kotlinx.coroutines.withTimeoutOrNull(30_000) {
            kotlinx.coroutines.flow.combine(machine, etat) { m, e -> m == id && e is EtatConnexion.Connecte }
                .first { it }
        } ?: false
    }

    /** Pilote `id` (vide : ce serveur) : les terminaux de l'ancienne machine sont oubliés. */
    fun choisirMachine(id: String, nom: String) {
        if (id == machine.value) return
        depot.terminaux.oublier()
        depot.client.changerMachine(id, nom)
    }

    /**
     * Lien `ccs://root?machine=…` (avis ntfy d'une demande root) ou notification locale : pilote la
     * machine qui demande si ce n'est pas celle en cours, puis relit `root.status` (la fenêtre
     * s'affiche avec la demande en cours ; après un changement, la connexion la relit d'elle-même).
     */
    fun ouvrirRoot(machineLien: String?) {
        viewModelScope.launch {
            if (!machineLien.isNullOrBlank()) {
                val liste = kotlinx.coroutines.withTimeoutOrNull(10_000) {
                    runCatching { depot.client.appeler("machines.list", com.mawena.ccs.reseau.ListeMachines.serializer()) }.getOrNull()
                }?.machines ?: _machines.value
                val cible = com.mawena.ccs.logique.Root.cibleLien(machineLien, machine.value, liste)
                if (cible != null) {
                    choisirMachine(cible.first, cible.second)
                    return@launch
                }
            }
            depot.root.actualiser()
        }
    }

    fun changerTheme(t: com.mawena.ccs.donnees.Theme) {
        depot.reglages.theme = t
        _theme.value = t
    }

    init {
        val i = _identifiants.value
        if (i != null && depot.client.etat.value is EtatConnexion.Arrete) {
            if (i.portier) {
                // connexion Portier d'avant le jeton d'appareil : on le demande une fois, avant le WebSocket
                viewModelScope.launch {
                    val jeton = kotlinx.coroutines.withTimeoutOrNull(10_000) { depot.api.jetonAppli(i, nomModele()) }
                    val j = if (jeton != null) i.copy(jeton = jeton).also { depot.coffre.ecrire(it); _identifiants.value = it } else i
                    if (_identifiants.value != null && depot.client.etat.value is EtatConnexion.Arrete) depot.client.demarrer(j)
                }
            } else {
                depot.client.demarrer(i)
            }
        }
        viewModelScope.launch {
            depot.client.etat.collect {
                if (it is EtatConnexion.Connecte) launch { rafraichirMachines() }
                if (it is EtatConnexion.Refuse) {
                    oublier()
                    _avis.value = "${it.raison} Reconnecte-toi."
                }
            }
        }
    }

    fun connecte(i: Identifiants) {
        depot.coffre.ecrire(i)
        _identifiants.value = i
        _avis.value = null
        depot.client.demarrer(i)
        com.mawena.ccs.notif.ServiceVeille.appliquer(getApplication())
    }

    fun deconnecter() {
        val portier = _identifiants.value?.viaPortier == true
        viewModelScope.launch {
            // le pont oublie ce téléphone comme sortie et source de son (avant de couper)
            depot.son.partir()
            oublier()
            if (portier) CookieManager.getInstance().removeAllCookies(null)
        }
    }

    private fun oublier() {
        depot.jarvis.fermer()
        depot.terminaux.oublier()
        fichiers.fermer()
        depot.client.arreter()
        depot.coffre.ecrire(null)
        _identifiants.value = null
        com.mawena.ccs.notif.ServiceVeille.appliquer(getApplication())
        androidx.core.app.NotificationManagerCompat.from(getApplication()).cancelAll()
    }

    /** Rend false si l'adresse est invalide. */
    fun changerAdresse(texte: String): Boolean {
        val nouvelle = depot.adresse.ecrire(texte) ?: return false
        _adresse.value = nouvelle
        return true
    }

    fun avisLu() {
        _avis.value = null
    }

    private companion object {
        const val CLE_MACHINES = "machines"
    }
}
