package com.mawena.ccs.logique

/**
 * Répondre en citant un message : format du message envoyé, le même que `web/chat-quote.js` et
 * `ccs_app/chat_quote.py`. Le message commence par la citation en bloc Markdown, puis la réponse :
 *
 * ```
 * > **Claude :**
 * > le passage cité
 *
 * la réponse
 * ```
 */
object Citation {
    enum class Auteur(val cle: String, val etiquette: String, val affiche: String) {
        Claude("claude", "Claude", "Claude"),
        Moi("moi", "Moi", "Toi"),
    }

    /** Message cité : son auteur et le passage. */
    data class Cite(val auteur: Auteur, val texte: String)

    /** Message de l'utilisateur qui commence par une citation : la citation et la réponse. */
    data class Decoupe(val auteur: Auteur, val texte: String, val corps: String)

    const val MAX = 1200          // message cité en entier : au-delà, seulement son début
    const val MAX_SELECTION = 4000
    const val COUPE = " […]"

    private fun propre(t: String?) = (t ?: "").replace("\r\n", "\n").trim()

    /** Texte à citer : sans blancs autour, coupé à `limite` caractères (entre deux mots si possible). */
    fun extrait(texte: String?, limite: Int = MAX): String {
        val p = propre(texte)
        val points = p.codePointCount(0, p.length)
        if (points <= limite) return p
        var coupe = p.substring(0, p.offsetByCodePoints(0, limite))
        val espace = maxOf(coupe.lastIndexOf(' '), coupe.lastIndexOf('\n'))
        if (espace >= coupe.length - 80) coupe = coupe.substring(0, espace)
        return coupe.trimEnd() + COUPE
    }

    /** Message à envoyer : la citation puis `corps`. Sans citation valable : `corps` tel quel. */
    fun composer(auteur: Auteur?, cite: String?, corps: String = ""): String {
        val t = propre(cite)
        if (auteur == null || t.isEmpty()) return corps
        val tete = (listOf("> **${auteur.etiquette} :**") + t.split("\n").map { if (it.isNotBlank()) "> $it" else ">" })
            .joinToString("\n")
        return if (corps.isNotEmpty()) "$tete\n\n$corps" else tete
    }

    /** Citation en tête d'un message de l'utilisateur, ou null. */
    fun decouper(texte: String?): Decoupe? {
        if (texte == null || !texte.startsWith("> **")) return null
        val lignes = texte.replace("\r\n", "\n").split("\n")
        val auteur = Auteur.entries.firstOrNull { lignes[0].trimEnd() == "> **${it.etiquette} :**" } ?: return null
        val cite = ArrayList<String>()
        var i = 1
        while (i < lignes.size && lignes[i].startsWith(">")) {
            val l = lignes[i].substring(1)
            cite.add(if (l.startsWith(" ")) l.substring(1) else l)
            i++
        }
        val texteCite = cite.joinToString("\n").trim()
        if (texteCite.isEmpty()) return null
        var reste = lignes.drop(i)
        if (reste.isNotEmpty() && reste[0].isBlank()) reste = reste.drop(1)
        return Decoupe(auteur, texteCite, reste.joinToString("\n"))
    }

    /** Texte d'un message de l'utilisateur à citer à son tour : sa réponse, pas ce qu'il citait. */
    fun texteSource(texte: String): String {
        val d = decouper(texte) ?: return texte
        return if (d.corps.isNotBlank()) d.corps else d.texte
    }

    /** Ce qu'on cite d'un message entier (`brut` : son texte d'origine). */
    fun de(auteur: Auteur, brut: String): Cite? {
        val t = extrait(if (auteur == Auteur.Moi) texteSource(brut) else brut)
        return if (t.isEmpty()) null else Cite(auteur, t)
    }

    /** Aperçu sur une ligne (bandeau au-dessus de la saisie). */
    fun uneLigne(texte: String?, limite: Int = 140): String {
        val l = (texte ?: "").split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")
        return if (l.length > limite) l.take(limite - 1) + "…" else l
    }
}
