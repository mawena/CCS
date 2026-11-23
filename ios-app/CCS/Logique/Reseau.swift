import Foundation

/// Calculs de l'onglet Réseau, sans interface (testés à part). Mêmes règles que le web et Android.
enum Reseau {
    enum Chemin: String {
        case ici, lan, direct, relais, veille, horsLigne
        /// Machine de calcul hors du réseau maillé, joignable seulement par le relais Ricochet.
        case ricochet

        static func de(_ path: String) -> Chemin {
            switch path {
            case "self": return .ici
            case "lan": return .lan
            case "direct": return .direct
            case "relay": return .relais
            case "offline": return .horsLigne
            case "ricochet": return .ricochet
            default: return .veille
            }
        }

        var libelle: String {
            switch self {
            case .ici: return "Serveur CCS"
            case .lan: return "Réseau local"
            case .direct: return "Direct par internet"
            case .relais: return "Relais du VPS"
            case .veille: return "En veille"
            case .horsLigne: return "Hors ligne"
            case .ricochet: return "Relais Ricochet (secours)"
            }
        }

        var icone: String {
            switch self {
            case .ici: return "checkmark.circle.fill"
            case .lan: return "house.fill"
            case .direct: return "bolt.fill"
            case .relais: return "arrow.triangle.swap"
            case .veille, .horsLigne: return "waveform.path.ecg"
            case .ricochet: return "lifepreserver"
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

    // MARK: calcul réparti (machines.list) dans les fiches

    /// La machine de calcul d'une fiche du réseau : ce serveur pour sa propre fiche, sinon par
    /// l'adresse du réseau maillé, puis par le nom (`reseau` des réglages, identifiant, nom d'hôte)
    /// comparé sans casse au nom ou à l'hôte de l'appareil (`matchMachine` du web).
    static func machine(pour a: Appareil, ici: Bool, parmi machines: [Machine]) -> Machine? {
        if ici { return machines.first { $0.local } }
        let cles = Set([a.name, a.host].filter { !$0.isEmpty }.map { $0.lowercased() })
        return machines.first { m in
            if m.local { return false }
            if let ip = m.meshIp, !ip.isEmpty, a.ips.contains(ip) { return true }
            return [m.mesh, m.id, m.host].contains { k in
                guard let k = k, !k.isEmpty else { return false }
                return cles.contains(k.lowercased())
            }
        }
    }

    /// Une fiche de l'onglet : un appareil (ou une machine joignable seulement par Ricochet) et
    /// sa machine de calcul éventuelle.
    struct Fiche: Identifiable {
        let appareil: Appareil
        let ici: Bool
        let machine: Machine?
        /// Machine hors du réseau maillé : ni adresse, ni ping, ni renommer, ni retirer.
        let ricochet: Bool

        var id: String { return ricochet ? "ricochet:" + (machine?.id ?? appareil.name) : appareil.name }
    }

    /// Les appareils du réseau, chacun avec sa machine de calcul, puis une fiche pour chaque
    /// machine non rattachée (hors ce serveur), marquée « Par Ricochet ».
    static func fiches(_ e: EtatReseau, machines: [Machine]) -> [Fiche] {
        var utilisees = Set<String>()
        var liste: [Fiche] = appareils(e).map { paire in
            let m = machine(pour: paire.0, ici: paire.1, parmi: machines)
            if let m = m { utilisees.insert(m.id) }
            return Fiche(appareil: paire.0, ici: paire.1, machine: m, ricochet: false)
        }
        for m in machines where !m.local && !utilisees.contains(m.id) {
            let a = Appareil(name: m.nom, host: m.id, online: m.online, path: m.online ? "ricochet" : "offline")
            liste.append(Fiche(appareil: a, ici: false, machine: m, ricochet: true))
        }
        return liste
    }

    /// Une barre du bloc « calcul » : « Charge » ou « Mémoire ».
    struct Barre: Equatable {
        let libelle: String
        /// Remplissage, entre 0 et 1.
        let part: Double
        let valeur: String
        /// 90 % ou plus : affichée en rouge.
        var chaude: Bool { return part >= 0.9 }
    }

    private static func nombre(_ x: Double, _ chiffres: Int) -> String {
        let f = NumberFormatter()
        f.locale = Locale(identifier: "fr_FR")
        f.numberStyle = .decimal
        f.usesGroupingSeparator = false
        f.minimumFractionDigits = chiffres
        f.maximumFractionDigits = chiffres
        return f.string(from: NSNumber(value: x)) ?? String(x)
    }

    /// Charge par cœur et mémoire, seulement pour une machine en ligne qui les publie.
    static func barres(_ m: Machine) -> [Barre] {
        guard m.online else { return [] }
        var b: [Barre] = []
        if m.cores > 0 {
            let parCoeur = m.load / Double(m.cores)
            b.append(Barre(libelle: "Charge", part: min(1, max(0, parCoeur)), valeur: "\(nombre(parCoeur, 2))/cœur"))
        }
        if let total = m.memTotal, total > 0 {
            let used = m.memUsed ?? 0
            let go = 1_073_741_824.0
            b.append(Barre(libelle: "Mémoire", part: min(1, max(0, used / total)),
                           valeur: "\(nombre(used / go, 1))/\(nombre(total / go, 0)) Go"))
        }
        return b
    }

    /// Ni réseau maillé ni tunnel SSH Ricochet : la machine ne peut pas recevoir de travaux.
    static func injoignable(_ m: Machine) -> Bool {
        return !m.local && !m.tunnel && (m.meshIp ?? "").isEmpty
    }

    /// « PC Linux » de l'ajout d'appareil par un lien Ricochet (`machines.add`) : il faut le relais,
    /// son jeton et le jeton opérateur. Sinon, la clé jetable du réseau maillé.
    static func ajoutParRicochet(_ r: ReglagesRelais?) -> Bool {
        guard let r = r else { return false }
        return !r.relais.isEmpty && r.jetonDefini && r.operateurDefini
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
