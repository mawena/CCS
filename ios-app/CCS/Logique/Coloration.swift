import Foundation

/**
 * Coloration simple du code (fichiers ouverts) : mots-clés, chaînes, commentaires, nombres (et
 * lignes ajoutées / retirées d'un diff, titres Markdown). Un seul passage, sans expression
 * régulière par jeton. Langue inconnue : chaînes et nombres. Positions en caractères.
 */
enum Coloration {
    enum Genre: Equatable { case motCle, chaine, commentaire, nombre, ajout, retrait, titre }

    struct Jeton: Equatable {
        let debut: Int
        let fin: Int
        let genre: Genre
    }

    private struct Famille {
        var ligne: [String] = []                        // débuts de commentaire jusqu'à la fin de la ligne
        var bloc: [(String, String)] = []               // commentaires en bloc
        var chaines: String = "\""                      // délimiteurs de chaîne
        var motsCles: Set<String> = []
        var casse = true
        var triples = false                             // """ et ''' (Python, Kotlin)
    }

    private static func mots(_ t: String) -> Set<String> { return Set(t.split(separator: " ").map(String.init)) }

    private static let cLike = mots(
        "if else for while do switch case default break continue return goto struct union enum typedef " +
            "static const volatile extern sizeof void int char long short float double unsigned signed bool true false " +
            "null nullptr class public private protected virtual template typename namespace using new delete this " +
            "auto inline include define ifdef ifndef endif"
    )
    private static let js = mots(
        "if else for while do switch case default break continue return function var let const class extends " +
            "new this super import export from as async await yield try catch finally throw typeof instanceof in of " +
            "true false null undefined void delete static get set interface type enum implements public private " +
            "protected readonly declare namespace keyof any unknown never string number boolean"
    )
    private static let kotlinJava = mots(
        "if else for while do when switch case default break continue return fun val var class object interface " +
            "data sealed enum abstract open override private public protected internal companion init constructor " +
            "this super null true false is as in out import package try catch finally throw new static final void " +
            "int long boolean char byte short double float extends implements lateinit suspend inline typealias by"
    )
    private static let swift = mots(
        "if else for while repeat switch case default break continue return func var let class struct enum protocol " +
            "extension import guard defer do try catch throw throws rethrows async await in where is as self Self super " +
            "init deinit nil true false static private fileprivate public internal open final override mutating " +
            "inout some any typealias associatedtype weak unowned lazy"
    )
    private static let python = mots(
        "if elif else for while break continue return def class import from as try except finally raise with " +
            "lambda yield pass global nonlocal assert del in is not and or None True False async await self match case"
    )
    private static let shell = mots(
        "if then else elif fi for while until do done case esac in function return local export readonly " +
            "set unset shift exit echo cd source alias sudo"
    )
    private static let go = mots(
        "break case chan const continue default defer else fallthrough for func go goto if import interface map " +
            "package range return select struct switch type var true false nil"
    )
    private static let rust = mots(
        "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod " +
            "move mut pub ref return self Self static struct super trait true type unsafe use where while Some None Ok Err"
    )
    private static let sql = mots(
        "select from where insert into values update set delete create table drop alter add index primary key " +
            "foreign references join left right inner outer on group by order having limit offset as and or not null " +
            "is in exists distinct union all case when then else end begin commit rollback default unique"
    )

