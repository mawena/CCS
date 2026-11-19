import Foundation

/// Modifications de Claude (Edit, MultiEdit, Write) en diff par lignes (`web/chat-diff.js`).
enum Diff {
    enum Genre: Equatable { case ajout, retrait, contexte, morceau }

    /// `ancien`, `nouveau` : numéros de ligne (diffs de git), absents pour les outils de Claude.
    struct Ligne: Equatable {
        let genre: Genre
        let texte: String
        var ancien: Int? = nil
        var nouveau: Int? = nil
    }

    /// Diff d'un outil de modification : fichier et lignes.
    struct Fichier: Equatable {
        let chemin: String
        let lignes: [Ligne]
        var ajouts: Int { return lignes.filter { $0.genre == .ajout }.count }
        var retraits: Int { return lignes.filter { $0.genre == .retrait }.count }
    }

    private static let lcsMax = 90_000      // au-delà (lignes × lignes) : tout retiré puis tout ajouté

    private static func lignes(_ t: String?) -> [String] {
        guard let t = t, !t.isEmpty else { return [] }
        var l = t.components(separatedBy: "\n")
        if l.last == "" { l.removeLast() }
        return l
    }

    /// Lignes communes au début et à la fin en contexte ; le milieu par plus longue sous-suite commune.
    static func parLignes(_ avant: String?, _ apres: String?) -> [Ligne] {
        let a = lignes(avant)
        let b = lignes(apres)
        var tete = 0
        while tete < a.count && tete < b.count && a[tete] == b[tete] { tete += 1 }
        var queue = 0
        while queue < a.count - tete && queue < b.count - tete && a[a.count - 1 - queue] == b[b.count - 1 - queue] { queue += 1 }
        let ma = Array(a[tete..<(a.count - queue)])
        let mb = Array(b[tete..<(b.count - queue)])
        var out: [Ligne] = []
        for l in a[0..<tete] { out.append(Ligne(genre: .contexte, texte: l)) }
        if ma.count * mb.count > lcsMax {
            for l in ma { out.append(Ligne(genre: .retrait, texte: l)) }
            for l in mb { out.append(Ligne(genre: .ajout, texte: l)) }
        } else {
            let n = ma.count
            let m = mb.count
            let largeur = m + 1
            var dp = [Int](repeating: 0, count: (n + 1) * (m + 1))
            if n > 0 && m > 0 {
                for i in stride(from: n - 1, through: 0, by: -1) {
                    for j in stride(from: m - 1, through: 0, by: -1) {
                        dp[i * largeur + j] = ma[i] == mb[j]
                            ? dp[(i + 1) * largeur + j + 1] + 1
                            : max(dp[(i + 1) * largeur + j], dp[i * largeur + j + 1])
                    }
                }
            }
            var i = 0
            var j = 0
            while i < n && j < m {
                if ma[i] == mb[j] {
                    out.append(Ligne(genre: .contexte, texte: ma[i]))
                    i += 1
                    j += 1
                } else if dp[(i + 1) * largeur + j] >= dp[i * largeur + j + 1] {
                    out.append(Ligne(genre: .retrait, texte: ma[i]))
                    i += 1
                } else {
                    out.append(Ligne(genre: .ajout, texte: mb[j]))
                    j += 1
                }
            }
            while i < n { out.append(Ligne(genre: .retrait, texte: ma[i])); i += 1 }
            while j < m { out.append(Ligne(genre: .ajout, texte: mb[j])); j += 1 }
        }
        for l in a[(a.count - queue)...] { out.append(Ligne(genre: .contexte, texte: l)) }
        return out
    }

    /// Diff d'un outil qui modifie un fichier ; nil pour les autres outils.
    static func deOutil(_ nom: String, _ entree: JSON?) -> Fichier? {
        guard let e = entree else { return nil }
        let chemin = e.texte("file_path")
        if chemin.isEmpty { return nil }
        switch nom {
        case "Edit":
            return Fichier(chemin: chemin, lignes: parLignes(e.texteOuNul("old_string"), e.texteOuNul("new_string")))
        case "MultiEdit":
            guard let edits = e["edits"]?.tableau else { return nil }
            var tout: [Ligne] = []
            for (k, x) in edits.enumerated() {
                if k > 0 { tout.append(Ligne(genre: .morceau, texte: "modification \(k + 1)")) }
                tout.append(contentsOf: parLignes(x.texteOuNul("old_string"), x.texteOuNul("new_string")))
            }
            return Fichier(chemin: chemin, lignes: tout)
        case "Write":
            return Fichier(chemin: chemin, lignes: parLignes("", e.texteOuNul("content")))
        default:
            return nil
        }
    }
}
