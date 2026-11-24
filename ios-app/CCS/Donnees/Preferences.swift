import Foundation

/// Thème de l'appli : celui du système, clair ou sombre.
enum Theme: String, CaseIterable {
    case systeme, clair, sombre

    var libelle: String {
        switch self {
        case .systeme: return "Système"
        case .clair: return "Clair"
        case .sombre: return "Sombre"
        }
    }
}

/// Petites préférences gardées dans `UserDefaults` (adresse, dossiers récents, brouillons…).
enum Prefs {
    private static var d: UserDefaults { return UserDefaults.standard }

    static func lire(_ cle: String) -> String? { return d.string(forKey: cle) }

    static func ecrire(_ cle: String, _ valeur: String?) {
        if let v = valeur { d.set(v, forKey: cle) } else { d.removeObject(forKey: cle) }
    }

    // MARK: adresse du serveur

    static var adresse: String {
        return lire("serveur").flatMap { Adresse.normaliser($0) } ?? Adresse.parDefaut
    }

    /// Enregistre l'adresse normalisée et la rend ; nil (rien n'est changé) si elle est invalide.
    static func changerAdresse(_ texte: String) -> String? {
        guard let a = Adresse.normaliser(texte) else { return nil }
        ecrire("serveur", a)
        return a
    }

    // MARK: thème

    static var theme: Theme {
        get { return lire("theme").flatMap { Theme(rawValue: $0) } ?? .systeme }
        set { ecrire("theme", newValue.rawValue) }
    }

    // MARK: terminal

    /// Taille du texte du terminal (points), bornée par `Touches`.
    static var tailleTerminal: Int {
        get { let t = d.integer(forKey: "taille-terminal"); return t == 0 ? Touches.tailleDefaut : Touches.borner(t) }
        set { d.set(Touches.borner(newValue), forKey: "taille-terminal") }
    }

    // MARK: voix

    /// Lire à voix haute chaque réponse de Claude terminée (désactivé par défaut).
    static var lireReponses: Bool {
        get { return d.bool(forKey: "lire-reponses") }
        set { d.set(newValue, forKey: "lire-reponses") }
    }

    /// Son partagé : « Rester à l'écoute » (récepteur UDP toujours ouvert, désactivé par défaut).
    static var resterALEcoute: Bool {
        get { return d.bool(forKey: Son.cleResterALEcoute) }
        set { d.set(newValue, forKey: Son.cleResterALEcoute) }
    }

    // MARK: dossiers récents de « Nouvelle session » (8 au plus, le plus récent d'abord)

    static func recents() -> [String] {
        return d.stringArray(forKey: "dossiers-recents") ?? []
    }

    static func retenirRecent(_ chemin: String) {
        let c = chemin.trimmingCharacters(in: .whitespaces)
        if c.isEmpty { return }
        let liste = [c] + recents().filter { $0 != c }
        d.set(Array(liste.prefix(8)), forKey: "dossiers-recents")
    }
}