    private static let familles: [String: Famille] = {
        var m: [String: Famille] = [:]
        let slash = ["//"]
        let blocC = [("/*", "*/")]
        let c = Famille(ligne: slash, bloc: blocC, chaines: "\"'", motsCles: cLike)
        let j = Famille(ligne: slash, bloc: blocC, chaines: "\"'`", motsCles: js)
        let kt = Famille(ligne: slash, bloc: blocC, chaines: "\"'", motsCles: kotlinJava, triples: true)
        let sw = Famille(ligne: slash, bloc: blocC, chaines: "\"", motsCles: swift, triples: true)
        let py = Famille(ligne: ["#"], bloc: [], chaines: "\"'", motsCles: python, triples: true)
        let sh = Famille(ligne: ["#"], bloc: [], chaines: "\"'", motsCles: shell)
        for n in ["c", "h", "cpp", "c++", "cc", "hpp", "cs", "csharp", "objc", "dart", "scala"] { m[n] = c }
        for n in ["swift"] { m[n] = sw }
        for n in ["js", "javascript", "jsx", "ts", "typescript", "tsx", "mjs", "cjs", "json5", "vue", "svelte"] { m[n] = j }
        for n in ["kotlin", "kt", "kts", "java", "groovy", "gradle"] { m[n] = kt }
        for n in ["python", "py", "python3"] { m[n] = py }
        for n in ["sh", "bash", "shell", "zsh", "console", "shellsession", "fish", "dockerfile", "docker", "makefile", "make"] { m[n] = sh }
        m["go"] = Famille(ligne: slash, bloc: blocC, chaines: "\"'`", motsCles: go)
        m["rust"] = Famille(ligne: slash, bloc: blocC, chaines: "\"", motsCles: rust)
        m["rs"] = m["rust"]
        m["sql"] = Famille(ligne: ["--"], bloc: blocC, chaines: "'\"", motsCles: sql, casse: false)
        m["lua"] = Famille(ligne: ["--"], bloc: [], chaines: "\"'", motsCles: mots("and break do else elseif end false for function if in local nil not or repeat return then true until while"))
        m["php"] = Famille(ligne: ["//", "#"], bloc: blocC, chaines: "\"'", motsCles: js.union(mots("echo elseif endif foreach endforeach require require_once include_once namespace use fn match")))
        for n in ["yaml", "yml", "toml", "ini", "conf", "nginx", "properties", "env"] {
            m[n] = Famille(ligne: ["#"], bloc: [], chaines: "\"'", motsCles: mots("true false null yes no on off"))
        }
        m["json"] = Famille(ligne: [], bloc: [], chaines: "\"", motsCles: mots("true false null"))
        for n in ["css", "scss", "sass", "less"] { m[n] = Famille(ligne: slash, bloc: blocC, chaines: "\"'", motsCles: mots("important media import keyframes from to")) }
        for n in ["html", "xml", "svg", "htm"] { m[n] = Famille(ligne: [], bloc: [("<!--", "-->")], chaines: "\"'", motsCles: []) }
        return m
    }()

    static let maxCaracteres = 30_000            // au-delà : pas de coloration (bloc énorme)

    /// Vrai si `motif` commence à la position `i` de `t`.
    private static func commence(_ t: [Character], _ motif: [Character], _ i: Int) -> Bool {
        if i + motif.count > t.count { return false }
        for k in 0..<motif.count where t[i + k] != motif[k] { return false }
        return true
    }

    private static func chercher(_ t: [Character], _ motif: [Character], depuis: Int) -> Int? {
        if motif.isEmpty { return depuis }
        var i = depuis
        while i + motif.count <= t.count {
            if commence(t, motif, i) { return i }
            i += 1
        }
        return nil
    }

    private static func finLigne(_ t: [Character], _ i: Int) -> Int {
        var k = i
        while k < t.count && t[k] != "\n" { k += 1 }
        return k
    }

    private static func lettreOuChiffre(_ c: Character) -> Bool { return c.isLetter || c.isNumber }

    static func jetons(_ code: String, _ langue: String) -> [Jeton] {
        return jetons(Array(code), langue)
    }

