import Foundation

/// Règles du son partagé côté appli (phase 42), sans interface : nom de l'appareil, adresse maillée.
enum Son {
    /// Annonce au pont toutes les 30 s ; il oublie l'appareil 90 s après la dernière.
    static let periodeAnnonce: Double = 30
    /// Rien reçu pendant 10 s : on cesse d'écouter.
    static let silenceMax: Double = 10
    /// Tampon matériel demandé à iOS (`setPreferredIOBufferDuration`) : 5 ms.
    static let tamponMateriel: Double = 0.005
    /// Son programmé d'avance sur le lecteur : au moins 20 ms et au moins deux tampons.
    static let avanceMinMs = 20
    static let tamponsEnVolMin = 2
    /// Clé `UserDefaults` du réglage « Rester à l'écoute » (désactivé par défaut) : récepteur UDP
    /// toujours ouvert sur le port annoncé, session audio gardée par du silence, tout paquet RTP
    /// joué tout de suite (même sans événement « receive »).
    static let cleResterALEcoute = "son-rester-a-l-ecoute"

    /// Adresse du réseau maillé (100.64.0.0/10, plage de Tailscale et Headscale).
    static func estMaillee(_ ip: String) -> Bool {
        let p = ip.split(separator: ".", omittingEmptySubsequences: false).map { Int($0) }
        guard p.count == 4, p.allSatisfy({ $0 != nil && (0...255).contains($0!) }) else { return false }
        return p[0]! == 100 && (64...127).contains(p[1]!)
    }

    /// Première adresse maillée parmi celles des interfaces (`utun*` d'abord, comme sur iOS).
    static func adresseMaillee(_ interfaces: [(nom: String, ip: String)]) -> String? {
        let maillees = interfaces.filter { estMaillee($0.ip) }
        return (maillees.first { $0.nom.hasPrefix("utun") } ?? maillees.first)?.ip
    }

    /// Nom accepté par le pont : lettres, chiffres, `.`, `_`, `-`, 63 au plus, sans signe au début.
    static func nettoyer(_ n: String) -> String {
        let permis = Set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
        var s = String(n.trimmingCharacters(in: .whitespaces).map { permis.contains($0) ? $0 : "-" })
        while let c = s.first, !(c.isLetter || c.isNumber) { s.removeFirst() }
        return String(s.prefix(63))
    }

    /**
     * Nom de cet appareil sur le réseau maillé : le pair (`self` ou `peers[]` de `network.status`)
     * qui porte son adresse 100.64.x ; à défaut, un nom tiré du modèle (`iphone`, `ipad`).
     */
    static func nomAppareil(ip: String?, etat: EtatReseau?, modele: String) -> String {
        if let ip = ip, let e = etat {
            let tous = (e.ici.map { [$0] } ?? []) + e.peers
            if let a = tous.first(where: { $0.ips.contains(ip) }) {
                let n = nettoyer(a.name)
                if !n.isEmpty { return n }
            }
        }
        return modele.lowercased().contains("ipad") ? "ipad" : "iphone"
    }

    /// Les sorties vers lesquelles cet appareil peut envoyer son son (lui excepté).
    static func sortiesPour(_ moi: String, _ l: ListeSon) -> [AppareilSon] {
        return l.sorties.filter { $0.device != moi }
    }

    /// Le flux qui joue sur cet appareil, et celui qu'il émet (d'après `audio.list`).
    static func flux(de moi: String, _ l: ListeSon) -> (recu: FluxSon?, emis: FluxSon?) {
        return (l.streams.first { $0.target == moi }, l.streams.first { $0.source == moi })
    }

    /// Icône d'un appareil annoncé, selon son système.
    static func icone(_ a: AppareilSon) -> String {
        switch a.system {
        case "ios": return a.device.lowercased().contains("ipad") ? "ipad" : "iphone"
        case "android": return "candybarphone"
        case "web": return "safari"
        case "linux":
            let n = a.device.lowercased()
            if ["vps", "cloud", "serveur", "server"].contains(where: { n.contains($0) }) { return "server.rack" }
            return n.contains("laptop") || n.contains("portable") ? "laptopcomputer" : "desktopcomputer"
        default: return "speaker.wave.2"
        }
    }
}
