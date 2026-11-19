package com.mawena.ccs.logique

/** Un élément partagé par une autre appli : adresse (`content://…`) et type MIME. */
data class ElementPartage(val uri: String, val mime: String?)

/** Ce qu'une autre appli partage vers CCS : texte pour la saisie, images jointes, autres fichiers. */
data class Partage(val texte: String, val images: List<String>, val fichiers: List<String>) {
    val vide: Boolean get() = texte.isBlank() && images.isEmpty() && fichiers.isEmpty()

    /** « 2 images, 1 fichier et du texte ». */
    fun resume(): String {
        val parts = buildList {
            if (images.isNotEmpty()) add(if (images.size == 1) "1 image" else "${images.size} images")
            if (fichiers.isNotEmpty()) add(if (fichiers.size == 1) "1 fichier" else "${fichiers.size} fichiers")
            if (texte.isNotBlank()) add("du texte")
        }
        return when (parts.size) {
            0 -> "Rien"
            1 -> parts[0]
            else -> parts.dropLast(1).joinToString(", ") + " et " + parts.last()
        }.replaceFirstChar { it.uppercase() }
    }
}

/** Analyse d'un partage Android (ACTION_SEND / SEND_MULTIPLE), sans Android. */
object AnalysePartage {
    /** Types que Claude lit comme images (les autres images partent comme fichiers). */
    val TYPES_IMAGE = setOf("image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp")

    /**
     * `sujet` (EXTRA_SUBJECT) passe devant le texte s'il n'y figure pas déjà (titre d'une page
     * partagée avec son lien). Au-delà de `maxImages`, les images partent comme fichiers.
     */
    fun analyser(texte: String?, sujet: String?, elements: List<ElementPartage>, maxImages: Int = 5): Partage {
        val t = texte?.trim().orEmpty()
        val s = sujet?.trim().orEmpty()
        val tout = when {
            s.isEmpty() -> t
            t.isEmpty() -> s
            t.contains(s) -> t
            else -> "$s\n$t"
        }
        val images = ArrayList<String>()
        val fichiers = ArrayList<String>()
        for (e in elements.distinctBy { it.uri }) {
            val mime = e.mime?.lowercase()?.substringBefore(';')?.trim()
            if (mime in TYPES_IMAGE && images.size < maxImages) images += e.uri else fichiers += e.uri
        }
        return Partage(tout, images, fichiers)
    }

    /** Nom de remplacement quand le nom existe déjà : « rapport.pdf » → « rapport (2).pdf ». */
    fun nomLibre(nom: String, essai: Int): String {
        if (essai <= 1) return nom
        val point = nom.lastIndexOf('.')
        return if (point > 0) "${nom.substring(0, point)} ($essai)${nom.substring(point)}" else "$nom ($essai)"
    }

    /** Saisie après le partage : brouillon existant, texte partagé, puis fichiers envoyés cités. */
    fun composer(brouillon: String, texte: String, fichiers: List<String>): String {
        val citation = when (fichiers.size) {
            0 -> ""
            1 -> "Fichier ajouté au dossier du projet : `${fichiers[0]}`"
            else -> "Fichiers ajoutés au dossier du projet : " + fichiers.joinToString(", ") { "`$it`" }
        }
        return listOf(brouillon.trimEnd(), texte.trim(), citation).filter { it.isNotEmpty() }.joinToString("\n\n")
    }
}
