package com.mawena.ccs.terminal

import com.mawena.ccs.reseau.CcsClient
import com.mawena.ccs.reseau.InfoTerminal
import com.mawena.ccs.reseau.ListeTerminaux
import com.mawena.ccs.reseau.RpcException
import com.mawena.ccs.reseau.SortieTerminal
import com.mawena.ccs.reseau.TerminalOuvert
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.buffer
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.put

/**
 * Terminaux ouverts depuis l'appli (`web/terminal.js` + onglets de `web/sessions.js`) : ils
 * survivent à la navigation entre écrans. Les événements `term.output` et `term.exit` vont au bon
 * terminal ; après une reconnexion, chacun se rattache (`term.attach`) et réaffiche la fin de sa
 * sortie. La saisie part dans l'ordre (une file par terminal).
 */
class Terminaux(private val client: CcsClient) {
    private val portee by lazy { CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate) }
    private var ecoute: Job? = null

    private val _sessions = MutableStateFlow<List<SessionTerminal>>(emptyList())
    val sessions: StateFlow<List<SessionTerminal>> = _sessions.asStateFlow()

    /** Messages pour l'utilisateur (saisie perdue…), une fois toutes les 4 s au plus. */
    private val _avis = MutableSharedFlow<String>(extraBufferCapacity = 4)
    val avis: SharedFlow<String> = _avis.asSharedFlow()
    private var dernierAvis = 0L

    /** Sortie arrivée avant la réponse de `term.open` (identifiant pas encore connu). */
    private val enAvance = HashMap<String, StringBuilder>()
    private val files = HashMap<String, Channel<String>>()

    fun session(id: String): SessionTerminal? = _sessions.value.firstOrNull { it.id == id }

    private fun ecouter() {
        if (ecoute != null) return
        ecoute = portee.launch {
            launch {
                client.evenements.buffer(Channel.UNLIMITED).collect { e ->
                    val id = (e.donnees["term_id"] as? JsonPrimitive)?.contentOrNull ?: return@collect
                    when (e.nom) {
                        "term.output" -> {
                            val texte = (e.donnees["data"] as? JsonPrimitive)?.contentOrNull.orEmpty()
                            val s = session(id)
                            if (s != null) s.recevoir(texte)
                            else if (enAvance.size < 8) enAvance.getOrPut(id) { StringBuilder() }.let { if (it.length < 65_536) it.append(texte) }
                        }
                        "term.exit" -> session(id)?.terminer((e.donnees["code"] as? JsonPrimitive)?.intOrNull ?: 0)
                    }
                }
            }
            launch { client.reconnexions.collect { _sessions.value.forEach { rattacher(it) } } }
        }
    }

    private fun ajouter(s: SessionTerminal) {
        _sessions.value = _sessions.value.filter { it.id != s.id } + s
        val file = Channel<String>(Channel.UNLIMITED)
        files[s.id] = file
        portee.launch {
            for (d in file) {
                try {
                    client.appeler("term.input", buildJsonObject { put("term_id", s.id); put("data", d) })
                } catch (e: RpcException) {
                    if (e.code == "introuvable") s.terminer(-1) else dire("La saisie n'est pas partie : ${e.message}.")
                }
            }
        }
    }

    private fun dire(m: String) {
        val t = System.currentTimeMillis()
        if (t - dernierAvis < 4000) return
        dernierAvis = t
        _avis.tryEmit(m)
    }

    private fun nouvelle(id: String, nom: String, cwd: String, colonnes: Int, lignes: Int) =
        SessionTerminal(id, nom, cwd, { d -> entrer(id, d) }, colonnes, lignes)

    /**
     * Nouveau terminal dans `cwd` : le shell de l'utilisateur, ou une commande permise par le pont
     * (`ccs add` et son nom de compte).
     */
    suspend fun ouvrir(cwd: String, colonnes: Int = 80, lignes: Int = 24, commande: String? = null, nom: String? = null): SessionTerminal {
        ecouter()
        val r = client.appeler("term.open", TerminalOuvert.serializer(), buildJsonObject {
            put("cwd", cwd)
            put("cols", colonnes)
            put("rows", lignes)
            if (commande != null) { put("command", commande); put("name", nom.orEmpty()) }
        })
        val s = nouvelle(r.termId, if (commande != null) nom.orEmpty() else cwd.trimEnd('/').substringAfterLast('/').ifEmpty { "Terminal" }, cwd, colonnes, lignes)
        ajouter(s)
        enAvance.remove(r.termId)?.let { s.recevoir(it.toString()) }
        return s
    }

    /** Terminaux du pont (ceux de la version web compris). */
    suspend fun lister(): List<InfoTerminal> = client.appeler("term.list", ListeTerminaux.serializer()).terms

    /** Terminal connu du pont mais pas encore affiché ici : on s'y rattache. */
    suspend fun reprendre(info: InfoTerminal): SessionTerminal {
        ecouter()
        session(info.termId)?.let { return it }
        val s = nouvelle(info.termId, info.name, info.cwd, 80, 24)
        ajouter(s)
        rattacherMaintenant(s)
        return s
    }

    private fun rattacher(s: SessionTerminal) {
        if (s.fin != null) return
        portee.launch { rattacherMaintenant(s) }
    }

    private suspend fun rattacherMaintenant(s: SessionTerminal) {
        try {
            val r = client.appeler("term.attach", SortieTerminal.serializer(), buildJsonObject { put("term_id", s.id) })
            s.remplacer(r.output)
            envoyerTaille(s)
        } catch (e: RpcException) {
            if (e.code != "hors_ligne") s.terminer(-1)
        }
    }

    /** Saisie (clavier, barre de touches, réponses de l'émulateur), dans l'ordre. */
    fun entrer(id: String, data: String) {
        if (data.isEmpty() || session(id)?.fin != null) return
        files[id]?.trySend(data)
    }

    fun redimensionner(s: SessionTerminal, colonnes: Int, lignes: Int) {
        if (s.redimensionner(colonnes, lignes)) envoyerTaille(s)
    }

    private fun envoyerTaille(s: SessionTerminal) {
        if (s.fin != null) return
        portee.launch {
            runCatching {
                client.appeler("term.resize", buildJsonObject { put("term_id", s.id); put("cols", s.colonnes); put("rows", s.lignes) })
            }
        }
    }

    /** Ferme le terminal sur le serveur (ce qui y tourne est arrêté) et le retire. */
    suspend fun fermer(s: SessionTerminal) {
        if (s.fin == null) {
            try {
                client.appeler("term.close", buildJsonObject { put("term_id", s.id) })
            } catch (e: RpcException) {
                if (e.code != "introuvable") throw e
            }
        }
        retirer(s)
    }

    /** Retire le terminal de l'appli seulement (il continue sur le serveur, rattachable). */
    fun retirer(s: SessionTerminal) {
        files.remove(s.id)?.close()
        _sessions.value = _sessions.value.filter { it.id != s.id }
    }

    /** Déconnexion : plus aucun terminal affiché. */
    fun oublier() {
        files.values.forEach { it.close() }
        files.clear()
        enAvance.clear()
        _sessions.value = emptyList()
    }
}
