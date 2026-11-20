import Foundation

/**
 * Chemins cités dans une réponse de Claude (`chemin` ou `chemin:ligne`) qui sont des fichiers du
 * projet (`work.files`, `web/chat-links.js`) : ils deviennent des liens qui ouvrent le fichier.
 * Port de `logique/LiensFichiers.kt`.
 */
struct LiensFichiers: Equatable {
    let cwd: String
    let fichiers: Set<String>

    struct Ref: Equatable {
        var chemin: String
        var ligne: Int?
        /// Texte cité et sa place dans le texte libre (`trouver`).
        var texte = ""
        var debut = 0
    }

    private static let ref = try! NSRegularExpression(pattern: "^(/?[\\w@+.-]+(?:/[\\w@+.-]+)*)(?::(\\d+)(?::\\d+)?)?$")
    private static let dansTexte = try! NSRegularExpression(
        pattern: "(^|[^\\w/.@+-])(\\.?/?[\\w@+.-]+(?:/[\\w@+.-]+)*\\.[A-Za-z0-9]+)(?::(\\d+)(?::\\d+)?)?")

    private var racine: String {
        var c = cwd
        while c.hasSuffix("/") { c.removeLast() }
        return c
    }

    /// Chemin relatif au projet + ligne si `texte` désigne un fichier connu.
    func ref(_ texte: String) -> Ref? {
        let t = texte.trimmingCharacters(in: .whitespaces) as NSString
        guard let m = LiensFichiers.ref.firstMatch(in: t as String, range: NSRange(location: 0, length: t.length)) else { return nil }
        var chemin = t.substring(with: m.range(at: 1))
        if chemin.hasPrefix("/") {
            guard chemin.hasPrefix(racine + "/") else { return nil }
            chemin = String(chemin.dropFirst(racine.count + 1))
        } else if chemin.hasPrefix("./") {
            chemin = String(chemin.dropFirst(2))
        }
        if chemin.split(separator: "/").contains("..") || !fichiers.contains(chemin) { return nil }
        let l = m.range(at: 2)
        return Ref(chemin: chemin, ligne: l.location == NSNotFound ? nil : Int(t.substring(with: l)))
    }

    /// Références trouvées dans un texte libre ; `debut` et `texte` en unités UTF-16 (NSString).
    func trouver(_ texte: String) -> [Ref] {
        if fichiers.isEmpty { return [] }
        let n = texte as NSString
        var out: [Ref] = []
        for m in LiensFichiers.dansTexte.matches(in: texte, range: NSRange(location: 0, length: n.length)) {
            let avant = m.range(at: 1).length
            let plage = NSRange(location: m.range.location + avant, length: m.range.length - avant)
            let t = n.substring(with: plage)
            guard var r = ref(t) else { continue }
            r.texte = t
            r.debut = plage.location
            out.append(r)
        }
        return out
    }

    func absolu(_ r: Ref) -> String { return Fichiers.joindre(cwd, r.chemin) }

    // MARK: liens touchables (`openURL` de l'écran du chat)

    static let schema = "ccs-fichier"

    /// Lien interne vers un fichier (ouvert par l'écran du chat, jamais par Safari).
    func lien(_ r: Ref) -> URL? {
        var c = URLComponents()
        c.scheme = LiensFichiers.schema
        c.host = "ouvrir"
        var q = [URLQueryItem(name: "chemin", value: absolu(r))]
        if let l = r.ligne { q.append(URLQueryItem(name: "ligne", value: String(l))) }
        c.queryItems = q
        return c.url
    }

    /// Chemin absolu et ligne d'un lien fait par `lien`.
    static func lire(_ u: URL) -> (chemin: String, ligne: Int?)? {
        guard u.scheme == schema, let c = URLComponents(url: u, resolvingAgainstBaseURL: false),
              let chemin = c.queryItems?.first(where: { $0.name == "chemin" })?.value, !chemin.isEmpty else { return nil }
        let ligne = c.queryItems?.first(where: { $0.name == "ligne" })?.value.flatMap { Int($0) }
        return (chemin, ligne)
    }
}
