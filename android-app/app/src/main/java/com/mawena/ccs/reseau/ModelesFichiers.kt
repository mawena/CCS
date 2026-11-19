package com.mawena.ccs.reseau

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/** Réponses des RPC `files.*` (`bridge_data.py`, `bridge_files.py`) et de `work.files`. */

@Serializable
data class RacinesFichiers(val home: String = "", val roots: List<String> = emptyList())

/** Une entrée de `files.list` (ou de `files.search`) : chemin relatif à la racine demandée. */
@Serializable
data class EntreeFichier(
    val name: String = "",
    val path: String = "",
    val dir: Boolean = false,
    val mark: String = "",
)

@Serializable
data class ListeFichiers(val entries: List<EntreeFichier> = emptyList(), val truncated: Boolean = false)

/** `files.read` : `kind` vaut text, image, binary ou too_big ; `stamp` est renvoyé tel quel à `files.write`. */
@Serializable
data class FichierLu(
    val kind: String = "",
    val stamp: JsonElement? = null,
    val text: String? = null,
    val encoding: String? = null,
)

@Serializable
data class ImageFichier(val mime: String = "", val data: String = "")

@Serializable
data class MorceauFichier(val size: Long = 0, val data: String = "", val done: Boolean = false)

@Serializable
data class InfoFichier(val dir: Boolean = false, val count: Int = 0, val size: Long = 0)

@Serializable
data class CheminRendu(val path: String = "")

@Serializable
data class FichierEcrit(val stamp: JsonElement? = null)

@Serializable
data class IndexFichiers(val files: List<String> = emptyList())

/** Réponses des RPC `git.*` (`bridge_git.py`). */

@Serializable
data class BrancheGit(
    val name: String? = null,
    val upstream: String? = null,
    val ahead: Int = 0,
    val behind: Int = 0,
)

/** Fichier de `git.status` : lettres de l'index et de la copie de travail (`.` : rien, `?` : non suivi). */
@Serializable
data class FichierGit(
    val path: String = "",
    val staged: String = ".",
    val unstaged: String = ".",
    @SerialName("orig_path") val ancien: String? = null,
)

@Serializable
data class EtatGit(
    val repo: Boolean = false,
    val root: String = "",
    val branch: BrancheGit = BrancheGit(),
    val files: List<FichierGit> = emptyList(),
    val truncated: Boolean = false,
    val proposed: String = "",
    @SerialName("last_message") val dernierMessage: String = "",
)

@Serializable
data class LigneGit(
    val kind: String = " ",
    val text: String = "",
    @SerialName("old_no") val ancien: Int? = null,
    @SerialName("new_no") val nouveau: Int? = null,
)

@Serializable
data class MorceauGit(val header: String = "", val lines: List<LigneGit> = emptyList())

@Serializable
data class DiffGit(
    val path: String = "",
    @SerialName("old_path") val ancien: String? = null,
    val binary: Boolean = false,
    @SerialName("new_file") val nouveau: Boolean = false,
    val deleted: Boolean = false,
    val hunks: List<MorceauGit> = emptyList(),
    val truncated: Boolean = false,
    @SerialName("too_big") val tropGros: Boolean = false,
)

@Serializable
data class ReponseDiff(val diff: DiffGit? = null)

@Serializable
data class CommitGit(
    val id: String = "",
    val short: String = "",
    val author: String = "",
    val email: String = "",
    val time: Long = 0,
    val subject: String = "",
    val parents: List<String> = emptyList(),
    val body: String = "",
)

@Serializable
data class JournalGit(val commits: List<CommitGit> = emptyList(), val more: Boolean = false)

@Serializable
data class RefGit(val name: String = "", val kind: String = "", val target: String = "")

@Serializable
data class RefsGit(val refs: List<RefGit> = emptyList())

@Serializable
data class DetailCommit(
    val commit: CommitGit = CommitGit(),
    val files: List<DiffGit> = emptyList(),
    val truncated: Boolean = false,
)

@Serializable
data class CommitCree(val id: String = "")
