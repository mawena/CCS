import Foundation

/// Un appareil annoncé au pont (`audio.list` : `devices`) : sortie s'il sait jouer, source s'il sait capter.
struct AppareilSon: LisibleJSON, Hashable, Identifiable {
    var device = ""
    var label = ""
    var ip = ""
    var port = Rtp.portParDefaut
    var play = false
    var capture = false
    /// linux | android | ios | web | autre
    var system = ""
    /// Secondes depuis sa dernière annonce.
    var age: Double = 0
    /// Lecteurs MPRIS publiés par l'agent `ccs audio` d'un PC Linux ; nil : il n'en publie pas.
    var players: [LecteurSon]? = nil

    var id: String { return device }
    var nom: String { return label.isEmpty ? device : label }

    init(device: String, label: String = "", ip: String = "", play: Bool = false, capture: Bool = false, system: String = "") {
        self.device = device; self.label = label; self.ip = ip; self.play = play; self.capture = capture; self.system = system
    }

    init(json j: JSON) {
        device = j.texte("device"); label = j.texte("label"); ip = j.texte("ip")
        port = j.entier("port", Rtp.portParDefaut); play = j.bool("play"); capture = j.bool("capture")
        system = j.texte("system"); age = j.double("age")
        players = j["players"]?.tableau.map { $0.map { LecteurSon(json: $0) } }
    }
}

/// Un lecteur MPRIS d'un PC (VLC, Firefox…), piloté par `audio.control` (`docs/audio.md`).
struct LecteurSon: LisibleJSON, Hashable, Identifiable {
    var id = ""
    var name = ""
    /// Playing | Paused | Stopped
    var status = "Stopped"
    var title = ""
    var artist = ""
    /// 0-100 ; nil : le lecteur ne donne pas son volume.
    var volume: Double? = nil
    var canPrev = true
    var canNext = true
    var canPlay = true
    var canPause = true
    var canSeek = false

    var joue: Bool { return status == "Playing" }
    var morceau: String { return [title, artist].filter { !$0.isEmpty }.joined(separator: " — ") }

    init(id: String, name: String = "", status: String = "Stopped") {
        self.id = id; self.name = name; self.status = status
    }

    init(json j: JSON) {
        id = j.texte("id"); name = j.texte("name"); status = j.texte("status")
        title = j.texte("title"); artist = j.texte("artist"); volume = j.doubleOuNul("volume")
        canPrev = j.bool("can_prev", true); canNext = j.bool("can_next", true)
        canPlay = j.bool("can_play", true); canPause = j.bool("can_pause", true); canSeek = j.bool("can_seek")
    }
}

/// Un flux en cours (`audio.list` : `streams`).
struct FluxSon: LisibleJSON, Hashable, Identifiable {
    var stream = ""
    var source = ""
    var target = ""
    var started: Double = 0

    var id: String { return stream }

    init(stream: String, source: String, target: String) {
        self.stream = stream; self.source = source; self.target = target
    }

    init(json j: JSON) {
        stream = j.texte("stream"); source = j.texte("source"); target = j.texte("target"); started = j.double("started")
    }
}

/// Réponse de `audio.list`.
struct ListeSon: LisibleJSON {
    var devices: [AppareilSon] = []
    var streams: [FluxSon] = []

    init(devices: [AppareilSon] = [], streams: [FluxSon] = []) { self.devices = devices; self.streams = streams }

    init(json j: JSON) {
        devices = j.liste("devices").map { AppareilSon(json: $0) }
        streams = j.liste("streams").map { FluxSon(json: $0) }
    }

    var sorties: [AppareilSon] { return devices.filter { $0.play } }
    var sources: [AppareilSon] { return devices.filter { $0.capture } }
    /// Appareils qui publient leurs lecteurs (PC Linux dont l'agent tourne).
    var avecLecteurs: [AppareilSon] { return devices.filter { $0.players != nil } }

    func nom(_ device: String) -> String {
        return devices.first { $0.device == device }?.nom ?? device
    }
}

/// Événement poussé `audio` (`docs/audio.md` §3).
enum EvenementSon: Equatable {
    /// Cet appareil (`device`) doit écouter sur `port` le flux venu de `de`.
    case recevoir(device: String, flux: String, de: String, deNom: String, port: Int)
    /// Cet appareil (`device`) doit émettre son son vers `ip:port`.
    case emettre(device: String, flux: String, vers: String, versNom: String, ip: String, port: Int)
    /// Le flux s'arrête pour `appareils` (source et cible).
    case arret(flux: String, appareils: [String], raison: String)

    static func lire(_ j: JSON) -> EvenementSon? {
        let flux = j.texte("stream")
        switch j.texte("action") {
        case "receive":
            let de = j.texte("from").isEmpty ? j.texte("source") : j.texte("from")
            return .recevoir(device: j.texte("device"), flux: flux, de: de,
                             deNom: j.texte("from_label").isEmpty ? de : j.texte("from_label"),
                             port: j.entier("port", Rtp.portParDefaut))
        case "emit":
            let vers = j.texte("to").isEmpty ? j.texte("target") : j.texte("to")
            guard !j.texte("ip").isEmpty else { return nil }
            return .emettre(device: j.texte("device"), flux: flux, vers: vers,
                            versNom: j.texte("to_label").isEmpty ? vers : j.texte("to_label"),
                            ip: j.texte("ip"), port: j.entier("port", Rtp.portParDefaut))
        case "stop":
            var a = j.listeTextes("devices")
            if a.isEmpty { a = [j.texte("source"), j.texte("target")].filter { !$0.isEmpty } }
            return .arret(flux: flux, appareils: a, raison: j.texte("reason"))
        default:
            return nil
        }
    }

    /// Chaque appareil ne garde que les événements qui le nomment.
    func concerne(_ moi: String) -> Bool {
        guard !moi.isEmpty else { return false }
        switch self {
        case .recevoir(let d, _, _, _, _), .emettre(let d, _, _, _, _, _): return d == moi
        case .arret(_, let a, _): return a.contains(moi)
        }
    }
}
