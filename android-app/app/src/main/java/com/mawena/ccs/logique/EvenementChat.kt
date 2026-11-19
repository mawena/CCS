package com.mawena.ccs.logique

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

/** Commande `/…` offerte par Claude Code (Hello) : nom sans `/`, description, indice d'argument. */
data class CommandeSlash(val nom: String, val description: String = "", val indice: String = "")

/** Modèle proposé par Claude Code (Hello) : valeur, libellé, niveaux d'effort. */
data class ModeleIa(val valeur: String, val libelle: String, val efforts: List<String> = emptyList())

/** Ligne de la liste de tâches de Claude (TodoWrite). */
data class Tache(val texte: String, val statut: String)

/** Étiquettes d'un message (`message_tags.py`). */
data class EntreeEtiquettes(val etiquettes: List<String>, val role: String = "", val extrait: String = "", val ts: Double = 0.0)

/**
 * Événement du chat poussé par le pont (`chat.event` → `event`), lu depuis le JSON de
 * `server/events.py` (nom de la classe Python dans `type`, ses champs à côté).
 */
sealed interface EvChat {
    data class Init(val sessionId: String, val modele: String, val droits: String) : EvChat
    data class Hello(val commandes: List<CommandeSlash>, val modeles: List<ModeleIa>, val droits: String) : EvChat
    data class Statut(val droits: String) : EvChat
    data class CommandeLocale(val texte: String) : EvChat
    data class Delta(val msgId: String, val texte: String, val parentId: String?) : EvChat
    data class Texte(val msgId: String, val texte: String, val parentId: String?) : EvChat
    data class Reflexion(val msgId: String) : EvChat
    data class OutilLance(val toolId: String, val nom: String, val entree: JsonObject, val parentId: String?) : EvChat
    data class OutilFini(val toolId: String, val texte: String, val erreur: Boolean, val parentId: String?) : EvChat
    data class AvisTache(val toolId: String, val statut: String, val resume: String) : EvChat
    data class Taches(val taches: List<Tache>) : EvChat
    data class Autorisation(
        val requestId: String, val outil: String, val affiche: String, val entree: JsonObject,
        val description: String, val agentId: String?,
    ) : EvChat
    data class Envoye(val texte: String, val images: Int, val nonce: String, val uuid: String) : EvChat
    data class EtiquettesChangees(val sessionId: String, val msgId: String, val entree: EntreeEtiquettes?) : EvChat
    data class Reglee(val requestId: String, val decision: String) : EvChat
    data class Tour(
        val ok: Boolean, val sousType: String, val coutUsd: Double, val texte: String,
        val limite: Boolean, val interrompu: Boolean,
    ) : EvChat
    data object Compacte : EvChat
    data class Reinitialise(val declencheur: String) : EvChat {
        /** Effacée par Claude en fin de sujet (`ccs chat effacer`), pas par `/clear`. */
        val auto: Boolean get() = declencheur == "ccs_auto"
    }
    data class Note(val texte: String, val genre: String) : EvChat
    data class NouvelEssai(val tentative: Int, val delaiS: Double) : EvChat
    data class Etat(val etat: String) : EvChat
    data class Contexte(val pourcentage: Int, val total: Long, val maximum: Long, val auto: Boolean) : EvChat
    data class OptionRefusee(val quoi: String, val erreur: String) : EvChat
    data class DemandeInconnue(val sousType: String) : EvChat
    data class Fin(val code: Int?, val demande: Boolean) : EvChat
    data class Autre(val type: String) : EvChat

    /** Sous-agent qui a émis l'événement (outil Task/Agent), s'il y en a un. */
    val parent: String?
        get() = when (this) {
            is Delta -> parentId
            is Texte -> parentId
            is OutilLance -> parentId
            is OutilFini -> parentId
            else -> null
        }

