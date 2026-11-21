import Foundation

/// Usage d'un tour (`TurnResult.usage`, `ccs_app/token_use.py` : `turn_usage`).
struct UsageTour: Equatable {
    var entree = 0          // `input` : tokens frais
    var cacheLu = 0         // `cache_read`
    var cacheEcrit = 0      // `cache_write`
    var produits = 0        // `output`
    var coutUsd = 0.0       // `cost_usd` : coût du tour seul
    var contexte = 0        // `context` : taille du contexte pour le message suivant
    var ttlCache = 0        // `cache_ttl_s` : 300 ou 3600
    var modele = ""         // `model`

    /// nil si l'usage est absent, `{}` ou tout à zéro.
    static func lire(_ j: JSON?) -> UsageTour? {
        guard let o = j, case .objet = o else { return nil }
        let u = UsageTour(
            entree: max(0, o.entier("input")), cacheLu: max(0, o.entier("cache_read")),
            cacheEcrit: max(0, o.entier("cache_write")), produits: max(0, o.entier("output")),
            coutUsd: o.double("cost_usd"), contexte: max(0, o.entier("context")),
            ttlCache: o.entier("cache_ttl_s"), modele: o.texte("model")
        )
        if u.entree == 0 && u.cacheLu == 0 && u.cacheEcrit == 0 && u.produits == 0 && u.contexte == 0 { return nil }
        return u
    }
}

/// Textes et seuils de la consommation de tokens (mêmes mots que `token_use.py`).
enum Jetons {
    /// Seuil du contexte lourd par défaut (`context_alert.threshold_tokens`).
    static let seuilDefaut = 150_000

    /// 12 345 → « 12 k », 1 234 567 → « 1,2 M », 403 → « 403 » (`fmt_tokens`).
    static func court(_ n: Int) -> String {
        let v = max(0, n)
        if v >= 1_000_000 { return String(format: "%.1f M", Double(v) / 1e6).replacingOccurrences(of: ".", with: ",") }
        if v >= 1000 { return "\(Int((Double(v) / 1000).rounded(.toNearestOrEven))) k" }
        return "\(v)"
    }

    /// Ligne sous une réponse : « 36 k lus · 15 k écrits · 403 produits · 0,04 $ » (`summary`).
    static func resume(_ u: UsageTour?) -> String {
        guard let u = u else { return "" }
        var parts: [String] = []
        if u.cacheLu > 0 { parts.append("\(court(u.cacheLu)) lus") }
        let ecrits = u.cacheEcrit + u.entree
        if ecrits > 0 { parts.append("\(court(ecrits)) écrits") }
        parts.append("\(court(u.produits)) produits")
        if u.coutUsd != 0 { parts.append(String(format: "%.2f $", u.coutUsd).replacingOccurrences(of: ".", with: ",")) }
        return parts.joined(separator: " · ")
    }

    enum Niveau: Equatable { case vert, orange, rouge }

    /// Vert sous la moitié du seuil, orange jusqu'au seuil, rouge au-delà (seuil ≤ 0 : défaut).
    static func niveau(_ contexte: Int, seuil: Int) -> Niveau {
        let s = seuil > 0 ? seuil : seuilDefaut
        if contexte > s { return .rouge }
        if contexte * 2 < s { return .vert }
        return .orange
    }

    /// Confirmation avant d'envoyer un message une fois le cache expiré.
    static func avertissementCache(_ contexte: Int) -> String {
        return "Le cache a expiré : ce message relira \(court(contexte)) tokens au prix fort."
    }
}
