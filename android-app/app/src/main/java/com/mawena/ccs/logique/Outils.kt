package com.mawena.ccs.logique

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/** Noms et cibles des outils de Claude, comme `TOOL_LABELS` et `target()` de `web/chat.js`. */
object Outils {
    private val LIBELLES = mapOf(
        "Read" to "Lecture", "Edit" to "Modification", "MultiEdit" to "Modification", "Write" to "Écriture",
        "Bash" to "Commande", "Grep" to "Recherche", "Glob" to "Fichiers", "WebFetch" to "Page web",
        "WebSearch" to "Recherche web", "Task" to "Sous-agent", "Agent" to "Sous-agent", "TodoWrite" to "Tâches",
        "Skill" to "Skill", "AskUserQuestion" to "Question", "NotebookEdit" to "Carnet",
    )

    /** Outils qui lancent un sous-agent. */
    val AGENTS = setOf("Task", "Agent")

    fun libelle(nom: String) = LIBELLES[nom] ?: nom

    private fun JsonObject.texte(cle: String): String = (this[cle] as? JsonPrimitive)?.contentOrNull.orEmpty()
    private fun premiere(s: String) = s.substringBefore('\n')

    /** Ce sur quoi porte l'outil : commande, fichier, motif, adresse… */
    fun cible(nom: String, e: JsonObject?): String {
        val i = e ?: return ""
        return when (nom) {
            "Bash" -> premiere(i.texte("command"))
            "Read", "Write", "Edit", "MultiEdit", "NotebookEdit" -> i.texte("file_path").ifEmpty { i.texte("notebook_path") }
            "Grep", "Glob" -> i.texte("pattern") + i.texte("path").let { if (it.isNotEmpty()) " dans $it" else "" }
            "WebFetch" -> i.texte("url")
            "WebSearch" -> i.texte("query")
            "Task", "Agent" -> i.texte("description").ifEmpty { premiere(i.texte("prompt")) }
            "Skill" -> i.texte("skill")
            else -> premiere(i.values.firstNotNullOfOrNull { v -> (v as? JsonPrimitive)?.takeIf { it.isString }?.content?.takeIf(String::isNotBlank) }.orEmpty())
        }
    }

    private val joli = Json { prettyPrint = true }

    /** Paramètres de l'outil en JSON lisible (détail d'une carte repliée). */
    fun details(e: JsonObject?): String = joli.encodeToString(JsonObject.serializer(), e ?: JsonObject(emptyMap()))
}
