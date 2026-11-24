import Foundation

/**
 * Échange entre l'appli et l'extension de diffusion (`Diffusion`) par le groupe d'applis
 * `group.<bundle id de l'appli>` : l'appli y écrit la cible (ip, port) et la demande d'arrêt,
 * l'extension y écrit qu'elle tourne (battement toutes les secondes). Partagé par les deux cibles.
 *
 * SideStore re-signe l'appli avec un identifiant Apple gratuit et renomme bundle et groupe (suffixe
 * de l'équipe) : le groupe réel est lu dans `ALTAppGroups` (ajouté par SideStore/AltStore à
 * l'Info.plist), sinon déduit du bundle id de l'appli, sinon le nom d'origine.
 */
enum GroupeSon {
    static let groupeOrigine = "group.com.mawena.ccs"
    /// Suffixe du bundle id de l'extension (`com.mawena.ccs.diffusion`).
    static let suffixeExtension = ".diffusion"

    private enum Cle {
        static let ip = "son.cible.ip"
        static let port = "son.cible.port"
        static let nom = "son.cible.nom"
        static let flux = "son.flux"
        static let arret = "son.arret"
        static let battement = "son.diffusion.vu"
        static let erreur = "son.diffusion.erreur"
    }

    /// Bundle id de l'appli, vu de l'appli ou de son extension.
    static var bundleAppli: String {
        let b = Bundle.main.bundleIdentifier ?? "com.mawena.ccs"
        if Bundle.main.bundlePath.hasSuffix(".appex"), let r = b.range(of: ".", options: .backwards) {
            return String(b[..<r.lowerBound])
        }
        return b
    }

    /// Bundle id de l'extension de diffusion, pour `RPSystemBroadcastPickerView.preferredExtension`.
    static var bundleExtension: String { return bundleAppli + suffixeExtension }

    static let groupe: String = {
        let candidats = ((Bundle.main.object(forInfoDictionaryKey: "ALTAppGroups") as? [String]) ?? [])
            + ["group." + bundleAppli, groupeOrigine]
        let fm = FileManager.default
        return candidats.first { fm.containerURL(forSecurityApplicationGroupIdentifier: $0) != nil } ?? groupeOrigine
    }()

    private static let stock: UserDefaults? = UserDefaults(suiteName: groupe)

    /// Le groupe est-il utilisable (appli signée avec le droit App Group) ?
    static var disponible: Bool {
        return FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: groupe) != nil
    }

    struct Cible: Equatable {
        var ip: String
        var port: Int
        var nom: String
        var flux: String
    }

    // MARK: côté appli

    /// Où envoyer le son ; nil : nulle part (l'extension capte sans émettre).
    static func ecrireCible(_ c: Cible?) {
        guard let s = stock else { return }
        s.set(c?.ip ?? "", forKey: Cle.ip)
        s.set(c?.port ?? 0, forKey: Cle.port)
        s.set(c?.nom ?? "", forKey: Cle.nom)
        s.set(c?.flux ?? "", forKey: Cle.flux)
        if c != nil { s.set(false, forKey: Cle.arret) }
    }

    /// Demande à l'extension de finir la diffusion (lu dans la seconde).
    static func demanderArret() {
        ecrireCible(nil)
        stock?.set(true, forKey: Cle.arret)
    }

    /// Une diffusion tourne (battement de moins de 4 s).
    static var diffusionActive: Bool {
        guard let t = stock?.object(forKey: Cle.battement) as? Double, t > 0 else { return false }
        return Date().timeIntervalSince1970 - t < 4
    }

    static var derniereErreur: String? {
        let e = stock?.string(forKey: Cle.erreur) ?? ""
        return e.isEmpty ? nil : e
    }

    // MARK: côté extension

    static func lireCible() -> Cible? {
        guard let s = stock else { return nil }
        let ip = s.string(forKey: Cle.ip) ?? ""
        let port = s.integer(forKey: Cle.port)
        guard !ip.isEmpty, port > 0 else { return nil }
        return Cible(ip: ip, port: port, nom: s.string(forKey: Cle.nom) ?? "", flux: s.string(forKey: Cle.flux) ?? "")
    }

    /// Lit et efface la demande d'arrêt.
    static func prendreArret() -> Bool {
        guard let s = stock, s.bool(forKey: Cle.arret) else { return false }
        s.set(false, forKey: Cle.arret)
        return true
    }

    /// `true` : la diffusion tourne (appelé chaque seconde) ; `false` : elle est finie.
    static func battre(_ actif: Bool) {
        stock?.set(actif ? Date().timeIntervalSince1970 : 0, forKey: Cle.battement)
    }

    static func ecrireErreur(_ e: String?) {
        stock?.set(e ?? "", forKey: Cle.erreur)
    }
}
