package com.mawena.ccs.notif

import android.content.Context
import com.mawena.ccs.logique.EvChat
import com.mawena.ccs.logique.Format
import com.mawena.ccs.logique.Veilleur
import com.mawena.ccs.reseau.ChatOuvert
import com.mawena.ccs.reseau.CcsClient
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.ListeChats
import com.mawena.ccs.reseau.ListeProjets
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

/**
 * Veille des chats du pont pendant que le service tourne : rattache le WebSocket à tous les chats
 * ouverts (`chat.list` puis `chat.attach`, à chaque connexion et chaque minute pour ceux ouverts
 * ailleurs), lit leurs événements et confie la décision au [Veilleur].
 *
 * Tout passe par une seule file traitée dans l'ordre : le collecteur des événements ne bloque
 * jamais le flux partagé (les écrans du chat le lisent aussi).
 *
 * Choix : la veille partage le client de l'appli, donc suit la machine pilotée (comme le web) ;
 * au changement de machine, ce qu'elle savait des chats de l'ancienne est oublié.
 */
class Veille(private val ctx: Context, private val client: CcsClient, private val portee: CoroutineScope) {
    private sealed interface Ordre {
        class Pousse(val d: JsonObject) : Ordre
        data object Synchro : Ordre
        data object Tic : Ordre
        class Affiche(val chatId: String?) : Ordre
        data object Oublier : Ordre
    }

    private val veilleur = Veilleur()
    private val derniers = HashMap<String, Long>()        // chat → dernier numéro lu
    private val infos = java.util.concurrent.ConcurrentHashMap<String, ChatOuvert>()
    private val titres = java.util.concurrent.ConcurrentHashMap<String, String>()   // conversation → titre
    private var seuilMs: Long? = 10 * 60_000L
    private var seuilLu = false
    private var file: Channel<Ordre>? = null
    private var job: Job? = null
    @Volatile private var affiche: String? = null
    private var synchroDemandee = false

    val active: Boolean get() = job != null

    fun demarrer() {
        if (job != null) return
        val f = Channel<Ordre>(Channel.UNLIMITED)
        file = f
        job = portee.launch {
            launch { client.evenements("chat.event").collect { f.trySend(Ordre.Pousse(it)) } }
            launch {
                client.etat.collect {
                    if (it is EtatConnexion.Connecte) f.trySend(Ordre.Synchro) else seuilLu = false
                }
            }
            launch { client.machine.drop(1).collect { f.trySend(Ordre.Oublier) } }
            launch {
                while (true) {
                    delay(TIC_MS)
                    f.trySend(Ordre.Tic)
                }
            }
            f.trySend(Ordre.Affiche(affiche))
            var derniereSynchro = 0L
            for (o in f) {
                try {
                    when (o) {
                        is Ordre.Pousse -> pousse(o.d)
                        Ordre.Synchro -> { synchroDemandee = false; synchroniser(tous = true); derniereSynchro = System.currentTimeMillis() }
                        Ordre.Tic -> {
                            if (client.etat.value is EtatConnexion.Connecte && System.currentTimeMillis() - derniereSynchro >= SYNCHRO_MS) {
                                synchroniser(tous = false); derniereSynchro = System.currentTimeMillis()
                            }
                            executer(veilleur.rappels(System.currentTimeMillis(), seuilMs))
                        }
                        is Ordre.Affiche -> executer(veilleur.afficher(o.chatId))
                        Ordre.Oublier -> {
                            executer(veilleur.garderSeulement(emptySet()))
                            derniers.clear(); infos.clear(); titres.clear()
                            seuilLu = false
                        }
                    }
                } catch (e: kotlinx.coroutines.CancellationException) {
                    throw e
                } catch (_: Exception) {
                    // un appel en échec (coupure) : la prochaine connexion resynchronise
                }
            }
        }
    }

    fun arreter() {
        job?.cancel()
        job = null
        file?.close()
        file = null
        derniers.clear()
        infos.clear()
    }

    /** Chat affiché à l'écran (null quand l'écran du chat passe en arrière-plan). */
    fun afficher(chatId: String?) {
        affiche = chatId
        file?.trySend(Ordre.Affiche(chatId))
    }

    /** L'écran de ce chat s'en va (un autre peut déjà s'être affiché). */
    fun quitter(chatId: String?) {
        if (chatId != null && affiche == chatId) afficher(null)
    }

    fun cible(chatId: String): CibleChat? = infos[chatId]?.let { cibleDe(it) }