    static func jetons(_ t: [Character], _ langue: String) -> [Jeton] {
        if t.count > maxCaracteres { return [] }
        let l = langue.lowercased()
        if l == "diff" || l == "patch" { return diff(t) }
        if l == "md" || l == "markdown" { return parLigne(t) { $0.first == "#" ? .titre : nil } }
        let f = familles[l] ?? Famille()
        let lignes = f.ligne.map { Array($0) }
        let blocs = f.bloc.map { (Array($0.0), Array($0.1)) }
        let delims = Set(f.chaines)
        var out: [Jeton] = []
        var i = 0
        let n = t.count
        while i < n {
            let c = t[i]
            // commentaire de ligne (en début de mot : « a#b » en shell n'en est pas un)
            if let lg = lignes.first(where: { commence(t, $0, i) }),
               lg != ["#"] || i == 0 || t[i - 1].isWhitespace {
                let fin = finLigne(t, i)
                out.append(Jeton(debut: i, fin: fin, genre: .commentaire))
                i = fin
                continue
            }
            if let b = blocs.first(where: { commence(t, $0.0, i) }) {
                let fin = chercher(t, b.1, depuis: i + b.0.count).map { $0 + b.1.count } ?? n
                out.append(Jeton(debut: i, fin: fin, genre: .commentaire))
                i = fin
                continue
            }
            if delims.contains(c) {
                let triple: [Character] = [c, c, c]
                let fin: Int
                if f.triples && commence(t, triple, i) {
                    fin = chercher(t, triple, depuis: i + 3).map { $0 + 3 } ?? n
                } else {
                    fin = finChaine(t, i, c)
                }
                out.append(Jeton(debut: i, fin: fin, genre: .chaine))
                i = fin
                continue
            }
            if c.isASCII && c.isNumber && (i == 0 || (!lettreOuChiffre(t[i - 1]) && t[i - 1] != "_")) {
                var k = i + 1
                while k < n && (lettreOuChiffre(t[k]) || t[k] == "." || t[k] == "_") { k += 1 }
                out.append(Jeton(debut: i, fin: k, genre: .nombre))
                i = k
                continue
            }
            if c.isLetter || c == "_" || c == "@" || c == "$" {
                var k = i + 1
                while k < n && (lettreOuChiffre(t[k]) || t[k] == "_") { k += 1 }
                let debutMot = (c == "@" || c == "$") ? i + 1 : i
                let mot = String(t[debutMot..<k])
                if !f.motsCles.isEmpty && (f.casse ? f.motsCles.contains(mot) : f.motsCles.contains(mot.lowercased())) {
                    out.append(Jeton(debut: i, fin: k, genre: .motCle))
                }
                i = k
                continue
            }
            i += 1
        }
        return out
    }

    /// Fin (exclue) d'une chaîne ouverte à `i` : délimiteur non échappé, ou fin de ligne (sauf `).
    private static func finChaine(_ t: [Character], _ i: Int, _ d: Character) -> Int {
        var k = i + 1
        while k < t.count {
            let c = t[k]
            if c == "\\" { k += 2; continue }
            if c == d { return k + 1 }
            if c == "\n" && d != "`" { return k }
            k += 1
        }
        return t.count
    }

    private static func parLigne(_ t: [Character], _ genre: (ArraySlice<Character>) -> Genre?) -> [Jeton] {
        var out: [Jeton] = []
        var debut = 0
        while debut <= t.count {
            let fin = finLigne(t, debut)
            if let g = genre(t[debut..<fin]) { out.append(Jeton(debut: debut, fin: fin, genre: g)) }
            if fin >= t.count { break }
            debut = fin + 1
        }
        return out
    }

    private static func diff(_ t: [Character]) -> [Jeton] {
        return parLigne(t) { l in
            let s = String(l)
            if s.hasPrefix("+++") || s.hasPrefix("---") || s.hasPrefix("@@") { return .titre }
            if s.hasPrefix("+") { return .ajout }
            if s.hasPrefix("-") { return .retrait }
            return nil
        }
    }

    /// Genre de chaque caractère (nil : texte ordinaire), pour découper en lignes colorées.
    static func genres(_ t: [Character], _ langue: String) -> [Genre?] {
        var g = [Genre?](repeating: nil, count: t.count)
        for j in jetons(t, langue) {
            let a = Swift.max(0, j.debut)
            let b = Swift.min(t.count, j.fin)
            if a < b { for k in a..<b { g[k] = j.genre } }
        }
        return g
    }
}
