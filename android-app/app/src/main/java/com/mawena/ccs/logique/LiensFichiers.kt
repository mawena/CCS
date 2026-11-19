package com.mawena.ccs.logique

/**
 * Chemins cités dans une réponse de Claude (`chemin` ou `chemin:ligne`) qui sont des fichiers du
 * projet (`web/chat-links.js`) : ils deviennent des liens qui ouvrent le fichier.
 */
class LiensFichiers(val cwd: String, val fichiers: Set<String>) {
    data class Ref(val chemin: String, val ligne: Int?, val texte: String = "", val index: Int = 0)

    /** Chemin relatif au projet + ligne si `texte` désigne un fichier connu. */
    fun ref(texte: String): Ref? {
        val m = REF.matchEntire(texte.trim()) ?: return null
        var chemin = m.groupValues[1]
        if (chemin.startsWith("/")) {
            if (!chemin.startsWith("${cwd.trimEnd('/')}/")) return null
            chemin = chemin.substring(cwd.trimEnd('/').length + 1)
        } else if (chemin.startsWith("./")) chemin = chemin.substring(2)
        if (".." in chemin.split('/') || chemin !in fichiers) return null
        return Ref(chemin, m.groupValues[2].toIntOrNull())
    }

    /** Références trouvées dans un texte libre. */
    fun trouver(texte: String): List<Ref> {
        if (fichiers.isEmpty()) return emptyList()
        val out = ArrayList<Ref>()
        for (m in DANS_TEXTE.findAll(texte)) {
            val avant = m.groupValues[1]
            val t = m.value.substring(avant.length)
            val r = ref(t) ?: continue
            out.add(r.copy(texte = t, index = m.range.first + avant.length))
        }
        return out
    }

    fun absolu(r: Ref): String = Fichiers.joindre(cwd, r.chemin)

    companion object {
        private val REF = Regex("^(/?[\\w@+.-]+(?:/[\\w@+.-]+)*)(?::(\\d+)(?::\\d+)?)?$")
        private val DANS_TEXTE = Regex("(^|[^\\w/.@+-])(\\.?/?[\\w@+.-]+(?:/[\\w@+.-]+)*\\.[A-Za-z0-9]+)(?::(\\d+)(?::\\d+)?)?")
    }
}
