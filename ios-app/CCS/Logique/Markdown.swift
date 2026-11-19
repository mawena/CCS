import Foundation

/// Expression régulière simple (NSRegularExpression) : correspondance entière et groupes.
struct Motif {
    let rx: NSRegularExpression

    init(_ motif: String) {
        // motifs écrits à la main dans ce fichier : une erreur ici est une faute de frappe
        rx = try! NSRegularExpression(pattern: motif, options: [])
    }

    /// Groupes (0 = tout) si `s` correspond en entier ; groupe absent : « ».
    func entier(_ s: String) -> [String]? {
        let ns = s as NSString
        guard let m = rx.firstMatch(in: s, options: [.anchored], range: NSRange(location: 0, length: ns.length)),
              m.range.location == 0, m.range.length == ns.length else { return nil }
        var g: [String] = []
        for i in 0..<m.numberOfRanges {
            let r = m.range(at: i)
            g.append(r.location == NSNotFound ? "" : ns.substring(with: r))
        }
        return g
    }

    func correspond(_ s: String) -> Bool { return entier(s) != nil }
}

/**
 * Markdown des réponses de Claude, lu en blocs (titres, paragraphes, listes, code, citations,
 * tableaux, règles) et en segments de texte stylés (gras, italique, code, barré, liens). L'écran
 * construit ses textes à partir de ce résultat. Tolérant : un texte en cours d'arrivée (bloc de
 * code pas encore fermé, `**` sans fin) se lit sans erreur.
 */
enum Markdown {
    indirect enum Bloc: Equatable {
        case titre(niveau: Int, contenu: [Segment])
        case paragraphe([Segment])
        case liste([Element])
        case code(langue: String, texte: String)
        case citation([Bloc])
        case tableau(entetes: [[Segment]], lignes: [[[Segment]]])
        case regle
    }

    /// Élément d'une liste : niveau d'imbrication (0, 1…), marque (« • », « 3. »), case à cocher.
    struct Element: Equatable {
        var niveau: Int
        var marque: String
        var contenu: [Segment]
        var coche: Bool? = nil
    }

    struct Segment: Equatable {
        var texte: String
        var gras = false
        var italique = false
        var code = false
        var barre = false
        var lien: String? = nil

        func memeStyle(_ o: Segment) -> Bool {
            return gras == o.gras && italique == o.italique && code == o.code && barre == o.barre && lien == o.lien
        }
    }

