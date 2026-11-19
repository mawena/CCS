package com.mawena.ccs.logique

/**
 * Coloration simple des blocs de code : mots-clés, chaînes, commentaires, nombres (et lignes
 * ajoutées / retirées d'un diff). Un seul passage, sans expressions régulières par jeton : assez
 * rapide pour recolorer un bloc à chaque morceau de réponse. Langue inconnue : chaînes et nombres.
 */
object Coloration {
    enum class Genre { MotCle, Chaine, Commentaire, Nombre, Ajout, Retrait, Titre }

    data class Jeton(val debut: Int, val fin: Int, val genre: Genre)

    private class Famille(
        val ligne: List<String>,               // débuts de commentaire jusqu'à la fin de la ligne
        val bloc: List<Pair<String, String>>,  // commentaires en bloc
        val chaines: String,                   // délimiteurs de chaîne
        val motsCles: Set<String>,
        val casse: Boolean = true,
        val triples: Boolean = false,          // """ et ''' (Python, Kotlin)
    )

    private fun mots(t: String) = t.split(' ').filter { it.isNotEmpty() }.toSet()

    private val C_LIKE = mots(
        "if else for while do switch case default break continue return goto struct union enum typedef " +
            "static const volatile extern sizeof void int char long short float double unsigned signed bool true false " +
            "null nullptr class public private protected virtual template typename namespace using new delete this " +
            "auto inline include define ifdef ifndef endif",
    )
    private val JS = mots(
        "if else for while do switch case default break continue return function var let const class extends " +
            "new this super import export from as async await yield try catch finally throw typeof instanceof in of " +
            "true false null undefined void delete static get set interface type enum implements public private " +
            "protected readonly declare namespace keyof any unknown never string number boolean",
    )
    private val KOTLIN_JAVA = mots(
        "if else for while do when switch case default break continue return fun val var class object interface " +
            "data sealed enum abstract open override private public protected internal companion init constructor " +
            "this super null true false is as in out import package try catch finally throw new static final void " +
            "int long boolean char byte short double float extends implements lateinit suspend inline typealias by",
    )
    private val PYTHON = mots(
        "if elif else for while break continue return def class import from as try except finally raise with " +
            "lambda yield pass global nonlocal assert del in is not and or None True False async await self match case",
    )
    private val SHELL = mots(
        "if then else elif fi for while until do done case esac in function return local export readonly " +
            "set unset shift exit echo cd source alias sudo",
    )
    private val GO = mots(
        "break case chan const continue default defer else fallthrough for func go goto if import interface map " +
            "package range return select struct switch type var true false nil",
    )
    private val RUST = mots(
        "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod " +
            "move mut pub ref return self Self static struct super trait true type unsafe use where while Some None Ok Err",
    )
    private val SQL = mots(
        "select from where insert into values update set delete create table drop alter add index primary key " +
            "foreign references join left right inner outer on group by order having limit offset as and or not null " +
            "is in exists distinct union all case when then else end begin commit rollback default unique",
    )
    private val PHP = JS + mots("echo elseif endif foreach endforeach require require_once include_once namespace use fn match")
    private val YAML = mots("true false null yes no on off")
    private val CSS = mots("important media import keyframes from to")

    private val SLASH = listOf("//")
    private val BLOC_C = listOf("/*" to "*/")

    private val FAMILLES: Map<String, Famille> = buildMap {
        val c = Famille(SLASH, BLOC_C, "\"'", C_LIKE)
        val js = Famille(SLASH, BLOC_C, "\"'`", JS)
        val kt = Famille(SLASH, BLOC_C, "\"'", KOTLIN_JAVA, triples = true)
        val py = Famille(listOf("#"), emptyList(), "\"'", PYTHON, triples = true)
        val sh = Famille(listOf("#"), emptyList(), "\"'", SHELL)
        for (n in listOf("c", "h", "cpp", "c++", "cc", "hpp", "cs", "csharp", "objc", "swift", "dart", "scala")) put(n, c)
        for (n in listOf("js", "javascript", "jsx", "ts", "typescript", "tsx", "mjs", "cjs", "json5", "vue", "svelte")) put(n, js)
        for (n in listOf("kotlin", "kt", "kts", "java", "groovy", "gradle")) put(n, kt)
        for (n in listOf("python", "py", "python3")) put(n, py)
        for (n in listOf("sh", "bash", "shell", "zsh", "console", "shellsession", "fish", "dockerfile", "docker", "makefile", "make")) put(n, sh)
        put("go", Famille(SLASH, BLOC_C, "\"'`", GO))
        put("rust", Famille(SLASH, BLOC_C, "\"", RUST)); put("rs", get("rust")!!)
        put("sql", Famille(listOf("--"), BLOC_C, "'\"", SQL, casse = false))
        put("lua", Famille(listOf("--"), emptyList(), "\"'", mots("and break do else elseif end false for function if in local nil not or repeat return then true until while")))
        put("php", Famille(listOf("//", "#"), BLOC_C, "\"'", PHP))
        for (n in listOf("yaml", "yml", "toml", "ini", "conf", "nginx", "properties", "env")) put(n, Famille(listOf("#"), emptyList(), "\"'", YAML))
        put("json", Famille(emptyList(), emptyList(), "\"", mots("true false null")))
        for (n in listOf("css", "scss", "sass", "less")) put(n, Famille(SLASH, BLOC_C, "\"'", CSS))
        for (n in listOf("html", "xml", "svg", "htm")) put(n, Famille(emptyList(), listOf("<!--" to "-->"), "\"'", emptySet()))
    }

