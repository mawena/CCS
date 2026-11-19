package com.mawena.ccs.logique

/**
 * Décide des notifications à partir des événements des chats (`chat.event`), sans Android :
 * fin de tour (retour au repos après un travail), autorisation ou question en attente, rappel
 * unique d'une attente trop longue (comme le rappel d'attente du bureau, `daemon.py`).
 *
 * Pas de notification pour le chat affiché à l'écran ([afficher]) ; celles qu'il avait sont retirées.
 * Les événements rejoués au premier rattachement d'un chat sont lus en `silencieux` : ils
 * renseignent l'état et les attentes en cours sans rien annoncer (déjà vus ailleurs).
 */
class Veilleur {
    sealed interface Action {
        val chatId: String

        data class FinTour(override val chatId: String, val resume: String, val limite: Boolean) : Action
        data class Attente(override val chatId: String, val requestId: String, val question: Boolean, val texte: String) : Action
        data class Rappel(override val chatId: String, val requestId: String, val question: Boolean, val texte: String, val minutes: Int) : Action
        data class RetirerFin(override val chatId: String) : Action
        data class RetirerAttente(override val chatId: String, val requestId: String) : Action
        /** Toutes les notifications du chat (chat affiché ou fermé). */
        data class RetirerTout(override val chatId: String) : Action
    }

    private class Suivi(var etat: String) {
        var interrompu = false
        var dernierTexte = ""
    }

    private class EnAttente(val chatId: String, val requestId: String, val question: Boolean, val texte: String, val depuis: Long) {
        var rappele = false
    }

    private val chats = HashMap<String, Suivi>()
    private val attentes = LinkedHashMap<String, EnAttente>()     // clé : chat|demande

    /** Chat affiché à l'écran (null : aucun, ou appli en arrière-plan). */
    var affiche: String? = null
        private set

    fun etat(chatId: String): String? = chats[chatId]?.etat
    fun attentes(chatId: String): List<String> = attentes.values.filter { it.chatId == chatId }.map { it.requestId }

    /** État lu dans `chat.list` / `chat.attach` : fait foi, sans alerte. */
    fun connaitre(chatId: String, etat: String) {
        val s = chats.getOrPut(chatId) { Suivi(etat) }
        s.etat = etat
        if (etat != "permission" && etat != "busy") retirerAttentes(chatId)
    }

    /** Chats fermés dans le pont : leurs notifications partent. */
    fun garderSeulement(ouverts: Set<String>): List<Action> {
        val partis = chats.keys.filter { it !in ouverts }
        partis.forEach { id -> chats.remove(id); retirerAttentes(id) }
        return partis.map { Action.RetirerTout(it) }
    }

    fun afficher(chatId: String?): List<Action> {
        affiche = chatId
        return if (chatId != null) listOf(Action.RetirerTout(chatId)) else emptyList()
    }

