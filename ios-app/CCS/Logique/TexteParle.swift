import Foundation

/**
 * Texte d'une réponse de Claude prêt à être lu à voix haute : le markdown grossier est retiré
 * (blocs de code → « bloc de code », titres, gras, italique, liens → leur texte, citations,
 * puces, tableaux, filets). Fonction pure, testée dans `TexteParleTests`.
 */
enum TexteParle {
    static let blocCode = "bloc de code"

    static func nettoyer(_ md: String) -> String {
        var lignes: [String] = []
        var dansCode = false
        var cloture = ""
        for brute in md.components(separatedBy: "\n") {
            let ligne = brute.trimmingCharacters(in: .whitespaces)
            if dansCode {
                if ligne.hasPrefix(cloture) { dansCode = false }
                continue
            }
            if ligne.hasPrefix("```") || ligne.hasPrefix("~~~") {
                dansCode = true
                cloture = String(ligne.prefix(3))
                lignes.append(blocCode + ".")
                continue
            }
            if let l = ligneNette(ligne) { lignes.append(l) }
        }
        // au plus une ligne vide entre deux paragraphes
        let texte = remplacer(lignes.joined(separator: "\n"), "\\n{3,}", "\n\n")
        return texte.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Une ligne hors bloc de code ; nil : ligne à sauter (filet, séparateur de tableau).
    private static func ligneNette(_ ligne: String) -> String? {
        if ligne.isEmpty { return "" }
        if ligne.range(of: "^([-*_])(\\s*\\1){2,}$", options: .regularExpression) != nil { return nil }
        if ligne.range(of: "^\\|?\\s*:?-{3,}:?\\s*(\\|\\s*:?-{3,}:?\\s*)*\\|?$", options: .regularExpression) != nil { return nil }
        var l = ligne
        var titre = false
        if l.range(of: "^#{1,6}\\s+", options: .regularExpression) != nil {
            l = remplacer(l, "^#{1,6}\\s+", "")
            l = remplacer(l, "\\s+#+$", "")
            titre = true
        }
        l = remplacer(l, "^(>\\s?)+", "")
        l = remplacer(l, "^[-*+]\\s+", "")
        l = remplacer(l, "^\\[[ xX]\\]\\s+", "")
        if l.hasPrefix("|") {
            var c = l.dropFirst()
            if c.hasSuffix("|") { c = c.dropLast() }
            l = c.split(separator: "|", omittingEmptySubsequences: false)
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
                .joined(separator: ", ")
        }
        l = enLigne(l)
        if titre, let d = l.last, !".!?:;…".contains(d) { l += "." }
        return l
    }

    /// Mise en forme dans la ligne ; le code entre accents graves est gardé tel quel (sans les accents).
    private static func enLigne(_ l: String) -> String {
        let morceaux = l.components(separatedBy: "`")
        var sortie = ""
        for (i, m) in morceaux.enumerated() {
            if i % 2 == 1 && i < morceaux.count - 1 {
                sortie += m
                continue
            }
            if i % 2 == 1 { sortie += "`" }           // accent grave sans pendant : laissé
            var t = m
            t = remplacer(t, "!\\[([^\\]]*)\\]\\([^)]*\\)", "$1")
            t = remplacer(t, "\\[([^\\]]+)\\]\\([^)]*\\)", "$1")
            t = remplacer(t, "\\*\\*|__|~~", "")
            t = t.replacingOccurrences(of: "*", with: "")
            t = remplacer(t, "(?<![\\p{L}\\p{N}])_([^_]+)_(?![\\p{L}\\p{N}])", "$1")
            sortie += t
        }
        return sortie
    }

    /// Saisie après une dictée : le texte dicté s'ajoute à ce qui était déjà écrit, séparé d'une espace.
    static func joindre(_ saisie: String, _ dicte: String) -> String {
        let d = dicte.trimmingCharacters(in: .whitespacesAndNewlines)
        if d.isEmpty { return saisie }
        guard let fin = saisie.last else { return d }
        return fin.isWhitespace ? saisie + d : saisie + " " + d
    }

    private static func remplacer(_ s: String, _ motif: String, _ par: String) -> String {
        return s.replacingOccurrences(of: motif, with: par, options: .regularExpression)
    }
}
