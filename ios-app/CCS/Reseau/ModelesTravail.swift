import Foundation

/**
 * Réponses des RPC de la feuille de route (`roadmap.*`), des tâches de fond (`tasks.*`), du
 * travail du chat (`work.changes`, `work.rewind_*`, `work.saved.*`), des réglages, du téléphone
 * (`phone.*`) et de la route `/api/tokens`.
 */

struct TacheFeuille: LisibleJSON, Equatable {
    var text = ""
    var done = false
    var line = 0
    var depth = 0
    init(json j: JSON) {
        text = j.texte("text")
        done = j.bool("done")
        line = j.entier("line")
        depth = j.entier("depth")
    }
}

struct PhaseFeuille: LisibleJSON, Equatable {
    var title = ""
    var version: String?
    var tasks: [TacheFeuille] = []
    var line = 0
    init(json j: JSON) {
        title = j.texte("title")
        version = j.texteOuNul("version")
        tasks = j.liste("tasks").map { TacheFeuille(json: $0) }
        line = j.entier("line")
    }
}

/// `roadmap.read` : `path` nul quand le projet n'a pas de ROADMAP.md.
struct FeuilleDeRoute: LisibleJSON, Equatable {
    var path: String?
    var title = ""
    var phases: [PhaseFeuille] = []
    init(json j: JSON) {
        path = j.texteOuNul("path")
        title = j.texte("title")
        phases = j.liste("phases").map { PhaseFeuille(json: $0) }
    }
}

struct ResultatCase: LisibleJSON {
    var changed = true
    init(json j: JSON) { changed = j.bool("changed", true) }
}

struct InvitationTache: LisibleJSON {
    var prompt = ""
    init(json j: JSON) { prompt = j.texte("prompt") }
}

/// Une tâche de fond (`Task` de `tasks.py`).
struct TacheFond: LisibleJSON, Identifiable, Equatable {
    var id = ""
    var message = ""
    var cwd = ""
    var model: String?
    var rights = ""
    var quand = "quota"
    var state = ""
    var created: Double = 0
    var started: Double?
    var finished: Double?
    var sessionId: String?
    var account: String?
    var attempts = 0
    var duration: Double?
    var cost: Double?
    var error: String?
    var note = ""

    init(json j: JSON) {
        id = j.texte("id")
        message = j.texte("message")
        cwd = j.texte("cwd")
        model = j.texteOuNul("model")
        rights = j.texte("rights")
        quand = j.texteOuNul("when") ?? "quota"
        state = j.texte("state")
        created = j.double("created")
        started = j.doubleOuNul("started")
        finished = j.doubleOuNul("finished")
        sessionId = j.texteOuNul("session_id")
        account = j.texteOuNul("account")
        attempts = j.entier("attempts")
        duration = j.doubleOuNul("duration")
        cost = j.doubleOuNul("cost")
        error = j.texteOuNul("error")
        note = j.texte("note")
    }
}

struct ListeTaches: LisibleJSON {
    var tasks: [TacheFond] = []
    init(json j: JSON) { tasks = j.liste("tasks").map { TacheFond(json: $0) } }
}

/// `tasks.log` : la tâche, son résumé et la fin de son journal.
struct JournalTache: LisibleJSON {
    var task = TacheFond(json: .vide)
    var summary = ""
    var lines: [String] = []
    var truncated = false
    init(json j: JSON) {
        task = TacheFond(json: j["task"] ?? .vide)
        summary = j.texte("summary")
        lines = j.listeTextes("lines")
        truncated = j.bool("truncated")
    }
}

/// Un fichier changé pendant la session (`work.changes`) ; `sha256` : son contenu actuel (nul s'il n'existe plus).
struct FichierChange: LisibleJSON, Identifiable, Equatable {
    var path = ""
    var kind = "modified"
    var binary = false
    var diff = ""
    var tropGros = false
    var sha256: String?
    var id: String { return path }
    init(json j: JSON) {
        path = j.texte("path")
        kind = j.texteOuNul("kind") ?? "modified"
        binary = j.bool("binary")
        diff = j.texte("diff")
        tropGros = j.bool("too_big")
        sha256 = j.texteOuNul("sha256")
    }
}

