import Foundation

/// Logique d'envoi du chat (`deliver`, `send`, `isSlashCommand` de `web/chat.js`).
enum Envoi {
    /// Commande de Claude Code (`/clear`, `/compact`…) : un `/` suivi d'une lettre, en tête.
    static func estCommandeSlash(_ texte: String?) -> Bool {
        guard let t = texte else { return false }
        let s = t.drop(while: { $0.isWhitespace })
        guard s.first == "/", let l = s.dropFirst().first else { return false }
        return l.isASCII && l.isLetter
    }

    /// Commande du shell (`!ls`) : lancée dans le dossier du projet, pas envoyée à Claude.
    static func commandeShell(_ texte: String, images: Int) -> String? {
        let t = texte.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.hasPrefix("!"), t.count > 1, images == 0 else { return nil }
        let c = String(t.dropFirst()).trimmingCharacters(in: .whitespacesAndNewlines)
        return c.isEmpty ? nil : c
    }

    /**
     * Message prêt à partir : `envoye` (texte pour Claude), `montre` (bulle), `commande` (envoyé
     * seul : la citation et les sorties `!` attendent le prochain message).
     */
    struct Pret: Equatable {
        let envoye: String
        let montre: String
        let commande: Bool
    }

    static func preparer(_ texte: String, images: Int, citation: Citation.Cite?, notesShell: [String]) -> Pret {
        if estCommandeSlash(texte) && images == 0 {
            let t = texte.trimmingCharacters(in: .whitespacesAndNewlines)
            return Pret(envoye: t, montre: t, commande: true)
        }
        let notes = notesShell.joined()
        guard let c = citation else { return Pret(envoye: notes + texte, montre: texte, commande: false) }
        return Pret(
            envoye: Citation.composer(c.auteur, c.texte, notes + texte),
            montre: Citation.composer(c.auteur, c.texte, texte),
            commande: false
        )
    }

    /// Sortie d'une commande `!`, ajoutée en tête du prochain message pour Claude.
    static func noteShell(_ commande: String, code: Int, sortie: String, tronquee: Bool) -> String {
        let montre = sortie + (tronquee ? "\n[sortie tronquée]" : "")
        return "J'ai lancé `\(commande)` dans le dossier du projet (code \(code)) :\n```\n\(montre)\n```\n\n"
    }

    /// Commandes `/…` proposées pendant la saisie d'un `/nom` (début du nom, puis ailleurs dans le nom).
    static func completer(_ saisie: String, _ commandes: [CommandeSlash], max nombre: Int = 8) -> [CommandeSlash] {
        guard saisie.hasPrefix("/"), !saisie.contains(" "), !saisie.contains("\n") else { return [] }
        let q = String(saisie.dropFirst()).lowercased()
        let debut = commandes.filter { $0.nom.lowercased().hasPrefix(q) }
        let ailleurs = q.isEmpty ? [] : commandes.filter { c in !debut.contains(c) && c.nom.lowercased().contains(q) }
        return Array((debut + ailleurs).prefix(nombre))
    }

    /// Identifiant uuid v4 du message envoyé (étiquettes : le même en direct et dans le journal).
    static func nouvelUuid() -> String { return UUID().uuidString.lowercased() }
}

/// Recherche dans le fil (`web/chat-search.js`) : sans accents ni majuscules, boucle aux extrémités.
enum Recherche {
    static func plier(_ s: String) -> String {
        var vue = String.UnicodeScalarView()
        for u in s.decomposedStringWithCanonicalMapping.unicodeScalars where u.properties.generalCategory != .nonspacingMark {
            vue.append(u)
        }
        return String(vue).lowercased()
    }

    static func trouver(_ textes: [String], _ requete: String) -> [Int] {
        let aiguille = plier(requete).trimmingCharacters(in: .whitespacesAndNewlines)
        if aiguille.isEmpty { return [] }
        return textes.indices.filter { plier(textes[$0]).contains(aiguille) }
    }

    static func pas(_ at: Int, _ nombre: Int, _ sens: Int) -> Int {
        return nombre == 0 ? -1 : (at + sens + nombre) % nombre
    }
}

/// Étiquettes des messages (`web/chat-tags.js`, nettoyage comme `message_tags.py`).
enum Etiquettes {
    static let maxNombre = 10
    static let maxCar = 40

    static func nettoyer(_ t: String) -> String {
        let mots = t.replacingOccurrences(of: ",", with: " ").split(whereSeparator: { $0.isWhitespace })
        return String(mots.joined(separator: " ").prefix(maxCar)).trimmingCharacters(in: .whitespaces)
    }

    static func nettoyer(_ liste: [String]) -> [String] {
        var vues = Set<String>()
        var out: [String] = []
        for t in liste.map({ nettoyer($0) }) where !t.isEmpty {
            if vues.insert(t.lowercased()).inserted { out.append(t) }
        }
        return Array(out.prefix(maxNombre))
    }

    static func lire(_ texte: String) -> [String] {
        return nettoyer(texte.components(separatedBy: ","))
    }

    /// Étiquettes par ordre alphabétique (sans casse), messages dans l'ordre où ils ont été étiquetés.
    static func parEtiquette(_ messages: [String: EntreeEtiquettes]) -> [(etiquette: String, messages: [(id: String, entree: EntreeEtiquettes)])] {
        var groupes: [String: (etiquette: String, messages: [(id: String, entree: EntreeEtiquettes)])] = [:]
        let tries = messages.sorted { a, b in a.value.ts != b.value.ts ? a.value.ts < b.value.ts : a.key < b.key }
        for (id, e) in tries {
            for t in e.etiquettes {
                let k = t.lowercased()
                var g = groupes[k] ?? (etiquette: t, messages: [])
                g.messages.append((id: id, entree: e))
                groupes[k] = g
            }
        }
        return groupes.keys.sorted().compactMap { groupes[$0] }
    }
}

/// Alerte de contexte lourd (`web/chat-context.js`).
enum AlerteContexte {
    static let partGardee = 0.2      // part du contexte gardée après `/compact` (comme context_alert.py)

    struct Decision: Equatable {
        let lourd: Bool
        let gain: Int?
    }

    static func decider(_ ev: MesureContexte, actif: Bool, seuil: Int, dejaLourd: Bool) -> Decision {
        if ev.auto { return Decision(lourd: false, gain: nil) }      // le pont compacte lui-même
        let dessus = actif && seuil > 0 && ev.total >= seuil
        return Decision(lourd: dessus, gain: (dessus && !dejaLourd) ? ev.total - Int(Double(ev.total) * partGardee) : nil)
    }
}
