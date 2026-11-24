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
    /// Bloc « calcul » de l'onglet Réseau : outils inventoriés, places (travaux à la fois), travaux actifs.
    var tools: [String] = []
    var limit = 2
    var running = 0
    var waiting = 0
    /// Mémoire utilisée et totale, en octets (absentes des anciens serveurs : optionnelles).
    var memUsed: Double? = nil
    var memTotal: Double? = nil
    /// Rattachement à une fiche du réseau maillé : nom d'hôte, nom `reseau` des réglages, adresse
    /// dans le réseau maillé. Chaînes éventuellement vides ou absentes.
    var host: String? = nil
    var mesh: String? = nil
    var meshIp: String? = nil

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
        memUsed = j.doubleOuNul("mem_used")
        memTotal = j.doubleOuNul("mem_total")
        host = j.texteOuNul("host")
        mesh = j.texteOuNul("mesh")
        meshIp = j.texteOuNul("mesh_ip")
    }

    /// « Places : 1/2 · 3 en attente » (bloc « calcul » du web).
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
    /// Jeton opérateur de Ricochet enregistré : « Ajouter un PC » par un lien Ricochet possible.
    var operateurDefini = false
    init(relais: String = "", jetonDefini: Bool = false, operateurDefini: Bool = false) {
        self.relais = relais
        self.jetonDefini = jetonDefini
        self.operateurDefini = operateurDefini
    }
    init(json j: JSON) {
        relais = j.texte("relay")
        jetonDefini = j.bool("token_set")
        chemin = j.texte("path")
        limiteDefaut = j.entier("default_limit", 2)
        operateurDefini = j.bool("operator_set")
    }
}

/// Réponse de `machines.add` : la commande à coller sur le PC (lien Ricochet à usage unique).
struct AjoutMachine: LisibleJSON {
    var id = ""
    var command = ""
    /// Vrai si la commande inscrit aussi le PC au réseau maillé.
    var mesh = false
    /// Vrai si la commande installe aussi CCS et Claude Code.
    var full = false
    var expiresS = 900
    init(json j: JSON) {
        id = j.texte("id")
        command = j.texte("command")
        mesh = j.bool("mesh")
        full = j.bool("full")
        expiresS = j.entier("expires_s", 900)
    }
}