    private const val MAX = 30_000            // au-delà : pas de coloration (bloc énorme)

    fun jetons(code: String, langue: String): List<Jeton> {
        if (code.length > MAX) return emptyList()
        val l = langue.lowercase()
        if (l == "diff" || l == "patch") return diff(code)
        if (l == "md" || l == "markdown") return titresMarkdown(code)
        val f = FAMILLES[l] ?: Famille(emptyList(), emptyList(), "\"", emptySet())
        val out = ArrayList<Jeton>()
        var i = 0
        val n = code.length
        while (i < n) {
            val c = code[i]
            // commentaire de ligne (en début de mot : « a#b » en shell n'en est pas un)
            val ligne = f.ligne.firstOrNull { code.startsWith(it, i) }
            if (ligne != null && (ligne != "#" || i == 0 || code[i - 1].isWhitespace())) {
                val fin = code.indexOf('\n', i).let { if (it < 0) n else it }
                out.add(Jeton(i, fin, Genre.Commentaire))
                i = fin
                continue
            }
            val bloc = f.bloc.firstOrNull { code.startsWith(it.first, i) }
            if (bloc != null) {
                val fin = code.indexOf(bloc.second, i + bloc.first.length).let { if (it < 0) n else it + bloc.second.length }
                out.add(Jeton(i, fin, Genre.Commentaire))
                i = fin
                continue
            }
            if (c in f.chaines) {
                val triple = f.triples && code.startsWith("$c$c$c", i)
                val fin = if (triple) code.indexOf("$c$c$c", i + 3).let { if (it < 0) n else it + 3 } else finChaine(code, i, c)
                out.add(Jeton(i, fin, Genre.Chaine))
                i = fin
                continue
            }
            if (c.isDigit() && (i == 0 || !code[i - 1].isLetterOrDigit() && code[i - 1] != '_')) {
                var k = i + 1
                while (k < n && (code[k].isLetterOrDigit() || code[k] == '.' || code[k] == '_')) k++
                out.add(Jeton(i, k, Genre.Nombre))
                i = k
                continue
            }
            if (c.isLetter() || c == '_' || c == '@' || c == '$') {
                var k = i + 1
                while (k < n && (code[k].isLetterOrDigit() || code[k] == '_')) k++
                val mot = code.substring(if (c == '@' || c == '$') i + 1 else i, k)
                if (f.motsCles.isNotEmpty() && (if (f.casse) mot in f.motsCles else mot.lowercase() in f.motsCles)) {
                    out.add(Jeton(i, k, Genre.MotCle))
                }
                i = k
                continue
            }
            i++
        }
        return out
    }

    /** Fin (exclue) d'une chaîne ouverte à `i` : délimiteur non échappé, ou fin de ligne (sauf `). */
    private fun finChaine(code: String, i: Int, d: Char): Int {
        var k = i + 1
        while (k < code.length) {
            val c = code[k]
            if (c == '\\') { k += 2; continue }
            if (c == d) return k + 1
            if (c == '\n' && d != '`') return k
            k++
        }
        return code.length
    }

    private fun parLigne(code: String, genre: (String) -> Genre?): List<Jeton> {
        val out = ArrayList<Jeton>()
        var debut = 0
        while (debut <= code.length) {
            val fin = code.indexOf('\n', debut).let { if (it < 0) code.length else it }
            genre(code.substring(debut, fin))?.let { out.add(Jeton(debut, fin, it)) }
            if (fin >= code.length) break
            debut = fin + 1
        }
        return out
    }

    private fun diff(code: String) = parLigne(code) { l ->
        when {
            l.startsWith("+++") || l.startsWith("---") || l.startsWith("@@") -> Genre.Titre
            l.startsWith("+") -> Genre.Ajout
            l.startsWith("-") -> Genre.Retrait
            else -> null
        }
    }

    private fun titresMarkdown(code: String) = parLigne(code) { l -> if (l.startsWith("#")) Genre.Titre else null }
}
