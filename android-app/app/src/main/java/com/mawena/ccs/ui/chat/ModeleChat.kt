package com.mawena.ccs.ui.chat

import android.graphics.Bitmap
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.mawena.ccs.Depot
import com.mawena.ccs.logique.ActionNote
import com.mawena.ccs.logique.AlerteContexte
import com.mawena.ccs.logique.Citation
import com.mawena.ccs.logique.CommandeSlash
import com.mawena.ccs.logique.Consommation
import com.mawena.ccs.logique.Effet
import com.mawena.ccs.logique.ElementFil
import com.mawena.ccs.logique.EntreeEtiquettes
import com.mawena.ccs.logique.Envoi
import com.mawena.ccs.logique.EvChat
import com.mawena.ccs.logique.FilChat
import com.mawena.ccs.logique.LigneFil
import com.mawena.ccs.logique.ModeleIa
import com.mawena.ccs.logique.NiveauContexte
import com.mawena.ccs.logique.Tache
import com.mawena.ccs.logique.Vocal
import com.mawena.ccs.logique.VueAgent
import com.mawena.ccs.reseau.ChatOuvert
import com.mawena.ccs.reseau.CodecRpc
import com.mawena.ccs.reseau.Cout
import com.mawena.ccs.reseau.Messages
import com.mawena.ccs.reseau.OptionsChat
import com.mawena.ccs.reseau.RpcException
import com.mawena.ccs.ui.DestChat
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject

/** Image jointe au prochain message. */
class PieceJointe(val typeMedia: String, val base64: String, val apercu: Bitmap?, val nom: String)

/** Ce que montre l'écran du chat, publié au plus toutes les 40 ms pendant une réponse. */
data class VueChat(
    val lignes: List<LigneFil> = emptyList(),
    val agents: List<VueAgent> = emptyList(),
    val agentVu: String? = null,
    val lignesAgent: List<LigneFil> = emptyList(),
    val taches: List<Tache> = emptyList(),
    val etat: String = "starting",
    val reflechit: Boolean = false,
    val contexte: String = "",
    val niveauContexte: NiveauContexte? = null,  // couleur de « Contexte … » (seuil de l'alerte)
    val cout: String = "",
    val historiqueComplet: Boolean = true,
    val ouverture: String? = null,              // erreur d'ouverture (chat.open refusé)
    val pret: Boolean = false,                  // chat ouvert et rattaché une fois
)

/** Options du chat telles que l'écran les montre ; `pretes` : les vraies options sont connues. */
data class ReglagesChat(
    val options: OptionsChat = OptionsChat(),
    val pretes: Boolean = false,
    val modeles: List<ModeleIa> = emptyList(),
)

/**
 * Un chat ouvert (`ChatView` de `web/chat.js`) : ouverture ou reprise (`chat.open`), rattachement
 * numéroté (`chat.attach` depuis le dernier numéro, après chaque reconnexion), historique du
 * journal, envoi, autorisations, questions, commandes `!`, étiquettes, contexte et coût. Gardé
 * par l'entrée de navigation : il survit à une rotation de l'écran.
 */
class ModeleChat(private val depot: Depot, private val dest: DestChat) : ViewModel() {
    private val client = depot.client
    private val fil = FilChat()

    var chatId: String? = dest.chatId; private set
    private val _idChat = MutableStateFlow(dest.chatId)
    /** Identifiant du chat dans le pont, connu après l'ouverture (chat affiché, pour les notifications). */
    val idChat: StateFlow<String?> = _idChat.asStateFlow()
    var cwd: String = dest.cwd; private set
    private var chemin: String? = dest.chemin
    private var historique: Historique? = dest.chemin?.let { Historique(it) }
    private var sessionVue: String? = null                 // session vue par le pont (une reprise peut en changer)
    private val verrouAttache = Mutex()
    private var mort = false

    private class Historique(val chemin: String) {
        var demarre = false
        var avant: Double? = null
        var charges = 0
        var complet = false
    }

    /** Cache expiré : tokens que relirait le message en attente de confirmation (null : rien à confirmer). */
    private val _confirmationCache = MutableStateFlow<Long?>(null)
    val confirmationCache: StateFlow<Long?> = _confirmationCache.asStateFlow()