struct PointRetour: LisibleJSON, Identifiable, Equatable {
    var messageId = ""
    var text = ""
    var time: Double?
    var id: String { return messageId }
    init(json j: JSON) {
        messageId = j.texte("message_id")
        text = j.texte("text")
        time = j.doubleOuNul("time")
    }
}

struct Changements: LisibleJSON {
    var unknown = false
    var files: [FichierChange] = []
    var points: [PointRetour] = []
    init(json j: JSON) {
        unknown = j.bool("unknown")
        files = j.liste("files").map { FichierChange(json: $0) }
        points = j.liste("points").map { PointRetour(json: $0) }
    }
}

struct EtapeRetour: LisibleJSON, Equatable {
    var path = ""
    var deleted = false
    var modifieParToi = false
    var sha256: String?
    init(json j: JSON) {
        path = j.texte("path")
        deleted = j.bool("deleted")
        modifieParToi = j.bool("user_edited")
        sha256 = j.texteOuNul("sha256")
    }
}

struct PlanRetour: LisibleJSON {
    var steps: [EtapeRetour] = []
    var skipped: [String] = []
    init(json j: JSON) {
        steps = j.liste("steps").map { EtapeRetour(json: $0) }
        skipped = j.listeTextes("skipped")
    }
}

struct ResultatRetour: LisibleJSON {
    var count = 0
    var skipped: [String] = []
    init(json j: JSON) {
        count = j.entier("count")
        skipped = j.listeTextes("skipped")
    }
}

struct MessageEnregistre: LisibleJSON, Identifiable, Equatable {
    var name = ""
    var text = ""
    var scope = "global"
    var id: String { return scope + ":" + name }
    init(json j: JSON) {
        name = j.texte("name")
        text = j.texte("text")
        scope = j.texteOuNul("scope") ?? "global"
    }
}

struct MessagesEnregistres: LisibleJSON {
    var items: [MessageEnregistre] = []
    init(json j: JSON) { items = j.liste("items").map { MessageEnregistre(json: $0) } }
}

/// `settings.get` : tous les réglages, tels que le pont les garde.
struct Reglages: LisibleJSON {
    var settings: JSON = .vide
    init(json j: JSON) {
        if let s = j["settings"], case .objet = s { settings = s }
    }
}

struct CanalTelephone: LisibleJSON {
    var topic = ""
    init(json j: JSON) { topic = j.texte("topic") }
}

struct EssaiTelephone: LisibleJSON {
    var ok = false
    var message = ""
    init(json j: JSON) {
        ok = j.bool("ok")
        message = j.texte("message")
    }
}

struct QrTelephone: LisibleJSON {
    var url = ""
    var image = ""
    init(json j: JSON) {
        url = j.texte("url")
        image = j.texte("image")
    }
}

/// Accès connecté au compte (`/api/tokens`). `kind` : session, device ou app.
struct Acces: LisibleJSON, Identifiable, Equatable {
    var id = ""
    var kind: String?
    var name = ""
    var created: Double?
    var dernierUsage: Double?
    init(json j: JSON) {
        id = j.texte("id")
        kind = j.texteOuNul("kind")
        name = j.texte("name")
        created = j.doubleOuNul("created")
        dernierUsage = j.doubleOuNul("last_used")
    }
}

struct ListeAcces: LisibleJSON {
    var tokens: [Acces] = []
    init(json j: JSON) { tokens = j.liste("tokens").map { Acces(json: $0) } }
}

// MARK: terminaux (`term.*`)

struct TerminalOuvert: LisibleJSON {
    var termId = ""
    init(json j: JSON) { termId = j.texte("term_id") }
}

struct InfoTerminal: LisibleJSON, Equatable, Identifiable {
    var termId = ""
    var cwd = ""
    var name = "Terminal"
    var id: String { return termId }
    init(json j: JSON) {
        termId = j.texte("term_id")
        cwd = j.texte("cwd")
        let n = j.texte("name")
        name = n.isEmpty ? "Terminal" : n
    }
}

struct ListeTerminaux: LisibleJSON {
    var terms: [InfoTerminal] = []
    init(json j: JSON) { terms = j.liste("terms").map { InfoTerminal(json: $0) } }
}

struct SortieTerminal: LisibleJSON {
    var output = ""
    init(json j: JSON) { output = j.texte("output") }
}
