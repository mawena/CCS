import SwiftUI
import UIKit
import WebKit

/// État de l'appli : adresse du serveur, identifiants gardés, connexion, thème, avis.
@MainActor
@Observable
final class ModeleAppli {
    let client = CcsClient()
    let avis = Avis()

    private(set) var adresse: String
    private(set) var identifiants: Identifiants? = nil
    /// Pourquoi on est revenu à l'écran de connexion (jeton révoqué…), affiché une fois.
    var avisConnexion: String? = nil
    private(set) var theme: Theme

    /// Coûts des conversations déjà lus (clé : chemin + date), demandés un à la fois.
    @ObservationIgnored var couts: [String: String] = [:]
    @ObservationIgnored private var fileCouts: Task<Void, Never>? = nil

    init() {
        let a = Prefs.adresse
        adresse = a
        theme = Prefs.theme
        let i = Coffre.lire()
        identifiants = (i?.serveur == a) ? i : nil
        client.surRefus = { [weak self] raison in
            self?.oublier()
            self?.avisConnexion = raison + " Reconnecte-toi."
        }
        if let i = identifiants { demarrer(i) }
    }

    private func demarrer(_ i: Identifiants) {
        guard i.portier else {
            client.demarrer(i)
            return
        }
        // connexion Portier sans jeton d'appareil : on le demande une fois, avant le WebSocket
        Task { @MainActor in
            let jeton = await ApiHttp.jetonAppli(i, nom: ModeleAppli.nomModele())
            var j = i
            if let t = jeton {
                j.jeton = t
                Coffre.ecrire(j)
                self.identifiants = j
            }
            if self.identifiants != nil, case .arrete = self.client.etat { self.client.demarrer(j) }
        }
    }

    func changerTheme(_ t: Theme) {
        theme = t
        Prefs.theme = t
    }

    func connecte(_ i: Identifiants) {
        Coffre.ecrire(i)
        identifiants = i
        avisConnexion = nil
        client.demarrer(i)
    }

    func deconnecter() {
        let portier = identifiants?.viaPortier == true
        oublier()
        if portier {
            let magasin = WKWebsiteDataStore.default()
            magasin.removeData(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes(), modifiedSince: Date.distantPast) {}
        }
    }

    private func oublier() {
        client.arreter()
        Coffre.ecrire(nil)
        identifiants = nil
        couts = [:]
    }

    /// Coût court d'une conversation (« 0,42 $ ») ; le coût est un plus : un échec est tu.
    func cout(chemin: String, cle: String) async -> String? {
        if let c = couts[cle] { return c }
        let precedent = fileCouts
        let t = Task { @MainActor () -> String? in
            _ = await precedent?.value
            if let c = self.couts[cle] { return c }
            guard let r = try? await self.client.appeler("conversation.cost", ["path": .chaine(chemin)], en: Cout.self) else { return nil }
            self.couts[cle] = r.short
            return r.short
        }
        fileCouts = Task { @MainActor in _ = await t.value }
        return await t.value
    }

    /// Rend false si l'adresse est invalide.
    func changerAdresse(_ texte: String) -> Bool {
        guard let a = Prefs.changerAdresse(texte) else { return false }
        adresse = a
        return true
    }

    /// Modèle de l'appareil (`iPhone14,2`), pour nommer le jeton d'appareil.
    static func identifiantMateriel() -> String {
        var u = utsname()
        uname(&u)
        let brut = withUnsafeBytes(of: &u.machine) { (p: UnsafeRawBufferPointer) -> String in
            let octets = p.prefix { $0 != 0 }
            return String(decoding: octets, as: UTF8.self)
        }
        return brut.isEmpty ? UIDevice.current.model : brut
    }

    /// Nom du jeton demandé après Portier.
    static func nomModele() -> String {
        return String("\(UIDevice.current.model) \(identifiantMateriel())".prefix(60))
    }

    /// Nom de l'appareil donné à l'appairage.
    static func nomAppareil() -> String {
        return String("Appli iOS (\(UIDevice.current.model) \(identifiantMateriel()))".prefix(60))
    }
}