    private val _vue = MutableStateFlow(VueChat())
    val vue: StateFlow<VueChat> = _vue.asStateFlow()

    /** Fichiers du projet (`work.files`, chemins relatifs) : liens des chemins cités par Claude. */
    private val _fichiers = MutableStateFlow<Set<String>>(emptySet())
    val fichiers: StateFlow<Set<String>> = _fichiers.asStateFlow()

    /** Relit la liste des fichiers du projet (après un tour : Claude a pu en créer). */
    fun chargerFichiers() {
        val id = chatId ?: return
        viewModelScope.launch {
            runCatching {
                client.appeler("work.files", com.mawena.ccs.reseau.IndexFichiers.serializer(), buildJsonObject { put("chat_id", id) })
            }.onSuccess { _fichiers.value = it.files.toSet() }
        }
    }

    private val _reglages = MutableStateFlow(ReglagesChat())
    val reglages: StateFlow<ReglagesChat> = _reglages.asStateFlow()

    private val _citation = MutableStateFlow<Citation.Cite?>(null)
    val citation: StateFlow<Citation.Cite?> = _citation.asStateFlow()

    private val _images = MutableStateFlow<List<PieceJointe>>(emptyList())
    val images: StateFlow<List<PieceJointe>> = _images.asStateFlow()

    private val _saisie = MutableStateFlow(depot.prefs.lire(cleBrouillon()).orEmpty())
    val saisie: StateFlow<String> = _saisie.asStateFlow()

    private val _envoi = MutableStateFlow(false)
    val envoiEnCours: StateFlow<Boolean> = _envoi.asStateFlow()

    private val _etiquettes = MutableStateFlow<Map<String, EntreeEtiquettes>>(emptyMap())
    val etiquettes: StateFlow<Map<String, EntreeEtiquettes>> = _etiquettes.asStateFlow()
    var connues: List<String> = emptyList(); private set
    private var sessionEtiquettes: String? = null

    private val _commandes = MutableStateFlow<List<CommandeSlash>>(emptyList())
    val commandes: StateFlow<List<CommandeSlash>> = _commandes.asStateFlow()

