package com.mawena.ccs.logique

/**
 * Markdown des réponses de Claude, lu en blocs (titres, paragraphes, listes, code, citations,
 * tableaux, règles) et en segments de texte stylés (gras, italique, code, barré, liens). Sans
 * Android : l'écran construit ses textes à partir de ce résultat. Tolérant : un texte en cours
 * d'arrivée (bloc de code pas encore fermé, `**` sans fin) se lit sans erreur.
 */
object Markdown {
    sealed interface Bloc

    data class Titre(val niveau: Int, val contenu: List<Segment>) : Bloc
    data class Paragraphe(val contenu: List<Segment>) : Bloc
    data class Liste(val elements: List<Element>) : Bloc
    data class Code(val langue: String, val texte: String) : Bloc
    data class Citation(val blocs: List<Bloc>) : Bloc
    data class Tableau(val entetes: List<List<Segment>>, val lignes: List<List<List<Segment>>>) : Bloc
    data object Regle : Bloc

    /** Élément d'une liste : niveau d'imbrication (0, 1…), marque (« • », « 3. »), case à cocher. */
    data class Element(val niveau: Int, val marque: String, val contenu: List<Segment>, val coche: Boolean? = null)

    data class Segment(
        val texte: String,
        val gras: Boolean = false,
        val italique: Boolean = false,
        val code: Boolean = false,
        val barre: Boolean = false,
        val lien: String? = null,
        /** Image `![alt](src)` : `texte` est le texte de remplacement, `lien` la source. */
        val image: Boolean = false,
    )

    private val FENCE = Regex("^ {0,3}(`{3,}|~{3,})\\s*([^`\\s]*)?.*$")
    private val TITRE = Regex("^ {0,3}(#{1,6})\\s+(.*?)\\s*#*\\s*$")
    private val REGLE = Regex("^ {0,3}([-*_])(\\s*\\1){2,}\\s*$")
    private val PUCE = Regex("^(\\s*)([-*+]|\\d{1,9}[.)])\\s+(.*)$")
    private val SEP_TABLEAU = Regex("^\\s*\\|?\\s*:?-{1,}:?\\s*(\\|\\s*:?-{1,}:?\\s*)*\\|?\\s*$")
    private val COCHE = Regex("^\\[([ xX])]\\s+(.*)$")

    fun analyser(md: String): List<Bloc> = blocs(md.replace("\r\n", "\n").split("\n"))

    private fun estDebutBloc(l: String): Boolean =
        FENCE.matches(l) || TITRE.matches(l) || REGLE.matches(l) || l.trimStart().startsWith(">") || PUCE.matches(l)

    private fun blocs(lignes: List<String>): List<Bloc> {
        val out = ArrayList<Bloc>()
        var i = 0
        while (i < lignes.size) {
            val l = lignes[i]
            if (l.isBlank()) { i++; continue }
            val fence = FENCE.matchEntire(l)
            if (fence != null) {
                val marque = fence.groupValues[1]
                val langue = fence.groupValues[2]
                val code = ArrayList<String>()
                i++
                while (i < lignes.size) {
                    val t = lignes[i].trimStart()
                    if (t.startsWith(marque.substring(0, 3)) && t.trimEnd().all { it == marque[0] } && t.trimEnd().length >= marque.length) { i++; break }
                    code.add(lignes[i])
                    i++
                }
                out.add(Code(langue.lowercase(), code.joinToString("\n")))
                continue
            }
            val titre = TITRE.matchEntire(l)
            if (titre != null) {
                out.add(Titre(titre.groupValues[1].length, enLigne(titre.groupValues[2])))
                i++
                continue
            }
            if (REGLE.matches(l)) { out.add(Regle); i++; continue }
            if (l.trimStart().startsWith(">")) {
                val dedans = ArrayList<String>()
                while (i < lignes.size && lignes[i].trimStart().startsWith(">")) {
                    val t = lignes[i].trimStart().substring(1)
                    dedans.add(if (t.startsWith(" ")) t.substring(1) else t)
                    i++
                }
                out.add(Citation(blocs(dedans)))
                continue
            }
            if (PUCE.matches(l)) {
                val (liste, suite) = liste(lignes, i)
                out.add(liste)
                i = suite
                continue
            }
            if (l.contains('|') && i + 1 < lignes.size && SEP_TABLEAU.matches(lignes[i + 1]) && lignes[i + 1].contains('-')) {
                val entetes = cellules(l)
                i += 2
                val rangs = ArrayList<List<List<Segment>>>()
                while (i < lignes.size && lignes[i].contains('|') && lignes[i].isNotBlank()) {
                    rangs.add(cellules(lignes[i]))
                    i++
                }
                out.add(Tableau(entetes, rangs))
                continue
            }
            // paragraphe : lignes jusqu'à une ligne vide ou un autre bloc
            val texte = StringBuilder()
            while (i < lignes.size && lignes[i].isNotBlank() && (texte.isEmpty() || !estDebutBloc(lignes[i]))) {
                val brut = lignes[i]
                val dure = brut.endsWith("  ") || brut.endsWith("\\")
                val t = brut.trim().removeSuffix("\\")
                if (texte.isNotEmpty()) texte.append(if (texte.endsWith("\n")) "" else " ")
                texte.append(t)
                if (dure) texte.append("\n")
                i++
            }
            out.add(Paragraphe(enLigne(texte.toString().trimEnd('\n'))))
        }
        return out
    }

