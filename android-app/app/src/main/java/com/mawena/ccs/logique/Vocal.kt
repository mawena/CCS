package com.mawena.ccs.logique

/**
 * Vocal sans Android (phase 35) : texte d'une réponse préparé pour la lecture à voix haute,
 * découpé en morceaux que la synthèse accepte, texte dicté ajouté à la saisie, réponse à lire en
 * fin de tour.
 */
object Vocal {
    private val CLOTURE = Regex("^\\s*(```|~~~)")
    private val IMAGE = Regex("!\\[([^\\]]*)]\\([^)]*\\)")
    private val LIEN = Regex("\\[([^\\]]+)]\\([^)]*\\)")
    private val LIEN_REF = Regex("\\[([^\\]]+)]\\[[^\\]]*]")
    private val AUTOLIEN = Regex("<(https?://[^>\\s]+)>")
    private val URL = Regex("https?://\\S+")
    private val CODE_EN_LIGNE = Regex("`+([^`]*)`+")
    private val TITRE = Regex("^#{1,6}\\s+(.*?)\\s*#*\\s*$")
    private val CITATION = Regex("^(>\\s?)+")
    private val PUCE = Regex("^([-*+]|\\d+[.)])\\s+(\\[[ xX]]\\s+)?")
    private val REGLE = Regex("^\\s*([-*_]\\s*){3,}$")
    private val SEPARATEUR_TABLEAU = Regex("^\\s*\\|?\\s*:?-+:?\\s*(\\|\\s*:?-+:?\\s*)*\\|?\\s*$")
    private val SOULIGNE = Regex("(?<![\\p{L}\\p{N}])_{1,2}([^_\\n]+?)_{1,2}(?![\\p{L}\\p{N}])")
    private val BARRE = Regex("~~(.+?)~~")
    private val HTML = Regex("</?[a-zA-Z][^>]*>")
    private val ESPACES = Regex("[ \\t]{2,}")
    private val FIN_PHRASE = Regex("[.!?:;,…]$")

    /**
     * Markdown d'une réponse de Claude rendu lisible à voix haute : blocs de code remplacés par
     * « bloc de code », liens et images réduits à leur texte, adresses par « lien », astérisques,
     * dièses, puces, citations et barres des tableaux retirés. Titres et puces finissent par un
     * point (la voix marque la pause).
     */
    fun pourLecture(markdown: String): String {
        val lignes = ArrayList<String>()
        var dansCode = false
        var cloture = ""
        for (brute in markdown.replace("\r\n", "\n").split('\n')) {
            val ouverture = CLOTURE.find(brute)
            if (dansCode) {
                if (ouverture != null && ouverture.groupValues[1] == cloture) dansCode = false
                continue
            }
            if (ouverture != null) {
                dansCode = true
                cloture = ouverture.groupValues[1]
                lignes.add("Bloc de code.")
                continue
            }
            ligne(brute)?.let(lignes::add)
        }
        // lignes vides consécutives réduites à une seule, ni au début ni à la fin
        return lignes.joinToString("\n").replace(PARAGRAPHES, "\n\n").trim()
    }

    private val PARAGRAPHES = Regex("\n{3,}")

    /** Une ligne hors bloc de code ; null : ligne retirée (séparateur d'un tableau). */
    private fun ligne(brute: String): String? {
        var t = brute.trim()
        if (t.isEmpty() || REGLE.matches(t)) return ""
        if (SEPARATEUR_TABLEAU.matches(t)) return null
        var pause = false
        TITRE.matchEntire(t)?.let { t = it.groupValues[1]; pause = true }
        t = t.replace(CITATION, "")
        PUCE.find(t)?.let { t = t.substring(it.range.last + 1); pause = true }
        if (t.startsWith("|") || t.endsWith("|")) {
            t = t.trim('|').split('|').map { it.trim() }.filter { it.isNotEmpty() }.joinToString(", ")
            pause = true
        }
        t = t.replace(IMAGE) { it.groupValues[1] }
            .replace(LIEN) { it.groupValues[1] }
            .replace(LIEN_REF) { it.groupValues[1] }
            .replace(AUTOLIEN, "lien")
            .replace(URL, "lien")
            .replace(CODE_EN_LIGNE) { it.groupValues[1] }
            .replace(BARRE) { it.groupValues[1] }
            .replace(HTML, "")
            .replace("*", "")
            .replace(SOULIGNE) { it.groupValues[1] }
            .replace("#", "")
            .replace(ESPACES, " ")
            .trim()
        if (pause && t.isNotEmpty() && !FIN_PHRASE.containsMatchIn(t)) t += "."
        return t
    }

    /**
     * Texte découpé en morceaux d'au plus [max] caractères pour la synthèse (elle refuse les
     * textes trop longs) : coupe de préférence entre deux paragraphes, puis après une phrase,
     * puis à une espace.
     */
    fun decouper(texte: String, max: Int): List<String> {
        require(max > 0)
        val morceaux = ArrayList<String>()
        var reste = texte.trim()
        while (reste.length > max) {
            val fenetre = reste.substring(0, max)
            val coupe = listOf(
                fenetre.lastIndexOf('\n'),
                maxOf(fenetre.lastIndexOf(". "), fenetre.lastIndexOf("! "), fenetre.lastIndexOf("? ")).let { if (it >= 0) it + 1 else -1 },
                fenetre.lastIndexOf(' '),
            ).firstOrNull { it > max / 4 } ?: max
            morceaux.add(reste.substring(0, coupe).trim())
            reste = reste.substring(coupe).trim()
        }
        if (reste.isNotEmpty()) morceaux.add(reste)
        return morceaux.filter { it.isNotEmpty() }
    }

    /** Texte dicté ajouté à la saisie : séparé par une espace si le texte d'avant n'en finit pas par une. */
    fun ajouterDictee(avant: String, dicte: String): String {
        val d = dicte.trim()
        return when {
            d.isEmpty() -> avant
            avant.isEmpty() || avant.last().isWhitespace() -> avant + d
            else -> "$avant $d"
        }
    }

    /** Dernière réponse de Claude du tour en cours (après le dernier message de l'utilisateur), ou null. */
    fun derniereReponse(elements: List<ElementFil>): ElementFil.MsgClaude? {
        for (e in elements.asReversed()) when (e) {
            is ElementFil.MsgClaude -> if (e.texte.isNotBlank()) return e
            is ElementFil.MsgToi -> return null
            else -> Unit
        }
        return null
    }
}
