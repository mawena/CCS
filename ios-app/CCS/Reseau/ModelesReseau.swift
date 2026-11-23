import Foundation

/// Un appareil du réseau maillé (`network.status` : `self`, `peers`).
struct Appareil: LisibleJSON, Hashable, Identifiable {
    var name = ""
    var host = ""
    var os = ""
    var ips: [String] = []
    var online = false
    /// self | lan | direct | relay | idle | offline
    var path = "idle"
    var endpoint = ""
    var relay = ""
    var addrs: [String] = []
    var rx: Double = 0
    var tx: Double = 0

    var id: String { return name }

    init(name: String = "", host: String = "", os: String = "", ips: [String] = [], online: Bool = false, path: String = "idle") {
        self.name = name; self.host = host; self.os = os; self.ips = ips; self.online = online; self.path = path
    }

    init(json j: JSON) {
        name = j.texte("name"); host = j.texte("host"); os = j.texte("os")
        ips = j.listeTextes("ips"); online = j.bool("online"); path = j.texteOuNul("path") ?? "idle"
        endpoint = j.texte("endpoint"); relay = j.texte("relay"); addrs = j.listeTextes("addrs")
        rx = j.double("rx"); tx = j.double("tx")
    }
}

/// Appareil connu du serveur Headscale (`nodes`).
struct NoeudServeur: LisibleJSON {
    var name = ""
    var host = ""
    var ips: [String] = []
    var online = false
    init(name: String, online: Bool = false) { self.name = name; self.online = online }
    init(json j: JSON) { name = j.texte("name"); host = j.texte("host"); ips = j.listeTextes("ips"); online = j.bool("online") }
}

/// Réponse de `network.status`.
struct EtatReseau: LisibleJSON {
    var url = ""
    var domain = ""
    var installed = false
    var server = false
    var state = ""
    var ici: Appareil? = nil
    var peers: [Appareil] = []
    var nodes: [NoeudServeur] = []
    var error: String? = nil

    init(ici: Appareil? = nil, peers: [Appareil] = [], nodes: [NoeudServeur] = []) {
        self.ici = ici; self.peers = peers; self.nodes = nodes
    }

    init(json j: JSON) {
        url = j.texte("url"); domain = j.texte("domain"); installed = j.bool("installed"); server = j.bool("server")
        state = j.texte("state")
        if let s = j["self"], s.objet != nil { ici = Appareil(json: s) }
        peers = j.liste("peers").map { Appareil(json: $0) }
        nodes = j.liste("nodes").map { NoeudServeur(json: $0) }
        error = j.texteOuNul("error")
    }
}

/// Réponse de `network.ping`.
struct PingReseau: LisibleJSON {
    var ok = false
    var path = ""
    var via = ""
    var ms: Double = 0
    var error: String? = nil
    init(erreur: String) { ok = false; error = erreur }
    init(json j: JSON) { ok = j.bool("ok"); path = j.texte("path"); via = j.texte("via"); ms = j.double("ms"); error = j.texteOuNul("error") }
}

struct CleReseau: LisibleJSON {
    var key = ""
    var linux: [String] = []
    init(json j: JSON) { key = j.texte("key"); linux = j.listeTextes("linux") }
}