    private fun liste(lignes: List<String>, debut: Int): Pair<Liste, Int> {
        val elements = ArrayList<Element>()
        val retraits = ArrayList<Int>()        // retrait de chaque niveau ouvert
        var i = debut
        var courant: StringBuilder? = null
        var marque = ""
        var niveau = 0
        fun fermer() {
            val c = courant ?: return
            val m = COCHE.matchEntire(c.toString())
            elements.add(
                if (m != null) Element(niveau, marque, enLigne(m.groupValues[2]), m.groupValues[1] != " ")
                else Element(niveau, marque, enLigne(c.toString())),
            )
            courant = null
        }
        while (i < lignes.size) {
            val l = lignes[i]
            val p = PUCE.matchEntire(l)
            if (p != null) {
                fermer()
                val retrait = p.groupValues[1].replace("\t", "    ").length
                while (retraits.isNotEmpty() && retraits.last() > retrait) retraits.removeAt(retraits.size - 1)
                if (retraits.isEmpty() || retraits.last() < retrait) retraits.add(retrait)
                niveau = retraits.size - 1
                val m = p.groupValues[2]
                marque = if (m[0].isDigit()) m.dropLast(1) + "." else "•"
                courant = StringBuilder(p.groupValues[3].trim())
                i++
                continue
            }
            if (l.isBlank()) {
                // une ligne vide puis un élément ou une suite en retrait : la liste continue
                val n = lignes.getOrNull(i + 1)
                if (n != null && (PUCE.matches(n) || (n.startsWith("  ") && n.isNotBlank() && !FENCE.matches(n)))) { i++; continue }
                break
            }
            if (courant != null && (l.startsWith(" ") || l.startsWith("\t")) && !FENCE.matches(l)) {
                courant!!.append(' ').append(l.trim())
                i++
                continue
            }
            if (courant != null && !estDebutBloc(l) && !l.contains('|')) {    // suite paresseuse
                courant!!.append(' ').append(l.trim())
                i++
                continue
            }
            break
        }
        fermer()
        return Liste(elements) to i
    }

    private fun cellules(l: String): List<List<Segment>> {
        var t = l.trim()
        if (t.startsWith("|")) t = t.substring(1)
        if (t.endsWith("|") && !t.endsWith("\\|")) t = t.dropLast(1)
        val out = ArrayList<String>()
        val c = StringBuilder()
        var code = false
        var k = 0
        while (k < t.length) {
            val ch = t[k]
            when {
                ch == '\\' && k + 1 < t.length && t[k + 1] == '|' -> { c.append('|'); k++ }
                ch == '`' -> { code = !code; c.append(ch) }
                ch == '|' && !code -> { out.add(c.toString()); c.clear() }
                else -> c.append(ch)
            }
            k++
        }
        out.add(c.toString())
        return out.map { enLigne(it.trim()) }
    }

    // ---- en ligne --------------------------------------------------------------------------

    private data class Style(val gras: Boolean = false, val italique: Boolean = false, val barre: Boolean = false, val lien: String? = null)

    private const val PONCTUATION = "\\`*_{}[]()#+-.!|~<>\"'"
    private val URL = Regex("https?://[^\\s<>\"]+")
    private val AUTO = Regex("<(https?://[^\\s>]+)>")

    fun enLigne(t: String): List<Segment> {
        val out = ArrayList<Segment>()
        enLigne(t, Style(), out)
        // segments voisins de même style réunis
        val fusion = ArrayList<Segment>()
        for (s in out) {
            val d = fusion.lastOrNull()
            if (d != null && !s.image && d.copy(texte = s.texte) == s) fusion[fusion.size - 1] = d.copy(texte = d.texte + s.texte)
            else fusion.add(s)
        }
        return fusion
    }

    private fun motAvant(s: String, i: Int) = i > 0 && s[i - 1].isLetterOrDigit()

