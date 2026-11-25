import Foundation

/**
 * Appareils de l'onglet Fichiers (`web/files-browser.js`) : le serveur CCS, puis chaque PC de
 * `machines.list` (sauf le serveur lui-même). Un PC est joignable s'il est en ligne et qu'on peut
 * l'atteindre par le réseau maillé (`mesh_ip`) ou par le tunnel Ricochet ; les autres sont montrés
 * grisés, avec la raison.
 */
enum Appareils {
    static let nomServeur = "Serveur CCS"

    struct Appareil: Identifiable, Equatable {
        /// Vide : le serveur CCS ; sinon l'identifiant de la machine.
        let id: String
        let nom: String
        let icone: String
        let joignable: Bool
        /// Pourquoi l'appareil n'est pas joignable (« hors ligne »…), nil s'il l'est.
        let raison: String?

        var estServeur: Bool { return id.isEmpty }
    }

    /// Un PC où parcourir des dossiers : en ligne, par le réseau maillé ou le tunnel.
    static func joignable(_ m: Machine) -> Bool {
        let maille = !(m.meshIp ?? "").trimmingCharacters(in: .whitespaces).isEmpty
        return !m.local && m.online && (maille || m.tunnel)
    }

    /// « hors ligne », « ni réseau maillé ni tunnel », ou nil si la machine est joignable.
    static func raison(_ m: Machine) -> String? {
        if joignable(m) { return nil }
        if !m.online { return "hors ligne" }
        return "ni réseau maillé ni tunnel"
    }

    /// Icône SF Symbols : portable si son nom le dit, sinon ordinateur de bureau.
    static func icone(_ m: Machine) -> String {
        let noms = [m.id, m.name, m.mesh ?? "", m.host ?? ""].joined(separator: " ").lowercased()
        return noms.contains("lp-") || noms.contains("laptop") || noms.contains("portable") ? "laptopcomputer" : "desktopcomputer"
    }

    /// La barre d'appareils : « Serveur CCS » d'abord, puis les machines (le serveur lui-même exclu).
    static func liste(_ machines: [Machine]) -> [Appareil] {
        let serveur = Appareil(id: "", nom: nomServeur, icone: "cloud", joignable: true, raison: nil)
        return [serveur] + machines.filter { !$0.local }.map { m in
            Appareil(id: m.id, nom: m.nom, icone: icone(m), joignable: joignable(m), raison: raison(m))
        }
    }

    /// Nom affiché d'un appareil (son identifiant s'il n'est pas dans la liste).
    static func nom(_ id: String, _ machines: [Machine]) -> String {
        if id.isEmpty { return nomServeur }
        return machines.first { $0.id == id }?.nom ?? id
    }

    /**
     * Faut-il une connexion à part pour cet appareil ? Non s'il est déjà celui de la connexion
     * principale (la machine pilotée, vide pour le serveur) : on la réutilise.
     */
    static func connexionAPart(appareil: String, pilotee: String) -> Bool {
        return appareil != pilotee
    }

    /// « lp-work injoignable : hors ligne » (le serveur : le message seul).
    static func messageInjoignable(_ nom: String, serveur: Bool, _ raison: String) -> String {
        return serveur ? raison : "\(nom) injoignable : \(raison)"
    }
}