    /** Messages courts pour l'utilisateur (texte, et action « Réessayer » éventuelle). */
    class Message(val texte: String, val action: String? = null, val faire: (() -> Unit)? = null)
    private val _messages = MutableSharedFlow<Message>(extraBufferCapacity = 8, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val messages: SharedFlow<Message> = _messages.asSharedFlow()

    /** Lecture à voix haute des réponses (« Lire », et chaque fin de tour si le réglage est actif). */
    val lecteur = Lecteur(depot.appli) { dire(it) }

    /** Chat affiché (écran au premier plan) : la lecture automatique ne parle que dans ce cas. */
    @Volatile var aLEcran = false

    private val shells = HashMap<String, String>()          // run_id → clé de la carte
    private val shellsTot = HashMap<String, JsonObject>()   // fins arrivées avant la réponse du pont
    private val notesShell = ArrayList<String>()
    private var lourd = false
    private var reglagesContexte: Pair<Boolean, Long>? = null
    private var publication: Job? = null
    private var contexteJob: Job? = null
    private var agentVu: String? = null

    init {
        loadCitation()
        viewModelScope.launch {
            client.evenements("chat.event").collect { d ->
                if (d.texte("chat_id") == chatId && chatId != null) recevoir(d)
            }
        }
        viewModelScope.launch {
            client.evenements("chat.tags").collect { d ->
                val sid = d.texte("session_id")
                if (sid.isNotEmpty() && sid == fil.sessionId) appliquerEtiquette(d.texte("msg_id"), EvChat.etiquettes(d["entry"]))
            }
        }
        viewModelScope.launch {
            client.evenements("shell.done").collect { d -> if (d.texte("chat_id") == chatId) finShell(d) }
        }
        viewModelScope.launch {
            client.reconnexions.collect { attacher(); sonderShells() }
        }
        viewModelScope.launch {
            ouvrir()
            envoyerPrevu()
        }
        // partage Android vers ce chat : texte ajouté à la saisie, images jointes
        viewModelScope.launch {
            kotlinx.coroutines.flow.combine(depot.remises, _idChat) { m, id -> m to id }.collect { (m, id) ->
                if (id == null) return@collect
                if (id in m) depot.prendreRemise(id)?.let { r ->
                    if (r.texte.isNotEmpty()) saisir(com.mawena.ccs.logique.AnalysePartage.composer(_saisie.value, r.texte, emptyList()))
                    r.images.forEach { joindre(it) }
                }
            }
        }
    }

    /**
     * Texte prévu à l'ouverture (« Faire… » d'une tâche de la feuille de route dans un nouveau
     * chat) : envoyé une seule fois, même si l'écran est recréé.
     */
    private suspend fun envoyerPrevu() {
        val texte = dest.aEnvoyer ?: return
        val cle = "envoye:${dest.jeton}"
        if (chatId == null || depot.prefs.lire(cle) != null) return
        depot.prefs.ecrire(cle, "1")
        livrer(texte, emptyList(), null) { envoyerTexte(texte) }
    }

    override fun onCleared() {
        mort = true
        lecteur.fermer()
        sauverBrouillon()
    }

    // ---- ouverture et rattachement ---------------------------------------------------------------

    /** Conversation de l'historique sans chat dans le pont : on la reprend (`chat.open`), comme le web. */
    private suspend fun ouvrir() {
        if (chatId == null) {
            try {
                val r = client.appeler("chat.open", ChatOuvert.serializer(), buildJsonObject {
                    put("cwd", cwd)
                    dest.sessionId?.let { put("session_id", it) }
                })
                adopter(r)
            } catch (e: Exception) {
                _vue.value = _vue.value.copy(ouverture = e.message ?: "Ouverture impossible.")
                return
            }
        }
        attacher()
    }

    private fun adopter(r: ChatOuvert) {
        chatId = r.chatId
        _idChat.value = r.chatId
        if (r.cwd.isNotEmpty()) cwd = r.cwd
        if (chemin == null && r.path != null) { chemin = r.path; if (historique == null) historique = Historique(r.path) }
        fil.definirSession(r.sessionId ?: dest.sessionId)
        r.options?.let { appliquerOptions(it) }
        if (r.seq == 0L) fil.changerEtat("starting")
    }

    fun reessayerOuverture() {
        _vue.value = _vue.value.copy(ouverture = null)
        viewModelScope.launch { ouvrir() }
    }

    /** Les rattachements se font l'un après l'autre (ouverture puis reconnexion rapprochées). */
    fun attacher() {
        viewModelScope.launch { verrouAttache.withLock { rattacher() } }
    }

    private suspend fun demanderAttache(depuis: Long): JsonObject? {
        val id = chatId ?: return null
        return try {
            client.appeler("chat.attach", buildJsonObject { put("chat_id", id); put("since", depuis) }).jsonObject
        } catch (e: RpcException) {
            if (e.code == "introuvable") perdu() else if (e.code != "hors_ligne") fil.note(e.message ?: "Erreur.", "error").also { publier() }
            null
        }
    }

    private suspend fun rattacher() {
        if (mort || chatId == null) return
        var r = demanderAttache(fil.seq) ?: return
        val seqPont = (r["seq"] as? JsonPrimitive)?.longOrNull
        val sid = r.texte("session_id")
        val enRetard = seqPont != null && seqPont < fil.seq
        val autre = sid.isNotEmpty() && sessionVue != null && sid != sessionVue
        if (enRetard || autre) {
            remettreAZero(autre)
            r = demanderAttache(0) ?: return
        }
        if (sid.isNotEmpty()) { fil.definirSession(sid); sessionVue = sid; chargerEtiquettes() }
        r.texte("path").takeIf { it.isNotEmpty() }?.let { p ->
            if (chemin == null) chemin = p
            if (historique == null && !autre) historique = Historique(p)
        }
        (r["options"] as? JsonObject)?.let { appliquerOptions(CodecRpc.json.decodeFromJsonElement(OptionsChat.serializer(), it)) }
            ?: if (!_reglages.value.pretes) _reglages.value = _reglages.value.copy(pretes = true) else Unit
        fil.repris()
        for (item in (r["events"] as? JsonArray).orEmpty()) (item as? JsonObject)?.let { traiter(it) }
        fil.changerEtat(r.texte("state"))
        _vue.value = _vue.value.copy(pret = true)
        publier(tout = true)
        demarrerHistorique((r["history_before"] as? JsonPrimitive)?.doubleOrNull)
    }

    private fun remettreAZero(nouvelleSession: Boolean) {
        sessionVue = null
        fil.remettreAZero()
        shells.clear(); shellsTot.clear()
        agentVu = null
        lourd = false
        historique = if (nouvelleSession) null else historique?.let { Historique(it.chemin) }
    }

    /** Le pont ne connaît plus ce chat (redémarrage) : carte « Reprendre la conversation ». */
    private fun perdu() {
        demarrerHistoriqueSansAttendre()
        fil.arrete(reprenable = fil.sessionId != null)
        publier(tout = true)
    }

    fun reprendre() {
        val sid = fil.sessionId ?: return
        viewModelScope.launch {
            try {
                val r = client.appeler("chat.open", ChatOuvert.serializer(), buildJsonObject { put("cwd", cwd); put("session_id", sid) })
                fil.repris()
                remettreAZero(false)
                historique = (r.path ?: chemin)?.let { Historique(it) }
                adopter(r)
                verrouAttache.withLock { rattacher() }
            } catch (e: Exception) {
                _messages.tryEmit(Message(e.message ?: "Reprise impossible.", "Réessayer") { reprendre() })
            }
        }
    }

    // ---- événements --------------------------------------------------------------------------

    private fun recevoir(d: JsonObject) {
        traiter(d, direct = true)
        publier()
    }

    /** `direct` : événement reçu en direct (pas rejoué par un rattachement ou l'historique). */
    private fun traiter(item: JsonObject, direct: Boolean = false) {
        val ev = (item["event"] as? JsonObject)?.let(EvChat::lire) ?: return
        val numero = (item["seq"] as? JsonPrimitive)?.longOrNull ?: 0L
        val effets = fil.recevoir(numero, ev)
        if (ev is EvChat.EtiquettesChangees && ev.sessionId == fil.sessionId) appliquerEtiquette(ev.msgId, ev.entree)
        if (ev is EvChat.Statut && fil.droitsAnnonces != null) {
            _reglages.value = _reglages.value.let { it.copy(options = it.options.copy(rights = fil.droitsAnnonces!!)) }
        }
        for (e in effets) when (e) {
            Effet.SessionConnue -> { sessionVue = fil.sessionId; chargerEtiquettes() }
            Effet.NouveauHello -> {
                _reglages.value = _reglages.value.copy(modeles = fil.modeles)
                if (fil.commandes.isNotEmpty()) _commandes.value = fil.commandes
            }
            Effet.DemanderContexte -> demanderContexte()
            Effet.TourFini -> {
                lireCout()
                if (direct && ev is EvChat.Tour && ev.ok && !ev.interrompu) lireFinDeTour()
            }
            Effet.MesureContexte -> fil.contexte?.let { verifierContexte(it) }
            Effet.AutorisationArrivee -> agentVu = null       // la demande est dans le fil : on y revient
        }
    }

    /** Publie la vue ; pendant une réponse, au plus toutes les 40 ms (un seul calcul pour plusieurs morceaux). */
    private fun publier(tout: Boolean = false) {
        if (tout) { publication?.cancel(); publication = null; calculer(); return }
        if (publication != null) return
        publication = viewModelScope.launch {
            delay(40)
            publication = null
            calculer()
        }
    }

    private fun calculer() {
        val c = fil.contexte
        val usage = fil.dernierUsage?.takeIf { it.contexte > 0 }
        val tokens = c?.total ?: usage?.contexte
        _vue.value = _vue.value.copy(
            lignes = LigneFil.de(fil.fil.elements),
            agents = fil.vuesAgents,
            agentVu = agentVu,
            lignesAgent = agentVu?.let { LigneFil.de(fil.filAgent(it)) } ?: emptyList(),
            taches = fil.taches,
            etat = fil.etat,
            reflechit = fil.reflechit,
            contexte = when {
                c != null -> "Contexte ${c.pourcentage} %"
                usage != null -> "Contexte ${Consommation.jetons(usage.contexte)}"
                else -> ""
            },
            niveauContexte = tokens?.let { Consommation.niveau(it, Consommation.seuil(reglagesContexte?.second)) },
            historiqueComplet = historique?.complet ?: true,
        )
    }

    fun voirAgent(id: String?) {
        agentVu = id
        publier(tout = true)
    }

    // ---- historique --------------------------------------------------------------------------

    private fun demarrerHistoriqueSansAttendre() {
        val h = historique ?: return
        if (h.demarre) return
        viewModelScope.launch { demarrerHistorique(null) }
    }

    private suspend fun demarrerHistorique(avant: Double?) {
        val h = historique ?: return
        if (h.demarre) return
        h.demarre = true
        h.avant = avant
        val r = lireHistorique(h, LIMITE) ?: run { h.demarre = false; return }
        if (historique !== h) return
        h.charges = r.size
        h.complet = r.size < LIMITE
        fil.prefixerHistorique(r)
        publier(tout = true)
    }

    private suspend fun lireHistorique(h: Historique, limite: Int) = try {
        client.appeler("conversations.messages", Messages.serializer(), buildJsonObject {
            put("path", h.chemin)
            put("limit", limite)
            h.avant?.let { put("before", it) }
        }).messages
    } catch (e: RpcException) {
        if (e.code == "introuvable") emptyList() else null      // chat neuf : pas encore de journal
    } catch (e: Exception) {
        null
    }

    /** Pour la recherche et les étiquettes : ajoute les messages plus anciens que les 200 derniers. */
    suspend fun chargerToutHistorique() {
        val h = historique ?: return
        if (h.complet || !h.demarre) return
        h.complet = true
        val r = lireHistorique(h, 100_000) ?: run { h.complet = false; return }
        if (historique !== h) return
        fil.prefixerHistorique(r.take(maxOf(0, r.size - h.charges)))
        h.charges = r.size
        publier(tout = true)
    }

    fun chargerPlus() { viewModelScope.launch { chargerToutHistorique() } }

    // ---- options -------------------------------------------------------------------------------

    private fun appliquerOptions(o: OptionsChat) {
        val droits = if (o.rights == "default") "manual" else o.rights.ifEmpty { "manual" }
        _reglages.value = _reglages.value.copy(options = o.copy(rights = droits), pretes = true)
    }

    fun changerOptions(o: OptionsChat) {
        if (!_reglages.value.pretes) return
        _reglages.value = _reglages.value.copy(options = o)
        appel("chat.options", buildJsonObject {
            putJsonObject("options") {
                put("model", o.model)
                put("effort", o.effort)
                put("ultracode", o.ultracode)
                put("rights", o.rights)
            }
        })
    }

    // ---- saisie, citation, images ----------------------------------------------------------------

    private fun cleBrouillon() = "brouillon:$cwd|${dest.sessionId ?: dest.chatId ?: ""}"
    private fun cleCitation() = "citation:$cwd|${dest.sessionId ?: dest.chatId ?: ""}"

    private var brouillonJob: Job? = null
    fun saisir(t: String) {
        _saisie.value = t
        brouillonJob?.cancel()
        brouillonJob = viewModelScope.launch { delay(300); sauverBrouillon() }
        if (t.startsWith("/") && _commandes.value.isEmpty()) chargerCommandes()
    }

    private fun sauverBrouillon() = depot.prefs.ecrire(cleBrouillon(), _saisie.value.ifEmpty { null })

    fun citer(c: Citation.Cite?) {
        _citation.value = c
        depot.prefs.ecrire(cleCitation(), c?.let { "${it.auteur.cle}\n${it.texte}" })
    }

    private fun loadCitation() {
        val brut = depot.prefs.lire(cleCitation()) ?: return
        val auteur = Citation.Auteur.entries.firstOrNull { it.cle == brut.substringBefore('\n') } ?: return
        val texte = brut.substringAfter('\n', "")
        if (texte.isNotEmpty()) _citation.value = Citation.Cite(auteur, texte)
    }

    fun joindre(p: PieceJointe) { if (_images.value.size < MAX_IMAGES) _images.value = _images.value + p }
    fun retirerImage(p: PieceJointe) { _images.value = _images.value - p }
    fun dire(texte: String) { _messages.tryEmit(Message(texte)) }

    // ---- vocal -----------------------------------------------------------------------------------

    /** « Lire » sur une réponse : la lit, ou arrête si elle est déjà en cours de lecture. */
    fun basculerLecture(cle: String, texte: String) = lecteur.basculer(cle, texte)

    fun arreterLecture() = lecteur.arreter()

    /** Fin de tour : lit la dernière réponse si le réglage « Lire les réponses » est actif et le chat affiché. */
    private fun lireFinDeTour() {
        if (!aLEcran || !depot.reglages.lireReponses) return
        Vocal.derniereReponse(fil.fil.elements)?.let { lecteur.lire(it.cle, it.texte) }
    }

    private var commandesJob: Job? = null
    private fun chargerCommandes() {
        val id = chatId ?: return
        if (commandesJob?.isActive == true) return
        commandesJob = viewModelScope.launch {
            runCatching { client.appeler("work.commands", buildJsonObject { put("chat_id", id) }).jsonObject }.getOrNull()?.let { r ->
                lireReglagesContexte(r)
                _commandes.value = (r["commands"] as? JsonArray).orEmpty().mapNotNull { c ->
                    (c as? JsonObject)?.let { CommandeSlash(it.texte("name"), it.texte("description"), it.texte("hint")) }
                }.filter { it.nom.isNotEmpty() }
            }
        }
    }

    // ---- envoi -----------------------------------------------------------------------------------

    /** Bouton Envoyer : commande `!`, sinon message (avec images et citation). */
    fun envoyer(forcer: Boolean = false) {
        _confirmationCache.value = null
        val texte = _saisie.value.trim()
        val imgs = _images.value
        if ((texte.isEmpty() && imgs.isEmpty()) || _envoi.value) return
        Envoi.commandeShell(texte, imgs.size)?.let { cmd ->
            saisir("")
            lancerShell(cmd)
            return
        }
        if (!forcer) Consommation.confirmationCache(texte, fil.cacheExpire)?.let { _confirmationCache.value = it; return }
        _envoi.value = true
        viewModelScope.launch {
            try {
                val cite = _citation.value
                if (livrer(texte, imgs, cite) { envoyer() }) {
                    _images.value = _images.value - imgs.toSet()
                    if (_citation.value == cite && !(Envoi.estCommandeSlash(texte) && imgs.isEmpty())) citer(null)
                    if (_saisie.value.trim() == texte) saisir("")
                }
            } finally {
                _envoi.value = false
            }
        }
    }

    /** Confirmation du cache expiré : « Compacter d'abord » (le message reste dans la saisie). */
    fun compacterDabord() {
        _confirmationCache.value = null
        envoyerTexte("/compact")
    }

    fun annulerConfirmation() { _confirmationCache.value = null }

    /** Texte préparé ailleurs (bouton « Compacter ») : envoyé sans toucher à la saisie. */
    fun envoyerTexte(texte: String) { viewModelScope.launch { livrer(texte, emptyList(), null) { envoyerTexte(texte) } } }

    private suspend fun livrer(texte: String, imgs: List<PieceJointe>, cite: Citation.Cite?, reessai: () -> Unit): Boolean {
        val id = chatId ?: run { _messages.tryEmit(Message("Le chat n'est pas encore ouvert.")); return false }
        val pret = Envoi.preparer(texte, imgs.size, cite, notesShell)
        val nonce = "${System.currentTimeMillis().toString(36)}-${(Math.random() * 1e9).toLong().toString(36)}"
        val uuid = Envoi.nouvelUuid()
        fil.retenirEnvoi(nonce)
        val r = try {
            client.appeler("chat.send", buildJsonObject {
                put("chat_id", id)
                put("text", pret.envoye)
                put("shown", pret.montre)
                put("nonce", nonce)
                put("uuid", uuid)
                putJsonArray("images") {
                    imgs.forEach { add(buildJsonObject { put("media_type", it.typeMedia); put("data", it.base64) }) }
                }
            }, delaiMs = 60_000).jsonObject
        } catch (e: Exception) {
            fil.oublierEnvoi(nonce)
            _messages.tryEmit(Message("Le message n'est pas parti : ${e.message}", "Réessayer", reessai))
            return false
        }
        if ((r["ok"] as? JsonPrimitive)?.booleanOrNull != true) {
            fil.oublierEnvoi(nonce)
            _messages.tryEmit(Message("Le message n'est pas parti : Claude n'a pas pu démarrer.", "Réessayer", reessai))
            return false
        }
        if (!pret.commande) notesShell.clear()
        agentVu = null
        fil.bulleToi(pret.montre, imgs.size, r.texte("uuid"))
        publier(tout = true)
        return true
    }

    fun interrompre() = appel("chat.interrupt")

    fun repondre(requestId: String, decision: String, motif: String = "") =
        appel("chat.answer", buildJsonObject { put("request_id", requestId); put("decision", decision); put("message", motif) })

    /** Réponses aux questions de Claude : question → texte, ou liste (choix multiple). */
    fun repondreQuestions(requestId: String, reponses: Map<String, Any>) =
        appel("chat.questions", buildJsonObject {
            put("request_id", requestId)
            putJsonObject("answers") {
                for ((q, r) in reponses) {
                    if (r is List<*>) put(q, buildJsonArray { r.forEach { add(JsonPrimitive(it.toString())) } })
                    else put(q, r.toString())
                }
            }
        })

    private fun appel(methode: String, params: JsonObject = JsonObject(emptyMap())) {
        val id = chatId ?: return
        viewModelScope.launch {
            try {
                client.appeler(methode, JsonObject(params + ("chat_id" to JsonPrimitive(id))))
            } catch (e: Exception) {
                fil.note(e.message ?: "Erreur.", "error")
                publier()
            }
        }
    }

    // ---- commandes `!` ----------------------------------------------------------------------------

    private fun lancerShell(commande: String) {
        val id = chatId ?: return
        val cle = fil.commande(commande)
        publier(tout = true)
        viewModelScope.launch {
            val r = try {
                client.appeler("shell.run", buildJsonObject { put("chat_id", id); put("command", commande) }).jsonObject
            } catch (e: Exception) {
                terminerShell(cle, commande, 127, e.message ?: "Erreur.", false)
                return@launch
            }
            val run = r.texte("run_id")
            shells[run] = cle
            fil.majCommande(cle) { it.copy(runId = run) }
            publier()
            shellsTot.remove(run)?.let { finShell(it) }
        }
    }

    fun arreterShell(runId: String) {
        viewModelScope.launch { runCatching { client.appeler("shell.stop", buildJsonObject { put("run_id", runId) }) } }
    }

    private fun finShell(d: JsonObject) {
        val run = d.texte("run_id")
        val cle = shells.remove(run) ?: run { shellsTot[run] = d; return }
        val cmd = (fil.fil[cle] as? ElementFil.Commande)?.commande.orEmpty()
        terminerShell(cle, cmd, (d["code"] as? JsonPrimitive)?.longOrNull?.toInt() ?: -1, d.texte("output"),
            (d["truncated"] as? JsonPrimitive)?.booleanOrNull ?: false)
    }

    private fun terminerShell(cle: String, commande: String, code: Int, sortie: String, tronquee: Boolean) {
        fil.majCommande(cle) { it.copy(code = code, sortie = (sortie + if (tronquee) "\n[sortie tronquée]" else "").ifEmpty { "(aucune sortie)" }) }
        notesShell.add(Envoi.noteShell(commande, code, sortie, tronquee))
        publier()
    }

    private suspend fun sonderShells() {
        for (run in shells.keys.toList()) {
            val r = runCatching { client.appeler("shell.poll", buildJsonObject { put("run_id", run) }).jsonObject }.getOrNull() ?: continue
            if ((r["done"] as? JsonPrimitive)?.booleanOrNull == true) finShell(r)
        }
    }

    // ---- contexte et coût -----------------------------------------------------------------------------

    /** « Contexte N % » n'arrive qu'en réponse à chat.context : on le demande après chaque tour. */
    private fun demanderContexte() {
        contexteJob?.cancel()
        contexteJob = viewModelScope.launch {
            delay(400)
            if (fil.etat != "stopped") appel("chat.context")
        }
    }

    private fun lireReglagesContexte(r: JsonObject) {
        val c = r["context"] as? JsonObject ?: return
        reglagesContexte = ((c["enabled"] as? JsonPrimitive)?.booleanOrNull ?: false) to
            ((c["threshold_tokens"] as? JsonPrimitive)?.longOrNull ?: 0L)
    }

    private fun verifierContexte(ev: EvChat.Contexte) {
        viewModelScope.launch {
            if (reglagesContexte == null) {
                val id = chatId ?: return@launch
                runCatching { client.appeler("work.commands", buildJsonObject { put("chat_id", id) }).jsonObject }.getOrNull()?.let { lireReglagesContexte(it) }
            }
            val (actif, seuil) = reglagesContexte ?: return@launch
            val d = AlerteContexte.decider(ev, actif, seuil, lourd)
            lourd = d.lourd
            d.gain?.let { gain ->
                fil.note("Contexte lourd : ${fr(ev.total)} jetons. Compacter libérerait environ ${fr(gain)} jetons (estimation).", "warning", ActionNote.Compacter)
                publier()
            }
        }
    }

    private fun lireCout() {
        viewModelScope.launch {
            if (chemin == null) {
                // chat neuf : le journal existe depuis le premier tour, le pont donne son chemin
                demanderAttache(fil.seq)?.texte("path")?.takeIf { it.isNotEmpty() }?.let { chemin = it; if (historique == null) historique = Historique(it).also { h -> h.demarre = true; h.complet = true } }
            }
            val p = chemin ?: return@launch
            val c = runCatching { client.appeler("conversations.cost", Cout.serializer(), buildJsonObject { put("path", p) }) }.getOrNull() ?: return@launch
            _vue.value = _vue.value.copy(cout = c.short)
        }
    }

    // ---- étiquettes ------------------------------------------------------------------------------------

    private fun chargerEtiquettes() {
        val sid = fil.sessionId ?: return
        if (sid == sessionEtiquettes) return
        sessionEtiquettes = sid
        viewModelScope.launch {
            val r = runCatching { client.appeler("chat.tags", buildJsonObject { put("session_id", sid) }).jsonObject }.getOrNull() ?: return@launch
            if (fil.sessionId != sid) return@launch
            _etiquettes.value = (r["messages"] as? JsonObject).orEmpty().mapNotNull { (k, v) -> EvChat.etiquettes(v)?.let { k to it } }.toMap()
            connues = (r["known"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
        }
    }

    private fun appliquerEtiquette(msgId: String, e: EntreeEtiquettes?) {
        if (msgId.isEmpty()) return
        _etiquettes.value = if (e != null) _etiquettes.value + (msgId to e) else _etiquettes.value - msgId
        if (e != null) {
            val vues = connues.map { it.lowercase() }.toSet()
            connues = connues + e.etiquettes.filter { it.lowercase() !in vues }
        }
    }

    val sessionId: String? get() = fil.sessionId

    fun etiqueter(msgId: String, etiquettes: List<String>, texte: String, role: String) {
        val sid = fil.sessionId ?: return
        viewModelScope.launch {
            try {
                val r = client.appeler("chat.tag", buildJsonObject {
                    put("session_id", sid); put("msg_id", msgId); put("text", texte); put("role", role)
                    putJsonArray("tags") { etiquettes.forEach { add(JsonPrimitive(it)) } }
                }).jsonObject
                if (fil.sessionId == sid) appliquerEtiquette(msgId, EvChat.etiquettes(r["entry"]))
            } catch (e: Exception) {
                _messages.tryEmit(Message("Étiquettes non enregistrées : ${e.message}"))
            }
        }
    }

    companion object {
        const val LIMITE = 200
        const val MAX_IMAGES = 5
        private fun fr(n: Long) = String.format(java.util.Locale.FRANCE, "%,d", n)
        private fun JsonObject.texte(cle: String) = (this[cle] as? JsonPrimitive)?.contentOrNull.orEmpty()
    }
}
