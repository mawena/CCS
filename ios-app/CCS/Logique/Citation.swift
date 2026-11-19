import Foundation

/**
 * Répondre en citant un message : format du message envoyé, le même que `web/chat-quote.js` et
 * `ccs_app/chat_quote.py`. Le message commence par la citation en bloc Markdown, puis la réponse :
 *
 *     > **Claude :**
 *     > le passage cité
 *
 *     la réponse
 */
enum Citation {
    enum Auteur: String, CaseIterable {
        case claude, moi

        var etiquette: String { return self == .claude ? "Claude" : "Moi" }
        var affiche: String { return self == .claude ? "Claude" : "Toi" }
    }

    /// Message cité : son auteur et le passage.
    struct Cite: Equatable {
        let auteur: Auteur
        let texte: String
    }

    /// Message de l'utilisateur qui commence par une citation : la citation et la réponse.
    struct Decoupe: Equatable {
        let auteur: Auteur
        let texte: String
        let corps: String
    }

    static let maxCite = 1200          // message cité en entier : au-delà, seulement son début
    static let maxSelection = 4000
    static let coupe = " […]"

    private static func propre(_ t: String?) -> String {
        return (t ?? "").replacingOccurrences(of: "\r\n", with: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Texte à citer : sans blancs autour, coupé à `limite` caractères (entre deux mots si possible).
    static func extrait(_ texte: String?, limite: Int = maxCite) -> String {
        let p = propre(texte)
        let scalaires = Array(p.unicodeScalars)
        if scalaires.count <= limite { return p }
        var tranche = Array(scalaires[0..<limite])
        if let espace = tranche.lastIndex(where: { $0 == " " || $0 == "\n" }), espace >= tranche.count - 80 {
            tranche = Array(tranche[0..<espace])
        }
        var vue = String.UnicodeScalarView()
        vue.append(contentsOf: tranche)
        var s = String(vue)
        while let d = s.last, d.isWhitespace { s.removeLast() }
        return s + coupe
    }

    /// Message à envoyer : la citation puis `corps`. Sans citation valable : `corps` tel quel.
    static func composer(_ auteur: Auteur?, _ cite: String?, _ corps: String = "") -> String {
        let t = propre(cite)
        guard let a = auteur, !t.isEmpty else { return corps }
        let lignes = t.components(separatedBy: "\n").map { $0.trimmingCharacters(in: .whitespaces).isEmpty ? ">" : "> " + $0 }
        let tete = (["> **\(a.etiquette) :**"] + lignes).joined(separator: "\n")
        return corps.isEmpty ? tete : tete + "\n\n" + corps
    }

    /// Citation en tête d'un message de l'utilisateur, ou nil.
    static func decouper(_ texte: String?) -> Decoupe? {
        guard let texte = texte, texte.hasPrefix("> **") else { return nil }
        let lignes = texte.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n")
        var premiere = lignes[0]
        while let d = premiere.last, d.isWhitespace { premiere.removeLast() }
        guard let auteur = Auteur.allCases.first(where: { premiere == "> **\($0.etiquette) :**" }) else { return nil }
        var cite: [String] = []
        var i = 1
        while i < lignes.count && lignes[i].hasPrefix(">") {
            var l = String(lignes[i].dropFirst())
            if l.hasPrefix(" ") { l.removeFirst() }
            cite.append(l)
            i += 1
        }
        let texteCite = cite.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        if texteCite.isEmpty { return nil }
        var reste = Array(lignes[i...])
        if let r = reste.first, r.trimmingCharacters(in: .whitespaces).isEmpty { reste.removeFirst() }
        return Decoupe(auteur: auteur, texte: texteCite, corps: reste.joined(separator: "\n"))
    }

    /// Texte d'un message de l'utilisateur à citer à son tour : sa réponse, pas ce qu'il citait.
    static func texteSource(_ texte: String) -> String {
        guard let d = decouper(texte) else { return texte }
        return d.corps.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? d.texte : d.corps
    }

    /// Ce qu'on cite d'un message entier (`brut` : son texte d'origine).
    static func de(_ auteur: Auteur, _ brut: String) -> Cite? {
        let t = extrait(auteur == .moi ? texteSource(brut) : brut)
        return t.isEmpty ? nil : Cite(auteur: auteur, texte: t)
    }

    /// Aperçu sur une ligne (bandeau au-dessus de la saisie).
    static func uneLigne(_ texte: String?, limite: Int = 140) -> String {
        let l = (texte ?? "").split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        return l.count > limite ? String(l.prefix(limite - 1)) + "…" : l
    }
}
