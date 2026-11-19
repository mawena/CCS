import Foundation

/// Textes et calculs partagés par les écrans (mêmes mots que la version web).
enum Format {
    /// « à l'instant », « il y a 5 min », « il y a 3 h », « hier », « il y a 4 j » (`ago` de `dom.js`).
    static func ilYA(_ ts: Double?, maintenant: Double = Date().timeIntervalSince1970) -> String {
        guard let t = ts, t > 0 else { return "" }
        let s = max(0, maintenant - t)
        if s < 60 { return "à l'instant" }
        if s < 3600 { return "il y a \(Int((s / 60).rounded(.down))) min" }
        if s < 86400 { return "il y a \(Int((s / 3600).rounded(.down))) h" }
        let j = Int((s / 86400).rounded(.down))
        return j == 1 ? "hier" : "il y a \(j) j"
    }

    /// 1 234 567 → « 1.2 M » (`fmt` de `analysis.js`).
    static func nombreCourt(_ n: Double) -> String {
        if n >= 1e9 { return String(format: "%.1f G", n / 1e9) }
        if n >= 1e6 { return String(format: "%.1f M", n / 1e6) }
        if n >= 1e3 { return "\(Int((n / 1e3).rounded())) k" }
        return "\(Int(n.rounded()))"
    }

    /// Nombre avec séparateur des milliers à la française (« 84 000 »).
    static func milliers(_ n: Int) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.locale = Locale(identifier: "fr_FR")
        return f.string(from: NSNumber(value: n)) ?? "\(n)"
    }

    /// Dernier élément d'un chemin : `/home/x/Work/ccs` → `ccs`.
    static func base(_ chemin: String?) -> String {
        guard let c = chemin, !c.isEmpty else { return "" }
        return c.split(separator: "/").last.map(String.init) ?? c
    }

    /// `/home/x/Work/ccs` → `~/Work/ccs` quand `home` vaut `/home/x`.
    static func court(_ chemin: String, home: String) -> String {
        if !home.isEmpty && chemin.hasPrefix(home + "/") { return "~" + chemin.dropFirst(home.count) }
        return chemin
    }

    /// Pourcentage arrondi et borné d'une jauge.
    static func pourcent(_ p: Double) -> Int {
        guard p.isFinite else { return 0 }
        return min(100, max(0, Int(p.rounded())))
    }

    /// Lignes d'un graphique en barres : les 8 plus grosses, avec leur part du total (0…100).
    static func barres(_ donnees: [String: Double], total: Double, max nombre: Int = 8) -> [(nom: String, valeur: Double, part: Double)] {
        let tries = donnees.sorted { a, b in a.value != b.value ? a.value > b.value : a.key < b.key }
        return tries.prefix(nombre).map { e in
            (nom: e.key, valeur: e.value, part: total > 0 ? 100 * e.value / total : 0)
        }
    }

    enum Role: String {
        case toi = "Toi"
        case claude = "Claude"
    }

    /// « utilisateur » / « assistant » (ou en anglais) → rôle ; nil pour les outils et notes.
    static func role(_ r: String) -> Role? {
        switch r.lowercased() {
        case "utilisateur", "user": return .toi
        case "assistant": return .claude
        default: return nil
        }
    }
}

/// État d'un chat du pont, dit comme dans « En cours » de la version web.
enum EtatChat {
    case occupe, permission, pret, demarre, veille, arrete

    enum Ton { case occupe, attente, pret, arret }

    static func de(_ etat: String) -> EtatChat {
        switch etat {
        case "busy": return .occupe
        case "permission": return .permission
        case "idle": return .pret
        case "starting": return .demarre
        case "suspended": return .veille
        default: return .arrete
        }
    }

    var libelle: String {
        switch self {
        case .occupe: return "Claude travaille"
        case .permission: return "attend ta réponse"
        case .pret: return "prêt"
        case .demarre: return "démarre"
        case .veille: return "en veille"
        case .arrete: return "arrêté"
        }
    }

    var ton: Ton {
        switch self {
        case .occupe, .demarre: return .occupe
        case .permission: return .attente
        case .pret: return .pret
        case .veille, .arrete: return .arret
        }
    }
}

/// Dossier proposé par « Nouvelle session ».
struct DossierPropose: Equatable {
    let chemin: String
    let etiquette: String
}

/**
 * Dossiers proposés par « Nouvelle session » : récents, puis projets connus, puis dépôts git,
 * sans doublon, filtrés par le texte tapé (chemin complet ou court en `~`).
 */
func dossiersProposes(recents: [String], connus: [String], depots: [String], saisie: String, home: String) -> [DossierPropose] {
    var vus = Set<String>()
    var tous: [DossierPropose] = []
    for (liste, etiquette) in [(recents, "récent"), (connus, "projet"), (depots, "git")] {
        for c in liste where !vus.contains(c) {
            vus.insert(c)
            tous.append(DossierPropose(chemin: c, etiquette: etiquette))
        }
    }
    let q = saisie.trimmingCharacters(in: .whitespaces).lowercased()
    if q.isEmpty { return tous }
    let developpe = q.hasPrefix("~") ? home.lowercased() + q.dropFirst() : q
    return tous.filter {
        $0.chemin.lowercased().contains(developpe) || Format.court($0.chemin, home: home).lowercased().contains(q)
    }
}

/// Modèles et droits de « Nouvelle session » (`sessions-new.js`).
enum ChoixSession {
    static let modeles: [(valeur: String, libelle: String)] = [
        ("", "Par défaut"), ("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku"), ("fable", "Fable"),
    ]
    static let droits: [(valeur: String, libelle: String)] = [
        ("manual", "Demander"), ("acceptEdits", "Modifications acceptées"), ("plan", "Plan"), ("bypassPermissions", "Tout autoriser"),
    ]
    static let efforts: [(valeur: String, libelle: String)] = [
        ("", "Par défaut"), ("low", "Faible"), ("medium", "Moyen"), ("high", "Élevé"), ("xhigh", "Très élevé"), ("max", "Max"),
    ]
}

/// Périodes de l'analyse (`analysis.js`).
let periodesAnalyse: [(jours: Int, libelle: String)] = [(1, "24 heures"), (7, "7 jours"), (30, "30 jours"), (90, "90 jours")]