    private fun enLigne(s: String, st: Style, out: MutableList<Segment>) {
        val buf = StringBuilder()
        fun vider() {
            if (buf.isNotEmpty()) out.add(Segment(buf.toString(), st.gras, st.italique, false, st.barre, st.lien))
            buf.clear()
        }
        fun entoure(i: Int, d: String, nouveau: Style): Int? {
            val debut = i + d.length
            if (debut >= s.length || s[debut].isWhitespace()) return null
            var f = s.indexOf(d, debut + 1)
            while (f >= 0) {
                val seul = d.length > 1 || ((f + 1 >= s.length || s[f + 1] != d[0]) && s[f - 1] != d[0])
                if (!s[f - 1].isWhitespace() && seul) break
                f = s.indexOf(d, f + 1)
            }
            if (f < 0) return null
            if (d[0] == '_' && f + d.length < s.length && s[f + d.length].isLetterOrDigit()) return null
            vider()
            enLigne(s.substring(debut, f), nouveau, out)
            return f + d.length
        }
        var i = 0
        while (i < s.length) {
            val c = s[i]
            if (c == '\\' && i + 1 < s.length && s[i + 1] in PONCTUATION) { buf.append(s[i + 1]); i += 2; continue }
            if (c == '`') {
                var n = 0
                while (i + n < s.length && s[i + n] == '`') n++
                val marque = "`".repeat(n)
                var f = s.indexOf(marque, i + n)
                while (f >= 0 && f + n < s.length && s[f + n] == '`') f = s.indexOf(marque, f + n + 1)
                if (f < 0) { buf.append(marque); i += n; continue }
                vider()
                var code = s.substring(i + n, f)
                if (code.length >= 2 && code.startsWith(" ") && code.endsWith(" ") && code.isNotBlank()) code = code.substring(1, code.length - 1)
                out.add(Segment(code, st.gras, st.italique, true, st.barre, st.lien))
                i = f + n
                continue
            }
            if (s.startsWith("***", i) || s.startsWith("___", i)) {
                val f = entoure(i, s.substring(i, i + 3), st.copy(gras = true, italique = true))
                if (f != null) { i = f; continue }
            }
            if (s.startsWith("**", i) || (s.startsWith("__", i) && !motAvant(s, i))) {
                val f = entoure(i, s.substring(i, i + 2), st.copy(gras = true))
                if (f != null) { i = f; continue }
            }
            if (s.startsWith("~~", i)) {
                val f = entoure(i, "~~", st.copy(barre = true))
                if (f != null) { i = f; continue }
            }
            if (c == '*' || (c == '_' && !motAvant(s, i))) {
                val f = entoure(i, c.toString(), st.copy(italique = true))
                if (f != null) { i = f; continue }
            }
            if ((c == '!' && i + 1 < s.length && s[i + 1] == '[') || (c == '[' && st.lien == null)) {
                val l = lien(s, if (c == '!') i + 1 else i)
                if (l != null && c == '!') {
                    vider()
                    out.add(Segment(l.first.ifEmpty { l.second }, st.gras, st.italique, false, st.barre, l.second, image = true))
                    i = l.third
                    continue
                }
                if (l != null) {
                    vider()
                    enLigne(l.first.ifEmpty { l.second }, st.copy(lien = l.second), out)
                    i = l.third
                    continue
                }
            }
            if (c == '<' && st.lien == null) {
                val m = AUTO.matchAt(s, i)
                if (m != null) {
                    vider(); out.add(Segment(m.groupValues[1], st.gras, st.italique, false, st.barre, m.groupValues[1]))
                    i += m.value.length
                    continue
                }
            }
            if (c == 'h' && st.lien == null && !motAvant(s, i)) {
                val m = URL.matchAt(s, i)
                if (m != null) {
                    val url = rognerUrl(m.value)
                    vider(); out.add(Segment(url, st.gras, st.italique, false, st.barre, url))
                    i += url.length
                    continue
                }
            }
            buf.append(c)
            i++
        }
        vider()
    }

    /** Ponctuation finale qui n'appartient pas au lien (« voir https://x.fr. »), parenthèses équilibrées. */
    fun rognerUrl(u: String): String {
        var url = u
        while (url.isNotEmpty()) {
            val d = url.last()
            if (d in ".,;:!?'\"*_" || (d == ')' && url.count { it == '(' } < url.count { it == ')' })) url = url.dropLast(1)
            else break
        }
        return url
    }

    /** `[texte](url)` qui commence à `i` : texte, adresse et fin ; null sinon. */
    private fun lien(s: String, i: Int): Triple<String, String, Int>? {
        var prof = 0
        var k = i
        while (k < s.length) {
            when (s[k]) {
                '[' -> prof++
                ']' -> { prof--; if (prof == 0) break }
                '\\' -> k++
            }
            k++
        }
        if (k >= s.length || k + 1 >= s.length || s[k + 1] != '(') return null
        var f = k + 2
        var p = 1
        while (f < s.length) {
            if (s[f] == '(') p++
            if (s[f] == ')') { p--; if (p == 0) break }
            f++
        }
        if (f >= s.length) return null
        val dedans = s.substring(k + 2, f).trim()
        val url = dedans.split(Regex("\\s+"), 2)[0].removePrefix("<").removeSuffix(">")
        if (url.isEmpty()) return null
        return Triple(s.substring(i + 1, k), url, f + 1)
    }

    /** Texte brut d'un bloc (recherche, copie). */
    fun texte(segments: List<Segment>) = segments.joinToString("") { it.texte }
}
