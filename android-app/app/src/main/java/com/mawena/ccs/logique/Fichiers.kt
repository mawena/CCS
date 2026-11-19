package com.mawena.ccs.logique

/**
 * Chemins et textes du gestionnaire de fichiers, sans Android (`web/files*.js`) : chemins relatifs,
 * fil d'Ariane, famille d'un fichier (icône, coloration), tailles, confirmations.
 */
object Fichiers {
    const val MORCEAU = 1024 * 1024                 // octets par morceau, comme le pont (CHUNK)
    const val MAX_TRANSFERT = 200L * 1024 * 1024     // 200 Mo, comme le pont

    fun nom(chemin: String): String = chemin.trimEnd('/').substringAfterLast('/').ifEmpty { "/" }

    fun parent(chemin: String): String {
        val c = chemin.trimEnd('/')
        val i = c.lastIndexOf('/')
        return if (i <= 0) "/" else c.substring(0, i)
    }

    fun joindre(base: String, rel: String): String =
        if (rel.isEmpty()) base else "${base.trimEnd('/')}/${rel.trimStart('/')}"

    fun sous(chemin: String, racine: String): Boolean {
        val r = racine.trimEnd('/')
        return chemin == racine || chemin == r || chemin.startsWith("$r/") || r.isEmpty()
    }

    /** Chemin relatif à `base` (vide si c'est `base`), ou null s'il n'est pas dedans. */
    fun relatif(chemin: String, base: String): String? {
        val b = base.trimEnd('/')
        val c = chemin.trimEnd('/').ifEmpty { "/" }
        return when {
            c == b || (b.isEmpty() && c == "/") -> ""
            c.startsWith("$b/") -> c.substring(b.length + 1)
            else -> null
        }
    }

    /** Racine (la plus longue) qui contient `chemin`, sinon `defaut`. */
    fun racineDe(chemin: String, racines: List<String>, defaut: String): String =
        racines.filter { sous(chemin, it) }.maxByOrNull { it.length } ?: defaut

    /** Fil d'Ariane : (libellé, chemin absolu) depuis `base` (« Personnel » si c'est `home`). */
    fun ariane(chemin: String, base: String, home: String): List<Pair<String, String>> {
        val out = mutableListOf((if (base == home) "Personnel" else base) to base)
        val rel = relatif(chemin, base) ?: return out
        var at = base
        for (p in rel.split('/').filter { it.isNotEmpty() }) {
            at = joindre(at, p)
            out.add(p to at)
        }
        return out
    }

    enum class Genre { Dossier, Fichier, Texte, Code, Config, Image, Archive, Media, Document }

    private val PAR_EXTENSION: Map<String, Genre> = buildMap {
        fun mettre(g: Genre, t: String) = t.split(' ').forEach { put(it, g) }
        mettre(Genre.Image, "png jpg jpeg gif webp svg bmp ico avif heic tif tiff")
        mettre(Genre.Code, "js mjs cjs ts tsx jsx py rb go rs c h cc cpp hpp java kt kts swift php sh bash zsh fish lua pl r sql css scss less html htm vue svelte dart cs gradle")
        mettre(Genre.Config, "json yaml yml toml ini cfg conf env xml lock service desktop gitignore editorconfig properties")
        mettre(Genre.Texte, "txt md markdown rst log csv tsv tex org adoc")
        mettre(Genre.Archive, "zip tar gz tgz bz2 xz zst 7z rar deb rpm jar war iso apk")
        mettre(Genre.Media, "mp3 wav ogg flac m4a opus mp4 mkv webm avi mov")
        mettre(Genre.Document, "pdf odt ods odp doc docx xls xlsx ppt pptx epub")
    }
    private val PAR_NOM = mapOf("makefile" to Genre.Code, "dockerfile" to Genre.Code, "license" to Genre.Texte,
        "readme" to Genre.Texte, "changelog" to Genre.Texte)

    fun extension(nom: String): String {
        val n = nom.lowercase()
        val i = n.lastIndexOf('.')
        return if (i >= 0) n.substring(i + 1) else ""
    }

    fun genre(nom: String, dossier: Boolean = false): Genre {
        if (dossier) return Genre.Dossier
        val n = nom.lowercase()
        return PAR_EXTENSION[extension(n)] ?: PAR_NOM[n] ?: if (n.startsWith(".")) Genre.Config else Genre.Fichier
    }

    /** Langue de coloration (celle des blocs de code du chat) d'après le nom du fichier. */
    fun langue(nom: String): String {
        val n = nom.lowercase()
        if (n == "makefile" || n == "gnumakefile") return "make"
        if (n == "dockerfile" || n.startsWith("dockerfile.")) return "dockerfile"
        if (n == ".env" || n.startsWith(".env.")) return "env"
        return when (val e = extension(n)) {
            "service", "desktop", "cfg", "editorconfig", "gitconfig" -> "ini"
            "markdown" -> "md"
            "zsh", "bash", "fish" -> "sh"
            else -> e
        }
    }

    fun estMarkdown(nom: String): Boolean = extension(nom) in setOf("md", "markdown")

    /** Taille lisible, comme la version web : « 512 o », « 12 Ko », « 3,4 Mo ». */
    fun taille(n: Long): String = when {
        n < 1024 -> "$n o"
        n < 1024 * 1024 -> "${Math.round(n / 1024.0)} Ko"
        else -> String.format(java.util.Locale.ROOT, "%.1f", n / 1024.0 / 1024.0).replace('.', ',') + " Mo"
    }

    /** Texte de la confirmation de suppression (d'après `files.info`). */
    fun texteSuppression(dossier: Boolean, nombre: Int, octets: Long): String = when {
        dossier && nombre > 0 -> "Ce dossier et les $nombre éléments qu'il contient seront supprimés pour de bon."
        dossier -> "Ce dossier vide sera supprimé."
        else -> "Ce fichier (${taille(octets)}) sera supprimé pour de bon."
    }

    /** Message d'erreur d'un nom refusé, ou null s'il convient (le pont vérifie aussi). */
    fun nomRefuse(nom: String): String? = when {
        nom.isBlank() -> "Le nom est vide."
        nom == "." || nom == ".." || '/' in nom || '\u0000' in nom -> "Nom refusé : pas de « / », ni « . » ou « .. »."
        nom.toByteArray(Charsets.UTF_8).size > 255 -> "Nom trop long (255 octets au plus)."
        else -> null
    }

    private val MARQUES = mapOf("M" to "modifié", "A" to "ajouté", "?" to "nouveau", "D" to "supprimé")
    fun marque(m: String): String = MARQUES[m].orEmpty()

    /** Positions (début, longueur) des morceaux d'un envoi de `total` octets (au moins un, même vide). */
    fun morceaux(total: Long, morceau: Int = MORCEAU): List<Pair<Long, Int>> {
        if (total <= 0) return listOf(0L to 0)
        val out = ArrayList<Pair<Long, Int>>()
        var o = 0L
        while (o < total) {
            val n = minOf(morceau.toLong(), total - o).toInt()
            out.add(o to n)
            o += n
        }
        return out
    }

    /** Découpe un texte en lignes pour l'affichage numéroté (sans ligne vide finale de trop). */
    fun lignes(texte: String): List<String> {
        val l = texte.replace("\r\n", "\n").split('\n')
        return if (l.size > 1 && l.last().isEmpty()) l.dropLast(1) else l
    }
}
