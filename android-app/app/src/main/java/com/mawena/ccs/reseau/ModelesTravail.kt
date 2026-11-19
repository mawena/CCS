package com.mawena.ccs.reseau

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

/**
 * Réponses des RPC de la feuille de route (`roadmap.*`), des tâches de fond (`tasks.*`), du
 * travail du chat (`work.changes`, `work.rewind_*`, `work.saved.*`), des terminaux (`term.*`) et
 * de la route `/api/tokens`.
 */

@Serializable
data class TacheFeuille(val text: String = "", val done: Boolean = false, val line: Int = 0, val depth: Int = 0)

@Serializable
data class PhaseFeuille(
    val title: String = "",
    val version: String? = null,
    val tasks: List<TacheFeuille> = emptyList(),
    val line: Int = 0,
)

/** `roadmap.read` : `path` nul quand le projet n'a pas de ROADMAP.md. */
@Serializable
data class FeuilleDeRoute(val path: String? = null, val title: String = "", val phases: List<PhaseFeuille> = emptyList())

@Serializable
data class ResultatCase(val changed: Boolean = true)

@Serializable
data class InvitationTache(val prompt: String = "")

/** Une tâche de fond (`Task` de `tasks.py`). */
@Serializable
data class TacheFond(
    val id: String = "",
    val message: String = "",
    val cwd: String = "",
    val model: String? = null,
    val rights: String = "",
    @SerialName("when") val quand: String = "quota",
    val state: String = "",
    val created: Double = 0.0,
    val started: Double? = null,
    val finished: Double? = null,
    @SerialName("session_id") val sessionId: String? = null,
    val account: String? = null,
    val attempts: Int = 0,
    val duration: Double? = null,
    val cost: Double? = null,
    val error: String? = null,
    val note: String = "",
)

@Serializable
data class ListeTaches(val tasks: List<TacheFond> = emptyList())

/** `tasks.log` : la tâche, son résumé et la fin de son journal. */
@Serializable
data class JournalTache(
    val task: TacheFond = TacheFond(),
    val summary: String = "",
    val lines: List<String> = emptyList(),
    val truncated: Boolean = false,
)

/** Un fichier changé pendant la session (`work.changes`) ; `sha256` : son contenu actuel (nul s'il n'existe plus). */
@Serializable
data class FichierChange(
    val path: String = "",
    val kind: String = "modified",
    val binary: Boolean = false,
    val diff: String = "",
    @SerialName("too_big") val tropGros: Boolean = false,
    val sha256: String? = null,
)

@Serializable
data class PointRetour(@SerialName("message_id") val messageId: String = "", val text: String = "", val time: Double? = null)

@Serializable
data class Changements(
    val unknown: Boolean = false,
    val files: List<FichierChange> = emptyList(),
    val points: List<PointRetour> = emptyList(),
)

@Serializable
data class EtapeRetour(
    val path: String = "",
    val deleted: Boolean = false,
    @SerialName("user_edited") val modifieParToi: Boolean = false,
    val sha256: String? = null,
)

@Serializable
data class PlanRetour(val steps: List<EtapeRetour> = emptyList(), val skipped: List<String> = emptyList())

@Serializable
data class ResultatRetour(val count: Int = 0, val skipped: List<String> = emptyList())

@Serializable
data class MessageEnregistre(val name: String = "", val text: String = "", val scope: String = "global")

@Serializable
data class MessagesEnregistres(val items: List<MessageEnregistre> = emptyList())

/** `settings.get` : tous les réglages, tels que le pont les garde. */
@Serializable
data class Reglages(val settings: JsonObject = JsonObject(emptyMap()))

@Serializable
data class CanalTelephone(val topic: String = "")

@Serializable
data class EssaiTelephone(val ok: Boolean = false, val message: String = "")

@Serializable
data class QrTelephone(val url: String = "", val image: String = "")

/** Accès connecté au compte (`/api/tokens`). `kind` : session, device ou app. */
@Serializable
data class Acces(
    val id: String = "",
    val kind: String? = null,
    val name: String = "",
    val created: Double? = null,
    @SerialName("last_used") val dernierUsage: Double? = null,
)

@Serializable
data class ListeAcces(val tokens: List<Acces> = emptyList())

@Serializable
data class TerminalOuvert(@SerialName("term_id") val termId: String = "")

@Serializable
data class InfoTerminal(@SerialName("term_id") val termId: String = "", val cwd: String = "", val name: String = "Terminal")

@Serializable
data class ListeTerminaux(val terms: List<InfoTerminal> = emptyList())

@Serializable
data class SortieTerminal(val output: String = "")
