import Foundation

/**
 * Chat riche (phase 49), partie sans écran : sons et vidéos reconnus à l'extension, adresses
 * d'images et de médias (https, ou chemin local lu par l'API fichiers du pont), blocs ```ccs
 * (JSON) lus en composants : choix, carte, cartes, formulaire. Port de `web/chat-rich.js` ;
 * format dans `docs/chat-riche.md`. Un bloc invalide donne nil : il reste un bloc de code.
 */
enum Riche {
    static let sons: Set<String> = ["mp3", "ogg", "wav", "m4a", "opus"]
    static let videos: Set<String> = ["mp4", "webm", "mov"]
    /// Fichier local lu par l'API fichiers : 60 Mo au plus, comme le web.
    static let maxLocal: Int64 = 60 * 1024 * 1024

    enum Media: Equatable { case son, video }

    /// Adresse https gardée telle quelle, ou chemin absolu sur le PC.
    enum Source: Equatable, Hashable {
        case url(URL)
        case chemin(String)
    }

    // MARK: médias

    /// Son, vidéo ou nil d'après l'extension (avant ?requête et #ancre).
    static func media(_ src: String) -> Media? {
        let s = src.trimmingCharacters(in: .whitespacesAndNewlines)
        let base = s.split(omittingEmptySubsequences: false, whereSeparator: { $0 == "?" || $0 == "#" }).first.map(String.init) ?? ""
        guard let point = base.lastIndex(of: ".") else { return nil }
        let ext = base[base.index(after: point)...].lowercased()
        guard !ext.isEmpty, ext.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber) }) else { return nil }
        if sons.contains(ext) { return .son }
        if videos.contains(ext) { return .video }
        return nil
    }

    private static let schema = try! NSRegularExpression(pattern: "^([a-z][\\w+.-]*:|//)", options: [.caseInsensitive])

    /**
     * Adresse https gardée ; chemin local (absolu, ou relatif au dossier `cwd` de la session)
     * normalisé ; le reste (javascript:, data:, http nu, //hôte…) est refusé.
     */
    static func resoudre(_ src: String, cwd: String) -> Source? {
        let s = src.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.lowercased().hasPrefix("https://") {
            guard let u = URL(string: s) ?? URL(string: s.addingPercentEncoding(withAllowedCharacters: .urlFragmentAllowed) ?? "") else { return nil }
            return .url(u)
        }
        let ns = s as NSString
        if s.isEmpty || schema.firstMatch(in: s, range: NSRange(location: 0, length: ns.length)) != nil { return nil }
        var parts: [String] = []
        for p in (s.hasPrefix("/") ? s : cwd + "/" + s).split(separator: "/", omittingEmptySubsequences: true) {
            if p == "." { continue }
            if p == ".." {
                if !parts.isEmpty { parts.removeLast() }
            } else {
                parts.append(String(p))
            }
        }
        return parts.isEmpty ? nil : .chemin("/" + parts.joined(separator: "/"))
    }

    /// Image ou lecteur trouvé dans un paragraphe, affiché sous son texte.
    struct MediaEnLigne: Equatable, Hashable {
        enum Genre: Equatable, Hashable { case image, son, video }
        var genre: Genre
        var src: String
        var legende: String
    }

    /**
     * Images (`![texte](adresse)`), puis liens, `chemins` en code et chemins de fichiers du
     * projet qui désignent un son ou une vidéo : chacun une fois, dans l'ordre du texte.
     */
    static func medias(_ segments: [Markdown.Segment], liens: LiensFichiers? = nil) -> [MediaEnLigne] {
        var out: [MediaEnLigne] = []
        func ajouter(_ src: String, _ legende: String, image: Bool = false) {
            let genre: MediaEnLigne.Genre
            switch media(src) {
            case .some(.son): genre = .son
            case .some(.video): genre = .video
            case .none:
                guard image else { return }
                genre = .image
            }
            let m = MediaEnLigne(genre: genre, src: src.trimmingCharacters(in: .whitespacesAndNewlines), legende: legende)
            if !out.contains(m) { out.append(m) }
        }
        for s in segments {
            if s.image, let l = s.lien {
                ajouter(l, s.texte, image: true)
            } else if let l = s.lien {
                ajouter(l, s.texte)
            } else if s.code {
                ajouter(s.texte, s.texte)
            } else if let lf = liens {
                for r in lf.trouver(s.texte) { ajouter(lf.absolu(r), r.texte) }
            }
        }
        return out
    }

    // MARK: blocs ccs

    /// Option d'un choix ou action d'une carte : envoie `message`, ou ouvre `lien` (http(s)).
    struct Option: Equatable, Hashable {
        var label: String
        var message: String
        var lien: URL?
    }

    struct Carte: Equatable, Hashable {
        var titre: String
        var image = ""
        var prix = ""
        var sousTitre = ""
        var description = ""
        var lien: URL? = nil
        var actions: [Option] = []
    }

    struct Champ: Equatable, Hashable {
        /// Clé de la valeur : `nom`, à défaut `label`.
        var cle: String
        var label: String
        /// « texte », « nombre » ou « liste ».
        var type: String
        var options: [String] = []
        var valeur: String? = nil
        var aide = ""
    }

    enum Composant: Equatable, Hashable {
        case choix(titre: String, options: [Option])
        case carte(Carte)
        case cartes([Carte])
        case formulaire(titre: String, envoyer: String, champs: [Champ])
    }

    /// Bloc ```ccs : le composant décrit s'il est valide (JSON, type connu, liste non vide), sinon nil.
    static func bloc(_ texte: String) -> Composant? {
        guard let d = texte.data(using: .utf8),
              let o = try? JSONSerialization.jsonObject(with: d, options: [.fragmentsAllowed]),
              let spec = o as? [String: Any], let type = spec["type"] as? String else { return nil }
        switch type {
        case "choix":
            guard let opts = spec["options"] as? [Any], !opts.isEmpty else { return nil }
            let titre = nonVide(chaine(spec["titre"])) ?? chaine(spec["question"])
            return .choix(titre: titre, options: opts.map(option).filter { !$0.label.isEmpty })
        case "carte":
            guard let c = carte(spec) else { return nil }
            return .carte(c)
        case "cartes":
            guard let items = spec["items"] as? [Any], !items.isEmpty else { return nil }
            return .cartes(items.compactMap { ($0 as? [String: Any]).flatMap(carte) })
        case "formulaire":
            guard let champs = spec["champs"] as? [Any], !champs.isEmpty else { return nil }
            return .formulaire(titre: chaine(spec["titre"]), envoyer: nonVide(chaine(spec["envoyer"])) ?? "Envoyer",
                               champs: champs.compactMap { ($0 as? [String: Any]).map(champ) })
        default:
            return nil
        }
    }

    /// Message lisible envoyé par un formulaire : le titre puis « - Libellé : valeur » par champ rempli.
    static func messageFormulaire(titre: String, champs: [Champ], valeurs: [String: String]) -> String {
        var lignes: [String] = titre.isEmpty ? [] : [titre]
        for c in champs {
            let v = (valeurs[c.cle] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if !v.isEmpty { lignes.append("- \(c.label) : \(v)") }
        }
        return lignes.joined(separator: "\n")
    }

    /// Valeur JSON en texte, comme `String(v)` du web (absent ou null : « »).
    static func chaine(_ v: Any?) -> String {
        guard let v = v else { return "" }
        if v is NSNull { return "" }
        if let s = v as? String { return s }
        if let n = v as? NSNumber {
            if CFGetTypeID(n) == CFBooleanGetTypeID() { return n.boolValue ? "true" : "false" }
            return n.stringValue
        }
        return ""
    }

    private static func nonVide(_ s: String) -> String? { return s.isEmpty ? nil : s }

    /// Adresse http(s) gardée ; tout autre schéma est retiré.
    static func lienWeb(_ s: String) -> URL? {
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        let b = t.lowercased()
        guard b.hasPrefix("https://") || b.hasPrefix("http://") else { return nil }
        return URL(string: t)
    }

    private static func option(_ o: Any) -> Option {
        if let d = o as? [String: Any] {
            let label = nonVide(chaine(d["label"])) ?? chaine(d["message"])
            let message = nonVide(chaine(d["message"])) ?? chaine(d["label"])
            return Option(label: label, message: message, lien: lienWeb(chaine(d["lien"])))
        }
        let t = chaine(o)
        return Option(label: t, message: t, lien: nil)
    }

    private static func carte(_ d: [String: Any]) -> Carte? {
        let titre = chaine(d["titre"])
        guard !titre.isEmpty else { return nil }
        let actions = (d["actions"] as? [Any] ?? []).map(option).filter { !$0.label.isEmpty }
        return Carte(titre: titre, image: chaine(d["image"]), prix: chaine(d["prix"]), sousTitre: chaine(d["sous_titre"]),
                     description: chaine(d["description"]), lien: lienWeb(chaine(d["lien"])), actions: actions)
    }

    private static func champ(_ d: [String: Any]) -> Champ {
        let nom = d["nom"].map { chaine($0) }
        let label = chaine(d["label"])
        let cle = (d["nom"] == nil || d["nom"] is NSNull) ? label : (nom ?? label)
        return Champ(cle: cle, label: nonVide(label) ?? (nom ?? ""), type: chaine(d["type"]),
                     options: (d["options"] as? [Any] ?? []).map { chaine($0) },
                     valeur: (d["valeur"] == nil || d["valeur"] is NSNull) ? nil : chaine(d["valeur"]),
                     aide: chaine(d["aide"]))
    }
}