    private static let fence = Motif(#"^ {0,3}(`{3,}|~{3,})\s*([^`\s]*)?.*$"#)
    private static let titre = Motif(#"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$"#)
    private static let regle = Motif(#"^ {0,3}([-*_])(\s*\1){2,}\s*$"#)
    private static let puce = Motif(#"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$"#)
    private static let sepTableau = Motif(#"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$"#)
    private static let coche = Motif(#"^\[([ xX])\]\s+(.*)$"#)

    static func analyser(_ md: String) -> [Bloc] {
        return blocs(md.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n"))
    }

    private static func vide(_ l: String) -> Bool { return l.allSatisfy { $0.isWhitespace } }

    private static func sansDebut(_ l: String) -> String { return String(l.drop(while: { $0.isWhitespace })) }

    private static func sansFin(_ l: String) -> String {
        var s = Substring(l)
        while let d = s.last, d.isWhitespace { s = s.dropLast() }
        return String(s)
    }

    private static func estDebutBloc(_ l: String) -> Bool {
        return fence.correspond(l) || titre.correspond(l) || regle.correspond(l) || sansDebut(l).hasPrefix(">") || puce.correspond(l)
    }

    private static func blocs(_ lignes: [String]) -> [Bloc] {
        var out: [Bloc] = []
        var i = 0
        while i < lignes.count {
            let l = lignes[i]
            if vide(l) {
                i += 1
                continue
            }
            if let f = fence.entier(l) {
                let marque = f[1]
                let langue = f[2]
                let premiere = marque.first ?? "`"
                var code: [String] = []
                i += 1
                while i < lignes.count {
                    let t = sansDebut(lignes[i])
                    let te = sansFin(t)
                    if t.hasPrefix(String(marque.prefix(3))) && te.allSatisfy({ $0 == premiere }) && te.count >= marque.count {
                        i += 1
                        break
                    }
                    code.append(lignes[i])
                    i += 1
                }
                out.append(.code(langue: langue.lowercased(), texte: code.joined(separator: "\n")))
                continue
            }
            if let t = titre.entier(l) {
                out.append(.titre(niveau: t[1].count, contenu: enLigne(t[2])))
                i += 1
                continue
            }
            if regle.correspond(l) {
                out.append(.regle)
                i += 1
                continue
            }
            if sansDebut(l).hasPrefix(">") {
                var dedans: [String] = []
                while i < lignes.count && sansDebut(lignes[i]).hasPrefix(">") {
                    var t = String(sansDebut(lignes[i]).dropFirst())
                    if t.hasPrefix(" ") { t.removeFirst() }
                    dedans.append(t)
                    i += 1
                }
                out.append(.citation(blocs(dedans)))
                continue
            }
            if puce.correspond(l) {
                let (elements, suite) = liste(lignes, i)
                out.append(.liste(elements))
                i = suite
                continue
            }
            if l.contains("|") && i + 1 < lignes.count && sepTableau.correspond(lignes[i + 1]) && lignes[i + 1].contains("-") {
                let entetes = cellules(l)
                i += 2
                var rangs: [[[Segment]]] = []
                while i < lignes.count && lignes[i].contains("|") && !vide(lignes[i]) {
                    rangs.append(cellules(lignes[i]))
                    i += 1
                }
                out.append(.tableau(entetes: entetes, lignes: rangs))
                continue
            }
            // paragraphe : lignes jusqu'à une ligne vide ou un autre bloc
            var texte = ""
            while i < lignes.count && !vide(lignes[i]) && (texte.isEmpty || !estDebutBloc(lignes[i])) {
                let brut = lignes[i]
                let dure = brut.hasSuffix("  ") || brut.hasSuffix("\\")
                var t = brut.trimmingCharacters(in: .whitespaces)
                if t.hasSuffix("\\") { t.removeLast() }
                if !texte.isEmpty && !texte.hasSuffix("\n") { texte += " " }
                texte += t
                if dure { texte += "\n" }
                i += 1
            }
            while texte.hasSuffix("\n") { texte.removeLast() }
            out.append(.paragraphe(enLigne(texte)))
        }
        return out
    }

    private static func liste(_ lignes: [String], _ debut: Int) -> ([Element], Int) {
        var elements: [Element] = []
        var retraits: [Int] = []        // retrait de chaque niveau ouvert
        var i = debut
        var courant: String? = nil
        var marque = ""
        var niveau = 0

        func fermer() {
            guard let c = courant else { return }
            if let m = coche.entier(c) {
                elements.append(Element(niveau: niveau, marque: marque, contenu: enLigne(m[2]), coche: m[1] != " "))
            } else {
                elements.append(Element(niveau: niveau, marque: marque, contenu: enLigne(c)))
            }
            courant = nil
        }

        while i < lignes.count {
            let l = lignes[i]
            if let p = puce.entier(l) {
                fermer()
                let retrait = p[1].replacingOccurrences(of: "\t", with: "    ").count
                while let d = retraits.last, d > retrait { retraits.removeLast() }
                if retraits.last.map({ $0 < retrait }) ?? true { retraits.append(retrait) }
                niveau = retraits.count - 1
                let m = p[2]
                if let c = m.first, c.isNumber {
                    marque = String(m.dropLast()) + "."
                } else {
                    marque = "•"
                }
                courant = p[3].trimmingCharacters(in: .whitespaces)
                i += 1
                continue
            }
            if vide(l) {
                // une ligne vide puis un élément ou une suite en retrait : la liste continue
                if i + 1 < lignes.count {
                    let n = lignes[i + 1]
                    if puce.correspond(n) || (n.hasPrefix("  ") && !vide(n) && !fence.correspond(n)) {
                        i += 1
                        continue
                    }
                }
                break
            }
            if let c = courant, (l.hasPrefix(" ") || l.hasPrefix("\t")) && !fence.correspond(l) {
                courant = c + " " + l.trimmingCharacters(in: .whitespaces)
                i += 1
                continue
            }
            if let c = courant, !estDebutBloc(l) && !l.contains("|") {    // suite paresseuse
                courant = c + " " + l.trimmingCharacters(in: .whitespaces)
                i += 1
                continue
            }
            break
        }
        fermer()
        return (elements, i)
    }

    private static func cellules(_ l: String) -> [[Segment]] {
        var t = l.trimmingCharacters(in: .whitespaces)
        if t.hasPrefix("|") { t.removeFirst() }
        if t.hasSuffix("|") && !t.hasSuffix("\\|") { t.removeLast() }
        let cs = Array(t)
        var out: [String] = []
        var c = ""
        var code = false
        var k = 0
        while k < cs.count {
            let ch = cs[k]
            if ch == "\\" && k + 1 < cs.count && cs[k + 1] == "|" {
                c.append("|")
                k += 1
            } else if ch == "`" {
                code.toggle()
                c.append(ch)
            } else if ch == "|" && !code {
                out.append(c)
                c = ""
            } else {
                c.append(ch)
            }
            k += 1
        }
        out.append(c)
        return out.map { enLigne($0.trimmingCharacters(in: .whitespaces)) }
    }

    // MARK: en ligne

    static func enLigne(_ t: String) -> [Segment] {
        let a = AnalyseEnLigne()
        a.parcourir(Array(t), Style())
        // segments voisins de même style réunis
        var fusion: [Segment] = []
        for s in a.out {
            if let d = fusion.last, d.memeStyle(s) {
                fusion[fusion.count - 1].texte += s.texte
            } else {
                fusion.append(s)
            }
        }
        return fusion
    }

    /// Ponctuation finale qui n'appartient pas au lien (« voir https://x.fr. »), parenthèses équilibrées.
    static func rognerUrl(_ u: String) -> String {
        var url = u
        while let d = url.last {
            let ouvrantes = url.filter { $0 == "(" }.count
            let fermantes = url.filter { $0 == ")" }.count
            if ".,;:!?'\"*_".contains(d) || (d == ")" && ouvrantes < fermantes) {
                url.removeLast()
            } else {
                break
            }
        }
        return url
    }

    /// Texte brut d'un bloc (recherche, copie).
    static func texte(_ segments: [Segment]) -> String {
        return segments.map { $0.texte }.joined()
    }

    struct Style: Equatable {
        var gras = false
        var italique = false
        var barre = false
        var lien: String? = nil
    }
}

/// Analyse en ligne : parcourt les caractères et ajoute les segments à `out` (récursif pour l'imbrication).
private final class AnalyseEnLigne {
    typealias Segment = Markdown.Segment
    typealias Style = Markdown.Style

    var out: [Segment] = []
    private static let ponctuation: Set<Character> = Set("\\`*_{}[]()#+-.!|~<>\"'")

    private static func lettreOuChiffre(_ c: Character) -> Bool { return c.isLetter || c.isNumber }

    private static func commencePar(_ s: [Character], _ m: String, _ i: Int) -> Bool {
        let mc = Array(m)
        if i + mc.count > s.count { return false }
        for k in 0..<mc.count where s[i + k] != mc[k] { return false }
        return true
    }

    /// Position de `m` dans `s` à partir de `depuis`, ou -1.
    private static func chercher(_ s: [Character], _ m: [Character], _ depuis: Int) -> Int {
        if m.isEmpty || depuis < 0 { return -1 }
        var i = depuis
        while i + m.count <= s.count {
            var ok = true
            for k in 0..<m.count where s[i + k] != m[k] {
                ok = false
                break
            }
            if ok { return i }
            i += 1
        }
        return -1
    }

    private static func motAvant(_ s: [Character], _ i: Int) -> Bool {
        return i > 0 && lettreOuChiffre(s[i - 1])
    }

    func parcourir(_ s: [Character], _ st: Style) {
        var buf = ""

        func vider() {
            if !buf.isEmpty {
                out.append(Segment(texte: buf, gras: st.gras, italique: st.italique, code: false, barre: st.barre, lien: st.lien))
            }
            buf = ""
        }

        /// Texte entouré par `d` à partir de `i` : analysé avec le style `nouveau` ; rend la position suivante.
        func entoure(_ i: Int, _ d: String, _ nouveau: Style) -> Int? {
            let dc = Array(d)
            let debut = i + dc.count
            if debut >= s.count || s[debut].isWhitespace { return nil }
            var f = AnalyseEnLigne.chercher(s, dc, debut + 1)
            while f >= 0 {
                let seul = dc.count > 1 || ((f + 1 >= s.count || s[f + 1] != dc[0]) && s[f - 1] != dc[0])
                if !s[f - 1].isWhitespace && seul { break }
                f = AnalyseEnLigne.chercher(s, dc, f + 1)
            }
            if f < 0 { return nil }
            if dc[0] == "_" && f + dc.count < s.count && AnalyseEnLigne.lettreOuChiffre(s[f + dc.count]) { return nil }
            vider()
            parcourir(Array(s[debut..<f]), nouveau)
            return f + dc.count
        }

        var i = 0
        while i < s.count {
            let c = s[i]
            if c == "\\" && i + 1 < s.count && AnalyseEnLigne.ponctuation.contains(s[i + 1]) {
                buf.append(s[i + 1])
                i += 2
                continue
            }
            if c == "`" {
                var n = 0
                while i + n < s.count && s[i + n] == "`" { n += 1 }
                let marque = [Character](repeating: "`", count: n)
                var f = AnalyseEnLigne.chercher(s, marque, i + n)
                while f >= 0 && f + n < s.count && s[f + n] == "`" { f = AnalyseEnLigne.chercher(s, marque, f + n + 1) }
                if f < 0 {
                    buf += String(marque)
                    i += n
                    continue
                }
                vider()
                var code = String(s[(i + n)..<f])
                if code.count >= 2 && code.hasPrefix(" ") && code.hasSuffix(" ") && !code.allSatisfy({ $0.isWhitespace }) {
                    code = String(code.dropFirst().dropLast())
                }
                out.append(Segment(texte: code, gras: st.gras, italique: st.italique, code: true, barre: st.barre, lien: st.lien))
                i = f + n
                continue
            }
            if AnalyseEnLigne.commencePar(s, "***", i) || AnalyseEnLigne.commencePar(s, "___", i) {
                var n = st
                n.gras = true
                n.italique = true
                if let f = entoure(i, String(s[i..<(i + 3)]), n) {
                    i = f
                    continue
                }
            }
            if AnalyseEnLigne.commencePar(s, "**", i) || (AnalyseEnLigne.commencePar(s, "__", i) && !AnalyseEnLigne.motAvant(s, i)) {
                var n = st
                n.gras = true
                if let f = entoure(i, String(s[i..<(i + 2)]), n) {
                    i = f
                    continue
                }
            }
            if AnalyseEnLigne.commencePar(s, "~~", i) {
                var n = st
                n.barre = true
                if let f = entoure(i, "~~", n) {
                    i = f
                    continue
                }
            }
            if c == "*" || (c == "_" && !AnalyseEnLigne.motAvant(s, i)) {
                var n = st
                n.italique = true
                if let f = entoure(i, String(c), n) {
                    i = f
                    continue
                }
            }
            if (c == "!" && i + 1 < s.count && s[i + 1] == "[") || (c == "[" && st.lien == nil) {
                if let l = lien(s, c == "!" ? i + 1 : i) {
                    vider()
                    var n = st
                    n.lien = l.url
                    parcourir(Array(l.texte.isEmpty ? l.url : l.texte), n)
                    i = l.fin
                    continue
                }
            }
            if c == "<" && st.lien == nil, let a = auto(s, i) {
                vider()
                out.append(Segment(texte: a.url, gras: st.gras, italique: st.italique, code: false, barre: st.barre, lien: a.url))
                i = a.fin
                continue
            }
            if c == "h" && st.lien == nil && !AnalyseEnLigne.motAvant(s, i), let brut = url(s, i) {
                let u = Markdown.rognerUrl(brut)
                vider()
                out.append(Segment(texte: u, gras: st.gras, italique: st.italique, code: false, barre: st.barre, lien: u))
                i += u.count
                continue
            }
            buf.append(c)
            i += 1
        }
        vider()
    }

    /// `https://…` qui commence à `i` (jusqu'à un blanc, `<`, `>` ou `"`), ou nil.
    private func url(_ s: [Character], _ i: Int) -> String? {
        let debut: Int
        if AnalyseEnLigne.commencePar(s, "https://", i) {
            debut = i + 8
        } else if AnalyseEnLigne.commencePar(s, "http://", i) {
            debut = i + 7
        } else {
            return nil
        }
        var f = debut
        while f < s.count && !s[f].isWhitespace && s[f] != "<" && s[f] != ">" && s[f] != "\"" { f += 1 }
        if f == debut { return nil }
        return String(s[i..<f])
    }

    /// `<https://…>` qui commence à `i`, ou nil.
    private func auto(_ s: [Character], _ i: Int) -> (url: String, fin: Int)? {
        guard let u = url(s, i + 1) else { return nil }
        let f = i + 1 + u.count
        guard f < s.count, s[f] == ">" else { return nil }
        return (url: u, fin: f + 1)
    }

    /// `[texte](url)` qui commence à `i` : texte, adresse et fin ; nil sinon.
    private func lien(_ s: [Character], _ i: Int) -> (texte: String, url: String, fin: Int)? {
        var prof = 0
        var k = i
        boucle: while k < s.count {
            switch s[k] {
            case "[":
                prof += 1
            case "]":
                prof -= 1
                if prof == 0 { break boucle }
            case "\\":
                k += 1
            default:
                break
            }
            k += 1
        }
        if k >= s.count || k + 1 >= s.count || s[k + 1] != "(" { return nil }
        var f = k + 2
        var p = 1
        while f < s.count {
            if s[f] == "(" { p += 1 }
            if s[f] == ")" {
                p -= 1
                if p == 0 { break }
            }
            f += 1
        }
        if f >= s.count { return nil }
        let dedans = String(s[(k + 2)..<f]).trimmingCharacters(in: .whitespaces)
        var adresse = dedans.split(whereSeparator: { $0.isWhitespace }).first.map(String.init) ?? ""
        if adresse.hasPrefix("<") { adresse.removeFirst() }
        if adresse.hasSuffix(">") { adresse.removeLast() }
        if adresse.isEmpty { return nil }
        return (texte: String(s[(i + 1)..<k]), url: adresse, fin: f + 1)
    }
}
