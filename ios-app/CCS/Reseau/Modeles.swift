import Foundation

/// Modèle lu depuis une valeur JSON, avec un défaut pour chaque champ absent ou mal typé.
protocol LisibleJSON {
    init(json: JSON)
}

/// Réponse vide ou sans intérêt (`chat.close`, `pause.set`…).
struct SansReponse: LisibleJSON {
    init(json: JSON) {}
}

struct Sante: LisibleJSON {
    var ok = false
    var version = ""
    init(json j: JSON) {
        ok = j.bool("ok")
        version = j.texte("version")
    }
}

struct InfoPortier: LisibleJSON, Equatable {
    var actif = false
    var connexion = ""
    init(json j: JSON) {
        actif = j.bool("actif")
        connexion = j.texte("connexion")
    }
}

struct InfoSession: LisibleJSON {
    var user = ""
    var portier = false
    init(json j: JSON) {
        user = j.texte("user")
        portier = j.bool("portier")
    }
}

/**
 * Réponse de `/api/pair` et `/api/enroll`. `status` : `ok` (avec `token`), `code` (code TOTP
 * demandé), `enroll` (première connexion : `secret` à ajouter dans l'appli d'authentification puis
 * premier code), `blocked` (`retry_after` secondes), `refused`, `error`.
 */
struct ReponseConnexion: LisibleJSON, Equatable {
    var status = "error"
    var user: String?
    var token: String?
    var pending: String?
    var secret: String?
    var retryAfter: Double?
    var message: String?

    init(json j: JSON) {
        status = j.texteOuNul("status") ?? "error"
        user = j.texteOuNul("user")
        token = j.texteOuNul("token")
        pending = j.texteOuNul("pending")
        secret = j.texteOuNul("secret")
        retryAfter = j.doubleOuNul("retry_after")
        message = j.texteOuNul("message")
    }

    init(status: String, message: String?) {
        self.status = status
        self.message = message
    }
}

// MARK: comptes (accueil)

struct Jauge: LisibleJSON, Equatable {
    var kind: String?
    var label = ""
    var percent = 0.0
    var reset = ""
    init(json j: JSON) {
        kind = j.texteOuNul("kind")
        label = j.texte("label")
        percent = j.double("percent")
        reset = j.texte("reset")
    }
}

struct StatutCarte: LisibleJSON, Equatable {
    var text = ""
    var kind = ""
    init(json j: JSON) {
        text = j.texte("text")
        kind = j.texte("kind")
    }
}

/// Une carte de compte de `accounts.cards` (voir `_card` dans `bridge_admin.py`).
struct Carte: LisibleJSON, Identifiable, Equatable {
    var name = ""
    var plan = ""
    var email = ""
    var org = ""
    var active = false
    var color: String?
    var main: [Jauge] = []
    var others: [Jauge] = []
    var status: StatutCarte?
    var erreur: String?
    var details: [String] = []
    var donnees = false

    var id: String { return name }

    init(json j: JSON) {
        name = j.texte("name")
        plan = j.texte("plan")
        email = j.texte("email")
        org = j.texte("org")
        active = j.bool("active")
        color = j.texteOuNul("color")
        main = j.liste("main").map { Jauge(json: $0) }
        others = j.liste("others").map { Jauge(json: $0) }
        if let s = j["status"], case .objet = s { status = StatutCarte(json: s) }
        erreur = j.texteOuNul("error_raw")
        details = j.listeTextes("details")
        donnees = j.bool("has_data")
    }
}

struct Cartes: LisibleJSON {
    var cards: [Carte] = []
    var best: JSON = .nul
    var bascule: JSON = .nul
    var misAJour: Double?
    var chatsEnCours = 0

    init(json j: JSON) {
        cards = j.liste("cards").map { Carte(json: $0) }
        best = j["best"] ?? .nul
        bascule = j["auto_switch"] ?? .nul
        misAJour = j.doubleOuNul("updated_at")
        chatsEnCours = j.entier("running_chats")
    }
}

/// Texte d'un champ d'un objet libre (`best`, `auto_switch`) : `chemin` mène à une chaîne non vide.
func texteDans(_ j: JSON, _ chemin: String...) -> String? {
    var e: JSON? = j
    for c in chemin { e = e?[c] }
    guard let s = e?.chaine, !s.trimmingCharacters(in: .whitespaces).isEmpty else { return nil }
    return s
}

/// Pause de la bascule et de l'orchestrateur (`accounts.state`).
struct Pause: LisibleJSON, Equatable {
    var until: String?
    var label = ""
    init(json j: JSON) {
        until = j.texteOuNul("until")
        label = j.texte("label")
    }
}

/// Réponse de `accounts.state` (`accounts_state` dans `bridge.py`) ; `pause_choices` : paires `[choix, libellé]`.
struct EtatComptes: LisibleJSON {
    var user = ""
    var home = ""
    var active: String?
    var colors: [String: String] = [:]
    var pause: Pause?
    var choix: [(valeur: String, libelle: String)] = []

    init(json j: JSON) {
        user = j.texte("user")
        home = j.texte("home")
        active = j.texteOuNul("active")
        for (k, v) in j["colors"]?.objet ?? [:] {
            if let s = v.chaine { colors[k] = s }
        }
        if let p = j["pause"], case .objet = p { pause = Pause(json: p) }
        choix = j.liste("pause_choices").compactMap { c in
            guard let t = c.tableau, t.count >= 2, let v = t[0].contenu, let l = t[1].contenu else { return nil }
            return (valeur: v, libelle: l)
        }
    }
}

/// Une vérification de `doctor.run` : `statut` vaut `erreur`, `avertissement` ou `ok`.
struct Verification: LisibleJSON, Identifiable {
    var nom = ""
    var statut = ""
    var detail = ""
    var commande: String?
    var id: String { return nom + "|" + detail }
    init(json j: JSON) {
        nom = j.texte("nom")
        statut = j.texte("statut")
        detail = j.texte("detail")
        commande = j.texteOuNul("commande")
    }
}

struct Bilan: LisibleJSON {
    var checks: [Verification] = []
    var errors = 0
    var warnings = 0
    var summary = ""
    init(json j: JSON) {
        checks = j.liste("checks").map { Verification(json: $0) }
        errors = j.entier("errors")
        warnings = j.entier("warnings")
        summary = j.texte("summary")
    }
}

/// `analysis.report` : jetons pondérés par projet, modèle, compte et heure.
struct Rapport: LisibleJSON {
    var total = 0.0
    var parProjet: [String: Double] = [:]
    var parModele: [String: Double] = [:]
    var parCompte: [String: Double] = [:]
    var parHeure: [Double] = []
    var days = 7
    var responses = 0

    init(json j: JSON) {
        func table(_ cle: String) -> [String: Double] {
            var t: [String: Double] = [:]
            for (k, v) in j[cle]?.objet ?? [:] { t[k] = v.nombre ?? 0 }
            return t
        }
        total = j.double("total")
        parProjet = table("by_project")
        parModele = table("by_model")
        parCompte = table("by_account")
        parHeure = j.liste("by_hour").map { $0.nombre ?? 0 }
        days = j.entier("days", 7)
        responses = j.entier("responses")
    }
}

/// Réponse de `accounts.switch` (`ok` faux si `ccs switch` a échoué).
struct ResultatBascule: LisibleJSON {
    var ok = false
    init(json j: JSON) { ok = j.bool("ok") }
}
