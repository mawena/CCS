import Foundation

/// Une machine de `machines.list` (toujours traité par le serveur, jamais relayé).
struct Machine: LisibleJSON, Codable, Equatable, Identifiable {
    var id = ""
    var name = ""
    var online = false
    /// Le serveur lui-même : jamais proposé (c'est « Ce serveur »).
    var local = false
    var cores = 0
    var load = 0.0
    var tunnel = false
    /// Page Machines : outils inventoriés, places (travaux à la fois), travaux actifs.
    var tools: [String] = []
    var limit = 2
    var running = 0
    var waiting = 0

    init(id: String = "", name: String = "", online: Bool = false, local: Bool = false, cores: Int = 0, load: Double = 0, tunnel: Bool = false) {
        self.id = id
        self.name = name
        self.online = online
        self.local = local
        self.cores = cores
        self.load = load
        self.tunnel = tunnel
    }

    init(json j: JSON) {
        id = j.texte("id")
        name = j.texte("name")
        online = j.bool("online")
        local = j.bool("local")
        cores = j.entier("cores")
        load = j.double("load")
        tunnel = j.bool("tunnel")
        tools = j.listeTextes("tools")
        limit = j.entier("limit", 2)
        running = j.entier("running")
        waiting = j.entier("waiting")
    }

    /// « Places : 1/2 · 3 en attente » (page Machines du web).
    var places: String {
        let base = "Places : \(running)/\(limit)"
        return waiting > 0 ? base + " · \(waiting) en attente" : base
    }

    var nom: String { return name.trimmingCharacters(in: .whitespaces).isEmpty ? id : name }

    /// Joignable par le tunnel : on peut la piloter.
    var choisissable: Bool { return online && tunnel }

    /// « en ligne · charge 1.2 sur 8 cœurs », « hors ligne »… comme `describe` de `machines.js`.
    var description: String {
        if !online { return "hors ligne" }
        var parts = ["en ligne"]
        if cores > 0 { parts.append("charge \(String(format: "%.1f", locale: Locale(identifier: "en_US_POSIX"), load)) sur \(cores) cœurs") }
        if !tunnel { parts.append("tunnel SSH non activé") }
        return parts.joined(separator: " · ")
    }
}

struct ListeMachines: LisibleJSON {
    var machines: [Machine] = []
    var message: String? = nil
    /// Faux si le calcul réparti n'est pas réglé sur le serveur (relais Ricochet).
    var configured = true
    init(json j: JSON) {
        configured = j.bool("configured", true)
        machines = j.liste("machines").map { Machine(json: $0) }
        message = j.texteOuNul("message")
    }

    /// Machines autres que ce serveur.
    var autres: [Machine] { return machines.filter { !$0.local } }
}

/// Un travail distant (`machines.jobs`, `distant_jobs.py`).
struct TravailDistant: LisibleJSON, Identifiable, Equatable {
    var id = ""
    var text = ""
    var cwd = ""
    var machine: String? = nil
    var state = ""
    var code: Int? = nil
    var created: Double? = nil
    var started: Double? = nil
    var ended: Double? = nil
    var why = ""

    init(json j: JSON) {
        id = j.texte("id")
        text = j.texte("text")
        cwd = j.texte("cwd")
        machine = j.texteOuNul("machine").flatMap { $0.isEmpty ? nil : $0 }
        state = j.texte("state")
        code = j.entierOuNul("code")
        created = j.doubleOuNul("created")
        started = j.doubleOuNul("started")
        ended = j.doubleOuNul("ended")
        why = j.texte("why")
    }
}

struct ListeTravaux: LisibleJSON {
    var jobs: [TravailDistant] = []
    init(json j: JSON) { jobs = j.liste("jobs").map { TravailDistant(json: $0) } }
}

/// Réglages du relais Ricochet (`machines.settings`) ; le jeton n'est jamais renvoyé.
struct ReglagesRelais: LisibleJSON {
    var relais = ""
    var jetonDefini = false
    var chemin = ""
    var limiteDefaut = 2
    init(json j: JSON) {
        relais = j.texte("relais")
        jetonDefini = j.bool("jeton_defini")
        chemin = j.texte("chemin")
        limiteDefaut = j.entier("limite_defaut", 2)
    }
}
