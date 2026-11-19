import Foundation

/// Un projet de `projects.list` (`ProjectEntry` de `session_hub.py`) ; `cwd` nul : « Tous ».
struct Projet: LisibleJSON, Identifiable, Equatable {
    var cwd: String?
    var name = ""
    var conversations = 0
    var total = 0
    var open = 0
    var waiting = 0
    var last = 0.0
    var exists = true
    var deplaceVers: String?
    var profile: String?

    var id: String { return cwd ?? "" }

    init(json j: JSON) {
        cwd = j.texteOuNul("cwd")
        name = j.texte("name")
        conversations = j.entier("conversations")
        total = j.entier("total")
        open = j.entier("open")
        waiting = j.entier("waiting")
        last = j.double("last")
        exists = j.bool("exists", true)
        deplaceVers = j.texteOuNul("moved_to")
        profile = j.texteOuNul("profile")
    }
}

/// Une conversation de l'historique (`Conversation` de `conversations.py`).
struct Conversation: LisibleJSON, Identifiable, Equatable, Hashable {
    var sessionId = ""
    var path = ""
    var cwd = ""
    var title = ""
    var premiereDemande = ""
    var derniereDemande = ""
    var prompts = 0
    var debut: Double?
    var misAJour = 0.0
    var origin = ""
    var branche = ""
    var size = 0
    var dossierExiste = true
    var archived = false

    var id: String { return path.isEmpty ? sessionId : path }

    var titre: String {
        if !title.trimmingCharacters(in: .whitespaces).isEmpty { return title }
        if !premiereDemande.trimmingCharacters(in: .whitespaces).isEmpty { return premiereDemande }
        return "(sans titre)"
    }

    init(json j: JSON) {
        sessionId = j.texte("session_id")
        path = j.texte("path")
        cwd = j.texte("cwd")
        title = j.texte("title")
        premiereDemande = j.texte("first_prompt")
        derniereDemande = j.texte("last_prompt")
        prompts = j.entier("prompts")
        debut = j.doubleOuNul("started_at")
        misAJour = j.double("updated_at")
        origin = j.texte("origin")
        branche = j.texte("git_branch")
        size = j.entier("size")
        dossierExiste = j.bool("folder_exists", true)
        archived = j.bool("archived")
    }
}

struct ListeProjets: LisibleJSON {
    var entries: [Projet] = []
    var conversations: [Conversation] = []
    var total = 0
    var projects = 0

    /// Projets réels (sans l'entrée « Tous les projets »).
    var projets: [Projet] { return entries.filter { !($0.cwd ?? "").isEmpty } }

    init(json j: JSON) {
        entries = j.liste("entries").map { Projet(json: $0) }
        conversations = j.liste("conversations").map { Conversation(json: $0) }
        total = j.entier("total")
        projects = j.entier("projects")
    }
}

/// Options d'un chat (`ChatOptions` de `chat_options.py`).
struct OptionsChat: LisibleJSON, Equatable {
    var model: String?
    var effort: String?
    var ultracode = false
    var rights = "manual"

    init() {}

    init(json j: JSON) {
        model = j.texteOuNul("model")
        effort = j.texteOuNul("effort")
        ultracode = j.bool("ultracode")
        rights = j.texteOuNul("rights") ?? "manual"
    }

    var enJSON: JSON {
        return .objet(["model": .de(model), "effort": .de(effort), "ultracode": .de(ultracode), "rights": .chaine(rights)])
    }
}

/// Un chat ouvert dans le pont (`chat.list`) ou la réponse de `chat.open`.
struct ChatOuvert: LisibleJSON, Identifiable, Equatable {
    var chatId = ""
    var cwd = ""
    var state = ""
    var seq = 0
    var options: OptionsChat?
    var sessionId: String?
    var path: String?
    var historiqueAvant: Double?

    var id: String { return chatId }

    init(json j: JSON) {
        chatId = j.texte("chat_id")
        cwd = j.texte("cwd")
        state = j.texte("state")
        seq = j.entier("seq")
        if let o = j["options"], case .objet = o { options = OptionsChat(json: o) }
        sessionId = j.texteOuNul("session_id")
        path = j.texteOuNul("path")
        historiqueAvant = j.doubleOuNul("history_before")
    }
}

