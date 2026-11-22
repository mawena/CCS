package com.mawena.ccs.reseau

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Un projet de `projects.list` (`ProjectEntry` de `session_hub.py`) ; `cwd` nul : « Tous ». */
@Serializable
data class Projet(
    val cwd: String? = null,
    val name: String = "",
    val conversations: Int = 0,
    val total: Int = 0,
    val open: Int = 0,
    val waiting: Int = 0,
    val last: Double = 0.0,
    val exists: Boolean = true,
    @SerialName("moved_to") val deplaceVers: String? = null,
    val profile: String? = null,
)

/** Une conversation de l'historique (`Conversation` de `conversations.py`). */
@Serializable
data class Conversation(
    @SerialName("session_id") val sessionId: String = "",
    val path: String = "",
    val cwd: String = "",
    val title: String = "",
    @SerialName("first_prompt") val premiereDemande: String = "",
    @SerialName("last_prompt") val derniereDemande: String = "",
    val prompts: Int = 0,
    @SerialName("started_at") val debut: Double? = null,
    @SerialName("updated_at") val misAJour: Double = 0.0,
    val origin: String = "",
    @SerialName("git_branch") val branche: String = "",
    val size: Long = 0,
    @SerialName("folder_exists") val dossierExiste: Boolean = true,
    val archived: Boolean = false,
) {
    val titre: String get() = title.ifBlank { premiereDemande.ifBlank { "(sans titre)" } }
}

@Serializable
data class ListeProjets(
    val entries: List<Projet> = emptyList(),
    val conversations: List<Conversation> = emptyList(),
    val total: Int = 0,
    val projects: Int = 0,
) {
    /** Projets réels (sans l'entrée « Tous les projets »). */
    val projets: List<Projet> get() = entries.filter { !it.cwd.isNullOrEmpty() }
}

/** Options d'un chat (`ChatOptions` de `chat_options.py`). */
@Serializable
data class OptionsChat(
    val model: String? = null,
    val effort: String? = null,
    val ultracode: Boolean = false,
    val rights: String = "manual",
)

/** Un chat ouvert dans le pont (`chat.list`) ou la réponse de `chat.open`. */
@Serializable
data class ChatOuvert(
    @SerialName("chat_id") val chatId: String = "",
    val cwd: String = "",
    val state: String = "",
    val seq: Long = 0,
    val options: OptionsChat? = null,
    @SerialName("session_id") val sessionId: String? = null,
    val path: String? = null,
    @SerialName("history_before") val historiqueAvant: Double? = null,
)

@Serializable
data class ListeChats(val chats: List<ChatOuvert> = emptyList())

@Serializable
data class Cout(val short: String = "", val text: String = "", val dollars: Double = 0.0)

@Serializable
data class Renomme(val title: String = "")

@Serializable
data class MiseCorbeille(@SerialName("trash_id") val trashId: String = "")

@Serializable
data class ElementCorbeille(
    @SerialName("trash_id") val trashId: String = "",
    @SerialName("session_id") val sessionId: String? = null,
    val cwd: String? = null,
    val title: String? = null,
    @SerialName("trashed_at") val supprimeLe: Double? = null,
)

@Serializable
data class Corbeille(val items: List<ElementCorbeille> = emptyList(), val days: Int = 30)

@Serializable
data class ProfilCompte(val name: String = "", val email: String = "", val active: Boolean = false)

/** `projects.account` : comptes, compte actif et compte conseillé pour un dossier. */
@Serializable
data class CompteProjet(
    val profiles: List<ProfilCompte> = emptyList(),
    val active: String? = null,
    val preferred: String? = null,
    val hint: String = "",
    val paused: Boolean = false,
)

@Serializable
data class DepotGit(val path: String = "", val name: String = "")

@Serializable
data class Depots(val folders: List<DepotGit> = emptyList(), val truncated: Boolean = false)

@Serializable
data class ProjetAjoute(val cwd: String = "")

/** Un message de `conversations.messages` (`Message` de `preview.py`). */
@Serializable
data class MessageHistorique(
    val role: String = "",
    val text: String = "",
    val ts: Double? = null,
    val tool: OutilHistorique? = null,
    @SerialName("msg_id") val msgId: String = "",
    val uuid: String = "",
)

@Serializable
data class OutilHistorique(
    val name: String = "",
    val target: String = "",
    val result: String? = null,
    @SerialName("tool_id") val toolId: String = "",
    @SerialName("is_error") val erreur: Boolean = false,
)

@Serializable
data class Messages(val messages: List<MessageHistorique> = emptyList())