    /** Un événement du chat ; `maintenant` / `ts` en millisecondes. */
    fun recevoir(chatId: String, ev: EvChat, ts: Long, silencieux: Boolean = false): List<Action> {
        val s = chats.getOrPut(chatId) { Suivi("idle") }
        val vu = silencieux || affiche == chatId
        val out = ArrayList<Action>()
        when (ev) {
            is EvChat.Etat -> {
                val avant = s.etat
                s.etat = ev.etat
                when {
                    ev.etat == "idle" && avant in TRAVAIL -> {
                        if (!s.interrompu && !vu) out += Action.FinTour(chatId, resumer(s.dernierTexte), false)
                        s.interrompu = false
                        out += retirerAttentes(chatId)
                    }
                    ev.etat == "busy" && avant !in TRAVAIL -> {
                        s.interrompu = false
                        s.dernierTexte = ""
                        out += Action.RetirerFin(chatId)        // nouveau tour : l'ancienne fin ne sert plus
                    }
                    ev.etat == "stopped" || ev.etat == "suspended" -> out += retirerAttentes(chatId)
                }
            }
            is EvChat.Texte -> if (ev.parentId == null && ev.texte.isNotBlank()) s.dernierTexte = ev.texte
            is EvChat.Tour -> {
                if (ev.interrompu) s.interrompu = true
                if (ev.texte.isNotBlank()) s.dernierTexte = ev.texte
            }
            is EvChat.Autorisation -> {
                val question = ev.outil == "AskUserQuestion"
                val texte = if (question) {
                    FilChat.questions(ev.entree).firstOrNull()?.question.orEmpty().ifEmpty { "Claude te pose une question." }
                } else {
                    val quoi = ev.affiche.ifEmpty { Outils.libelle(ev.outil) }
                    val cible = Outils.cible(ev.outil, ev.entree)
                    if (cible.isNotEmpty()) "$quoi : $cible" else quoi
                }
                val a = EnAttente(chatId, ev.requestId, question, texte, ts)
                attentes[cle(chatId, ev.requestId)] = a
                if (!vu) out += Action.Attente(chatId, ev.requestId, question, texte)
            }
            is EvChat.Reglee -> {
                if (attentes.remove(cle(chatId, ev.requestId)) != null || !silencieux) out += Action.RetirerAttente(chatId, ev.requestId)
            }
            is EvChat.Fin -> {
                s.etat = "stopped"
                out += retirerAttentes(chatId)
            }
            else -> Unit
        }
        return if (silencieux) out.filter { it is Action.RetirerFin || it is Action.RetirerAttente || it is Action.RetirerTout } else out
    }

    /**
     * Rappels dus : attentes d'au moins `seuilMs`, pas encore rappelées. Une attente vue sur le chat
     * affiché compte comme vue (pas de rappel).
     */
    fun rappels(maintenant: Long, seuilMs: Long?): List<Action> {
        if (seuilMs == null || seuilMs <= 0) return emptyList()
        val out = ArrayList<Action>()
        for (a in attentes.values) {
            if (a.rappele || maintenant - a.depuis < seuilMs) continue
            a.rappele = true
            if (a.chatId == affiche) continue
            out += Action.Rappel(a.chatId, a.requestId, a.question, a.texte, ((maintenant - a.depuis) / 60_000).toInt())
        }
        return out
    }

    /** Attentes trouvées au premier rattachement déjà plus vieilles que le seuil : pas de rappel. */
    fun marquerAnciennes(maintenant: Long, seuilMs: Long?) {
        if (seuilMs == null || seuilMs <= 0) return
        attentes.values.filter { maintenant - it.depuis >= seuilMs }.forEach { it.rappele = true }
    }

    /** Instant du prochain rappel (ms), ou null. */
    fun prochainRappel(seuilMs: Long?): Long? {
        if (seuilMs == null || seuilMs <= 0) return null
        return attentes.values.filter { !it.rappele }.minOfOrNull { it.depuis + seuilMs }
    }

    private fun retirerAttentes(chatId: String): List<Action> {
        val parties = attentes.values.filter { it.chatId == chatId }
        parties.forEach { attentes.remove(cle(chatId, it.requestId)) }
        return parties.map { Action.RetirerAttente(chatId, it.requestId) }
    }

    private fun cle(chatId: String, requestId: String) = "$chatId|$requestId"

    companion object {
        private val TRAVAIL = setOf("busy", "permission")
        private const val MAX_RESUME = 300

        /** Fin de la réponse de Claude, sur une ligne, pour le corps de la notification. */
        fun resumer(texte: String): String {
            val t = texte.replace(Regex("[`*_#>]+"), "").replace(Regex("\\s+"), " ").trim()
            if (t.isEmpty()) return "Prêt pour la suite."
            return if (t.length <= MAX_RESUME) t else t.take(MAX_RESUME - 1).trimEnd() + "…"
        }
    }
}
