import Foundation

/// Calculs de l'onglet Réseau, sans interface (testés à part). Mêmes règles que le web et Android.
enum Reseau {
    enum Chemin: String {
        case ici, lan, direct, relais, veille, horsLigne

        static func de(_ path: String) -> Chemin {
            switch path {
            case "self": return .ici
            case "lan": return .lan
            case "direct": return .direct
            case "relay": return .relais
            case "offline": return .horsLigne
            default: return .veille
            }
        }

        var libelle: String {
            switch self {
            case .ici: return "Cet appareil"
            case .lan: return "Réseau local"
            case .direct: return "Direct par internet"
            case .relais: return "Relais du VPS"
            case .veille: return "En veille"
            case .horsLigne: return "Hors ligne"
            }
        }

        var icone: String {
            switch self {
            case .ici: return "checkmark.circle.fill"
            case .lan: return "house.fill"
            case .direct: return "bolt.fill"
            case .relais: return "arrow.triangle.swap"
            case .veille, .horsLigne: return "waveform.path.ecg"
            }
        }
    }

    enum Genre { case serveur, portable, bureau, android, iphone }

    static func genre(_ a: Appareil) -> Genre {
        let os = a.os.lowercased()
        let nom = a.name.lowercased()
        if os == "ios" || nom.contains("iphone") || nom.contains("ipad") { return .iphone }
        if os == "android" || nom.contains("pixel") || nom.contains("phone") { return .android }
        if os == "macos" { return .portable }
        if ["vps", "cloud", "server", "serveur"].contains(where: { nom.contains($0) }) { return .serveur }
        if nom.contains("laptop") || nom.contains("portable") { return .portable }
        return .bureau
    }

    static func icone(_ a: Appareil) -> String {
        switch genre(a) {
        case .serveur: return "server.rack"
        case .portable: return "laptopcomputer"
        case .bureau: return "desktopcomputer"
        case .android: return "candybarphone"
        case .iphone: return "iphone"
        }
    }

    enum SorteAdresse: String {
        case locale = "Local", publique = "Public", v6 = "IPv6", maille = "Réseau"
    }

    struct Adresse: Equatable, Hashable {
        let ip: String
        let sorte: SorteAdresse
    }

    /// « 192.168.1.20:41641 » ou « [2a02::1]:41641 » → adresse et sorte.
    static func adresse(_ texte: String) -> Adresse {
        var hote = texte
        if texte.hasPrefix("["), let fin = texte.firstIndex(of: "]") {
            hote = String(texte[texte.index(after: texte.startIndex)..<fin])
        } else if let r = texte.range(of: ":[0-9]+$", options: .regularExpression) {
            hote.removeSubrange(r)
        }
        if hote.contains(":") {
            let l = hote.lowercased()
            let local = l.hasPrefix("fe80") || l.hasPrefix("fc") || l.hasPrefix("fd")
            return Adresse(ip: hote, sorte: local ? .locale : .v6)
        }
        let p = hote.split(separator: ".").map { Int($0) }
        guard p.count == 4, p.allSatisfy({ $0 != nil }) else { return Adresse(ip: hote, sorte: .publique) }
        let a = p[0]!, b = p[1]!
        if a == 100 && (64...127).contains(b) { return Adresse(ip: hote, sorte: .maille) }
        if a == 10 || (a == 172 && (16...31).contains(b)) || (a == 192 && b == 168) || (a == 169 && b == 254) {
            return Adresse(ip: hote, sorte: .locale)
        }
        return Adresse(ip: hote, sorte: .publique)
    }

    /// Adresses publiées par l'appareil, sans celles du réseau maillé.
    static func adressesPubliees(_ a: Appareil) -> [Adresse] {
        var vues = Set<String>()
        return a.addrs.map(adresse).filter { $0.sorte != .maille && vues.insert($0.ip).inserted }
    }

    struct Bilan: Equatable {
        let total, enLigne, lan, direct, relais: Int
    }

    static func bilan(_ e: EtatReseau) -> Bilan {
        let ici = e.ici == nil ? 0 : 1
        return Bilan(total: e.peers.count + ici, enLigne: e.peers.filter { $0.online }.count + ici,
                     lan: e.peers.filter { $0.path == "lan" }.count,
                     direct: e.peers.filter { $0.path == "direct" }.count,
                     relais: e.peers.filter { $0.path == "relay" }.count)
    }

    /// Tous les appareils à afficher : celui-ci, ses pairs, puis ceux que seul le serveur connaît.
    static func appareils(_ e: EtatReseau) -> [(Appareil, Bool)] {
        var liste: [(Appareil, Bool)] = []
        if let i = e.ici { liste.append((i, true)) }
        liste += e.peers.map { ($0, false) }
        let vus = Set(liste.map { $0.0.name })
        for n in e.nodes where !vus.contains(n.name) {
            var a = Appareil(name: n.name, host: n.host, ips: n.ips, online: n.online, path: n.online ? "idle" : "offline")
            a.addrs = []
            liste.append((a, false))
        }
        return liste
    }

    static func octets(_ n: Double) -> String {
        if n < 1024 { return "\(Int(n)) o" }
        let unites = ["Ko", "Mo", "Go", "To"]
        var x = n / 1024
        var i = 0
        while x >= 1024 && i < unites.count - 1 { x /= 1024; i += 1 }
        let t: String
        if x < 10 {
            t = String(format: "%.1f", x).replacingOccurrences(of: ".0", with: "").replacingOccurrences(of: ".", with: ",")
        } else {
            t = String(Int(x))
        }
        return "\(t) \(unites[i])"
    }

    static func nomValide(_ n: String) -> Bool {
        return n.range(of: "^[a-z0-9][a-z0-9-]{0,62}$", options: .regularExpression) != nil
    }

    static func ligneLinux(_ lignes: [String]) -> String {
        return "sudo sh -c '\(lignes.joined(separator: " && "))'"
    }
}
