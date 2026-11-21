import Foundation

/// Travaux distants (`ccs distant`) : mêmes mots que la page Machines du web (`pages-machines.js`).
enum Travaux {
    static let actifs: Set<String> = ["attente", "programmé", "envoi", "en cours"]
    static let limites = Array(1...8)

    static func actif(_ j: TravailDistant) -> Bool { return actifs.contains(j.state) }

    static func enCours(_ j: TravailDistant) -> Bool { return j.state == "en cours" || j.state == "envoi" }

    /// Durée lisible : « 42 s », « 3 min 07 s », « 2 h 05 » (`duration`).
    static func duree(_ secondes: Double) -> String {
        let s = max(0, Int(secondes.rounded()))
        if s < 60 { return "\(s) s" }
        if s < 3600 { return "\(s / 60) min " + String(format: "%02d", s % 60) + " s" }
        return "\(s / 3600) h " + String(format: "%02d", (s % 3600) / 60)
    }

    /// « pc-bureau · 3 min 07 s · code 0 · ~/Work/ccs » (`jobLine`).
    static func ligne(_ j: TravailDistant, home: String = "", maintenant: Double = Date().timeIntervalSince1970) -> String {
        var parts = [j.machine ?? "machine à choisir"]
        if let d = j.started { parts.append(duree((j.ended ?? maintenant) - d)) }
        else { parts.append("créé " + Format.ilYA(j.created, maintenant: maintenant)) }
        if let c = j.code { parts.append("code \(c)") }
        if !j.cwd.isEmpty { parts.append(Format.court(j.cwd, home: home)) }
        return parts.joined(separator: " · ")
    }

    enum Teinte { case attente, enCours, fini, echec, neutre }

    /// Couleur de la pastille d'état (`PILL`) ; « fini » avec un code non nul est un échec.
    static func teinte(_ j: TravailDistant) -> Teinte {
        switch j.state {
        case "attente", "programmé": return .attente
        case "envoi", "en cours": return .enCours
        case "fini": return (j.code ?? 0) != 0 ? .echec : .fini
        case "échec": return .echec
        default: return .neutre
        }
    }

    /// Paramètres de `machines.start` ; nil et un message si le formulaire est incomplet.
    static func demande(commande: String, dossier: String, home: String, machine: String, quand: String, heure: String) -> (params: [String: JSON]?, erreur: String?) {
        let t = commande.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty { return (nil, "Écris la commande à lancer.") }
        var cwd = dossier.trimmingCharacters(in: .whitespaces)
        if cwd.isEmpty { cwd = home }
        cwd = TachesFond.dossier(cwd, home: home)
        if cwd.isEmpty { return (nil, "Indique le dossier.") }
        var p: [String: JSON] = ["command": .chaine(t), "cwd": .chaine(cwd)]
        switch quand {
        case "heure":
            if !TachesFond.heureValide(heure) { return (nil, "Choisis l'heure.") }
            p["when"] = .chaine(heure)
        case "nuit": p["when"] = .chaine("nuit")
        default: p["when"] = .chaine("")
        }
        if !machine.isEmpty { p["machine"] = .chaine(machine) }
        return (p, nil)
    }
}