struct ListeChats: LisibleJSON {
    var chats: [ChatOuvert] = []
    init(json j: JSON) { chats = j.liste("chats").map { ChatOuvert(json: $0) } }
}

struct Cout: LisibleJSON {
    var short = ""
    var text = ""
    var dollars = 0.0
    init(json j: JSON) {
        short = j.texte("short")
        text = j.texte("text")
        dollars = j.double("dollars")
    }
}

struct MiseCorbeille: LisibleJSON {
    var tid = ""
    init(json j: JSON) { tid = j.texte("tid") }
}

struct ElementCorbeille: LisibleJSON, Identifiable {
    var tid = ""
    var sessionId: String?
    var cwd: String?
    var title: String?
    var supprimeLe: Double?
    var id: String { return tid }
    init(json j: JSON) {
        tid = j.texte("tid")
        sessionId = j.texteOuNul("id")
        cwd = j.texteOuNul("cwd")
        title = j.texteOuNul("title")
        supprimeLe = j.doubleOuNul("trashed_at")
    }
}

struct Corbeille: LisibleJSON {
    var items: [ElementCorbeille] = []
    var days = 30
    init(json j: JSON) {
        items = j.liste("items").map { ElementCorbeille(json: $0) }
        days = j.entier("days", 30)
    }
}

struct ProfilCompte: LisibleJSON, Equatable {
    var name = ""
    var email = ""
    var active = false
    init(json j: JSON) {
        name = j.texte("name")
        email = j.texte("email")
        active = j.bool("active")
    }
}

/// `projects.account` : comptes, compte actif et compte conseillé pour un dossier.
struct CompteProjet: LisibleJSON, Equatable {
    var profiles: [ProfilCompte] = []
    var active: String?
    var preferred: String?
    var hint = ""
    var paused = false
    init(json j: JSON) {
        profiles = j.liste("profiles").map { ProfilCompte(json: $0) }
        active = j.texteOuNul("active")
        preferred = j.texteOuNul("preferred")
        hint = j.texte("hint")
        paused = j.bool("paused")
    }
}

struct Depots: LisibleJSON {
    var dossiers: [String] = []
    var truncated = false
    init(json j: JSON) {
        dossiers = j.liste("folders").map { $0.texte("path") }.filter { !$0.isEmpty }
        truncated = j.bool("truncated")
    }
}

struct ProjetAjoute: LisibleJSON {
    var cwd = ""
    init(json j: JSON) { cwd = j.texte("cwd") }
}

struct OutilHistorique: Equatable {
    var name = ""
    var target = ""
    var result: String?
    var toolId = ""
    var erreur = false

    init(name: String, target: String, result: String? = nil, toolId: String, erreur: Bool = false) {
        self.name = name
        self.target = target
        self.result = result
        self.toolId = toolId
        self.erreur = erreur
    }

    init(json j: JSON) {
        name = j.texte("name")
        target = j.texte("target")
        result = j.texteOuNul("result")
        toolId = j.texte("tool_id")
        erreur = j.bool("is_error")
    }
}

/// Un message de `conversation.messages` (`Message` de `preview.py`).
struct MessageHistorique: Equatable {
    var role = ""
    var text = ""
    var ts: Double?
    var tool: OutilHistorique?
    var msgId = ""
    var uuid = ""

    init(role: String, text: String, tool: OutilHistorique? = nil, msgId: String = "", uuid: String = "") {
        self.role = role
        self.text = text
        self.tool = tool
        self.msgId = msgId
        self.uuid = uuid
    }

    init(json j: JSON) {
        role = j.texte("role")
        text = j.texte("text")
        ts = j.doubleOuNul("ts")
        if let t = j["tool"], case .objet = t { tool = OutilHistorique(json: t) }
        msgId = j.texte("msg_id")
        uuid = j.texte("uuid")
    }
}

struct Messages: LisibleJSON {
    var messages: [MessageHistorique] = []
    init(json j: JSON) { messages = j.liste("messages").map { MessageHistorique(json: $0) } }
}
