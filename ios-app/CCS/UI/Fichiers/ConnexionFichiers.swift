import SwiftUI

/**
 * Appareil ouvert dans l'onglet Fichiers et sa connexion (`web/files-browser.js`). Le serveur CCS
 * ou un PC du réseau maillé : si ce n'est pas la machine pilotée, une connexion à part, fixée sur
 * lui (`/api/ws?protocol=1&machine=<id>`), sans changer la machine pilotée de l'appli. Elle est
 * fermée en quittant l'onglet et rouverte en y revenant ; le dernier appareil choisi est gardé.
 */
@MainActor
@Observable
final class ConnexionFichiers {
    nonisolated private static let cleAppareil = "fichiers:appareil"

    /// Vide : le serveur CCS ; sinon l'identifiant de la machine.
    private(set) var appareil: String = Prefs.lire(ConnexionFichiers.cleAppareil) ?? ""
    /// Connexion à part, fixée sur `appareil` (gardée arrêtée hors de l'onglet).
    private(set) var connexion: CcsClient? = nil

    private let principal: CcsClient
    /// Connexion jamais démarrée, rendue tant que celle de l'appareil n'existe pas encore :
    /// les écrans attendent (rien n'est lu sur un autre appareil que celui choisi).
    private let enAttente: CcsClient
    @ObservationIgnored var identifiants: () -> Identifiants? = { nil }

    init(principal: CcsClient) {
        self.principal = principal
        self.enAttente = CcsClient(machineFixe: "")
    }

    /// Faut-il une connexion à part pour l'appareil choisi ?
    var aPart: Bool { return Appareils.connexionAPart(appareil: appareil, pilotee: principal.machine) }

    /// Connexion à utiliser pour l'appareil ouvert.
    var client: CcsClient { return clientPour(appareil) }

    /// Connexion pour `appareil` (nil : la connexion principale, hors de l'onglet Fichiers).
    func clientPour(_ appareil: String?) -> CcsClient {
        guard let a = appareil, Appareils.connexionAPart(appareil: a, pilotee: principal.machine) else { return principal }
        if let c = connexion, c.machine == a { return c }
        return enAttente
    }

    /// Ouvre un autre appareil (gardé pour la prochaine fois).
    func choisir(_ id: String) {
        guard id != appareil else { return }
        appareil = id
        Prefs.ecrire(ConnexionFichiers.cleAppareil, id.isEmpty ? nil : id)
        ouvrir()
    }

    /// Ouvre (ou rouvre) la connexion qu'il faut pour l'appareil choisi ; ne fait rien de plus si elle est là.
    func ouvrir() {
        guard aPart else {
            fermer()
            return
        }
        if let c = connexion, c.machine != appareil {
            c.arreter()
            connexion = nil
        }
        let c: CcsClient
        if let existante = connexion {
            c = existante
        } else {
            c = CcsClient(machineFixe: appareil)
            connexion = c
        }
        switch c.etat {
        case .arrete, .refuse:
            if let i = identifiants() { c.demarrer(i) }
        default:
            break
        }
    }

    /// Nouvel essai tout de suite (« Réessayer »).
    func reessayer() {
        guard let c = connexion else {
            ouvrir()
            return
        }
        switch c.etat {
        case .arrete, .refuse: ouvrir()
        default: c.reessayer()
        }
    }

    /// Ferme la connexion à part (onglet quitté) ; elle se rouvre au retour.
    func fermer() {
        connexion?.arreter()
    }

    /// Déconnexion de l'appli : tout est oublié.
    func oublier() {
        connexion?.arreter()
        connexion = nil
    }
}

private struct CleAppareilFichiers: EnvironmentKey {
    static let defaultValue: String? = nil
}

extension EnvironmentValues {
    /// Appareil dont les écrans Fichiers lisent les dossiers (nil : la machine pilotée).
    var appareilFichiers: String? {
        get { return self[CleAppareilFichiers.self] }
        set { self[CleAppareilFichiers.self] = newValue }
    }
}