    companion object {
        fun lire(o: JsonObject): EvChat {
            val type = o.texte("type")
            return when (type) {
                "Init" -> Init(o.texte("session_id"), o.texte("model"), o.texte("permission_mode"))
                "Hello" -> Hello(commandes(o["commands"]), modeles(o["models"]), o.texte("permission_mode"))
                "Status" -> Statut(o.texte("permission_mode"))
                "LocalCommand" -> CommandeLocale(o.texte("text"))
                "TextDelta" -> Delta(o.texte("msg_id"), o.texte("text"), o.texteOuNul("parent_id"))
                "AssistantText" -> Texte(o.texte("msg_id"), o.texte("text"), o.texteOuNul("parent_id"))
                "Thinking" -> Reflexion(o.texte("msg_id"))
                "ToolUse" -> OutilLance(o.texte("tool_id"), o.texte("name"), o["input"] as? JsonObject ?: JsonObject(emptyMap()), o.texteOuNul("parent_id"))
                "ToolResult" -> OutilFini(o.texte("tool_id"), o.texte("text"), o.bool("is_error"), o.texteOuNul("parent_id"))
                "TaskNotice" -> AvisTache(o.texte("tool_id"), o.texte("status"), o.texte("summary"))
                "Todos" -> Taches(taches(o["items"]))
                "PermissionRequest" -> Autorisation(
                    o.texte("request_id"), o.texte("tool_name"), o.texte("display_name"),
                    o["input"] as? JsonObject ?: JsonObject(emptyMap()), o.texte("description"), o.texteOuNul("agent_id"),
                )
                "UserSent" -> Envoye(o.texte("text"), o.entier("images"), o.texte("nonce"), o.texte("uuid"))
                "TagsChanged" -> EtiquettesChangees(o.texte("session_id"), o.texte("msg_id"), etiquettes(o["entry"]))
                "PermissionSettled" -> Reglee(o.texte("request_id"), o.texte("decision"))
                "TurnResult" -> Tour(
                    o.bool("ok"), o.texte("subtype"), (o["cost_usd"] as? JsonPrimitive)?.doubleOrNull ?: 0.0,
                    o.texte("text"), o.bool("is_limit"), o.bool("interrupted"),
                )
                "Compacted" -> Compacte
                "ConversationReset" -> Reinitialise(o.texte("trigger"))
                "Notice" -> Note(o.texte("text"), o.texte("kind").ifEmpty { "info" })
                "Retrying" -> NouvelEssai(o.entier("attempt"), (o["delay_s"] as? JsonPrimitive)?.doubleOrNull ?: 0.0)
                "StateChanged" -> Etat(o.texte("state"))
                "ContextUsage" -> Contexte(o.entier("percentage"), o.long("total"), o.long("maximum"), o.bool("auto_compact"))
                "OptionRefused" -> OptionRefusee(o.texte("what"), o.texte("error"))
                "UnhandledRequest" -> DemandeInconnue(o.texte("subtype"))
                "ProcessExited" -> Fin((o["code"] as? JsonPrimitive)?.longOrNull?.toInt(), o.bool("requested"))
                else -> Autre(type)
            }
        }

        private fun JsonObject.texte(cle: String): String = texteOuNul(cle).orEmpty()
        private fun JsonObject.texteOuNul(cle: String): String? =
            (this[cle] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull
        private fun JsonObject.bool(cle: String) = (this[cle] as? JsonPrimitive)?.booleanOrNull ?: false
        private fun JsonObject.long(cle: String) = (this[cle] as? JsonPrimitive)?.let { it.longOrNull ?: it.doubleOrNull?.toLong() } ?: 0L
        private fun JsonObject.entier(cle: String) = long(cle).toInt()

        private fun chaine(e: JsonElement?): String = (e as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull.orEmpty()

        private fun commandes(e: JsonElement?): List<CommandeSlash> = (e as? JsonArray).orEmpty().mapNotNull {
            when (it) {
                is JsonArray -> chaine(it.getOrNull(0)).takeIf(String::isNotEmpty)?.let { n ->
                    CommandeSlash(n.removePrefix("/"), chaine(it.getOrNull(1)), chaine(it.getOrNull(2)))
                }
                is JsonPrimitive -> chaine(it).takeIf(String::isNotEmpty)?.let { n -> CommandeSlash(n.removePrefix("/")) }
                else -> null
            }
        }

        fun modeles(e: JsonElement?): List<ModeleIa> = (e as? JsonArray).orEmpty().mapNotNull {
            when (it) {
                is JsonArray -> chaine(it.getOrNull(0)).takeIf(String::isNotEmpty)?.let { v ->
                    ModeleIa(v, chaine(it.getOrNull(1)).ifEmpty { v }, (it.getOrNull(3) as? JsonArray).orEmpty().map(::chaine).filter(String::isNotEmpty))
                }
                is JsonPrimitive -> chaine(it).takeIf(String::isNotEmpty)?.let { v -> ModeleIa(v, v) }
                else -> null
            }
        }

        /** Tâches : `[contenu, statut]` (pont) ou `{content, status, activeForm}`. */
        private fun taches(e: JsonElement?): List<Tache> = (e as? JsonArray).orEmpty().mapNotNull {
            when (it) {
                is JsonArray -> Tache(chaine(it.getOrNull(0)), chaine(it.getOrNull(1)).ifEmpty { "pending" })
                is JsonObject -> {
                    val statut = it.texte("status").ifEmpty { "pending" }
                    val forme = it.texte("activeForm")
                    Tache(if (statut == "in_progress" && forme.isNotEmpty()) forme else it.texte("content"), statut)
                }
                else -> null
            }
        }

        fun etiquettes(e: JsonElement?): EntreeEtiquettes? {
            val o = e as? JsonObject ?: return null
            val tags = (o["tags"] as? JsonArray).orEmpty().map(::chaine).filter(String::isNotEmpty)
            if (tags.isEmpty()) return null
            return EntreeEtiquettes(tags, o.texte("role"), o.texte("excerpt"), (o["ts"] as? JsonPrimitive)?.doubleOrNull ?: 0.0)
        }
    }
}