    private fun cibleDe(c: ChatOuvert) = CibleChat(
        c.chatId, c.cwd, c.sessionId, c.path,
        c.sessionId?.let { titres[it] } ?: Format.base(c.cwd),
    )

    /**
     * `tous` : après une connexion, chaque chat est rattaché (la nouvelle connexion ne l'est pas
     * encore). Sinon (chaque minute), seuls les chats nouveaux le sont : les autres poussent déjà.
     */
    private suspend fun synchroniser(tous: Boolean) {
        if (!seuilLu) lireSeuil()
        val chats = client.appeler("chat.list", ListeChats.serializer()).chats
        executer(veilleur.garderSeulement(chats.map { it.chatId }.toSet()))
        derniers.keys.retainAll(chats.map { it.chatId }.toSet())
        for (c in chats) {
            infos[c.chatId] = c
            val connu = derniers[c.chatId]
            if (!tous && connu != null) continue
            val silencieux = connu == null
            val depuis = connu ?: (c.seq - REJOUES).coerceAtLeast(0)
            val r = client.appeler("chat.attach", buildJsonObject { put("chat_id", c.chatId); put("since", depuis) }).jsonObject
            if (connu == null) derniers[c.chatId] = depuis
            for (item in (r["events"] as? JsonArray).orEmpty()) (item as? JsonObject)?.let { traiter(c.chatId, it, silencieux) }
            (r["state"] as? JsonPrimitive)?.contentOrNull?.let { veilleur.connaitre(c.chatId, it) }
            if (silencieux) veilleur.marquerAnciennes(System.currentTimeMillis(), seuilMs)
        }
    }

    /** Rappel d'attente du serveur (`alerts.waiting_reminder`, `alerts.waiting_reminder_min`), comme le bureau. */
    private suspend fun lireSeuil() {
        val r = runCatching { client.appeler("settings.get").jsonObject }.getOrNull() ?: return
        val a = (r["settings"] as? JsonObject)?.get("alerts") as? JsonObject
        val actif = (a?.get("waiting_reminder") as? JsonPrimitive)?.booleanOrNull ?: true
        val min = (a?.get("waiting_reminder_min") as? JsonPrimitive)?.longOrNull ?: 10
        seuilMs = if (actif && min > 0) min * 60_000 else null
        seuilLu = true
    }

    private suspend fun pousse(d: JsonObject) {
        val id = (d["chat_id"] as? JsonPrimitive)?.contentOrNull ?: return
        if (id !in derniers) {
            if (synchroDemandee) return
            synchroDemandee = true
            // chat ouvert depuis ce téléphone (chat.open nous y rattache) : relire la liste
            file?.trySend(Ordre.Synchro)   // traité après : ce qui manque revient par chat.attach
            return
        }
        traiter(id, d, false)
    }

    private suspend fun traiter(chatId: String, item: JsonObject, silencieux: Boolean) {
        val seq = (item["seq"] as? JsonPrimitive)?.longOrNull ?: return
        if (seq <= (derniers[chatId] ?: 0)) return
        derniers[chatId] = seq
        val ev = item["event"] as? JsonObject ?: return
        val ts = (item["ts"] as? JsonPrimitive)?.doubleOrNull?.let { (it * 1000).toLong() } ?: System.currentTimeMillis()
        executer(veilleur.recevoir(chatId, EvChat.lire(ev), ts, silencieux))
    }

    private suspend fun executer(actions: List<Veilleur.Action>) {
        for (a in actions) {
            val annonce = a is Veilleur.Action.FinTour || a is Veilleur.Action.Attente || a is Veilleur.Action.Rappel
            val c = if (annonce) infos[a.chatId]?.let { titrer(it); cibleDe(it) } else null
            Notifs.appliquer(ctx, a, c)
        }
    }

    /** Titre de la conversation (`projects.list` du dossier), lu une fois ; sinon le nom du dossier. */
    private suspend fun titrer(c: ChatOuvert) {
        val sid = c.sessionId ?: return
        if (titres.containsKey(sid)) return
        val liste = withTimeoutOrNull(5_000) {
            runCatching { client.appeler("projects.list", ListeProjets.serializer(), buildJsonObject { put("cwd", c.cwd) }) }.getOrNull()
        } ?: return
        liste.conversations.firstOrNull { it.sessionId == sid }?.let { titres[sid] = it.titre }
    }

    companion object {
        private const val TIC_MS = 60_000L
        private const val SYNCHRO_MS = 60_000L
        /** Événements relus au premier rattachement (attente en cours, sans annonce). */
        private const val REJOUES = 200L
    }
}
