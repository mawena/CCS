import Foundation

/**
 * Réglages du serveur (`web/settings.js`, `web/pages-phone.js`) : mêmes groupes, mêmes libellés,
 * mêmes bornes. Chaque valeur part seule par `settings.set` ; le pont la valide à son tour.
 */
enum DefReglages {
    enum Genre: Equatable {
        case booleen
        case nombre(min: Double, max: Double, entier: Bool)
        case heure
        case texte
        case choix([Option])
    }

    struct Option: Equatable {
        let valeur: String
        let libelle: String
    }

    struct Def: Equatable {
        let chemin: String
        let libelle: String
        let genre: Genre
        var aide: String = ""
    }

    struct Groupe {
        let titre: String
        let reglages: [Def]
        var texte: String = ""
    }

    private static let b = Genre.booleen
    private static let h = Genre.heure
    private static func n(_ min: Double, _ max: Double, entier: Bool = false) -> Genre { return .nombre(min: min, max: max, entier: entier) }

    static let droits: [Option] = [
        Option(valeur: "manual", libelle: "Manuel"), Option(valeur: "acceptEdits", libelle: "Accepter les modifications"),
        Option(valeur: "plan", libelle: "Plan"), Option(valeur: "auto", libelle: "Auto"),
        Option(valeur: "dontAsk", libelle: "Sans question"), Option(valeur: "bypassPermissions", libelle: "Aucune vérification"),
    ]

    /// Téléphone (ntfy) : en tête, comme sur le web.
    static let telephone = Groupe(
        titre: "Téléphone (notifications ntfy)",
        reglages: [
            Def(chemin: "phone.enabled", libelle: "Envoyer les notifications", genre: b),
            Def(chemin: "phone.server", libelle: "Serveur ntfy", genre: .texte, aide: "https://ntfy.sh par défaut"),
            Def(chemin: "phone.topic", libelle: "Canal secret", genre: .texte,
                aide: "Celui qui le connaît peut lire tes notifications : ne le partage pas."),
            Def(chemin: "phone.events.waiting", libelle: "Une session attend ma réponse", genre: b),
            Def(chemin: "phone.events.task", libelle: "Une tâche se termine", genre: b),
            Def(chemin: "phone.events.switch", libelle: "Bascule de compte", genre: b),
            Def(chemin: "phone.events.exhausted", libelle: "Tous les comptes sont épuisés", genre: b),
            Def(chemin: "phone.show_content", libelle: "Montrer la commande", genre: b,
                aide: "La notification d'autorisation affiche la commande exacte (sinon : le type et le projet seulement)."),
        ],
        texte: "Reçois sur ton téléphone « attend ta réponse », tâche finie, bascule. Installe l'application ntfy, puis abonne-toi au lien."
    )

    static let groupes: [Groupe] = [
        Groupe(titre: "Bascule automatique", reglages: [
            Def(chemin: "auto_switch.enabled", libelle: "Basculer avant la limite", genre: b),
            Def(chemin: "auto_switch.threshold", libelle: "Seuil de bascule (%)", genre: n(1, 100)),
            Def(chemin: "auto_switch.target_max_session", libelle: "Session maximale du compte visé (%)", genre: n(0, 100)),
            Def(chemin: "auto_switch.target_max_weekly", libelle: "Semaine maximale du compte visé (%)", genre: n(0, 100)),
        ]),
        Groupe(titre: "Orchestrateur", reglages: [
            Def(chemin: "orchestrator.enabled", libelle: "Orchestrateur des fenêtres de 5 h", genre: b),
            Def(chemin: "orchestrator.active_hours.start", libelle: "Début de la plage active", genre: h),
            Def(chemin: "orchestrator.active_hours.end", libelle: "Fin de la plage active", genre: h),
            Def(chemin: "orchestrator.reserve_points", libelle: "Réserve (points)", genre: n(0, 100)),
        ]),
        Groupe(titre: "Alertes", reglages: [
            Def(chemin: "alerts.enabled", libelle: "Alertes", genre: b),
            Def(chemin: "alerts.eta_minutes", libelle: "Prévenir avant la limite (minutes)", genre: n(1, 1440)),
            Def(chemin: "alerts.weekly_forecast", libelle: "Prévision de la semaine", genre: b),
            Def(chemin: "alerts.waiting_reminder", libelle: "Rappel quand une session attend ma réponse", genre: b),
            Def(chemin: "alerts.waiting_reminder_min", libelle: "Rappel après (minutes)", genre: n(1, 1440)),
            Def(chemin: "context_alert.enabled", libelle: "Alerte de contexte lourd", genre: b),
            Def(chemin: "context_alert.threshold_tokens", libelle: "Seuil du contexte lourd (jetons)", genre: n(1000, 10_000_000, entier: true)),
            Def(chemin: "context_alert.auto_compact", libelle: "Compacter automatiquement les chats au-delà du seuil", genre: b),
            Def(chemin: "budget.enabled", libelle: "Budgets par projet", genre: b),
        ]),
        Groupe(titre: "Ne pas déranger", reglages: [
            Def(chemin: "alerts.quiet.enabled", libelle: "Plage de silence", genre: b),
            Def(chemin: "alerts.quiet.start", libelle: "Début", genre: h),
            Def(chemin: "alerts.quiet.end", libelle: "Fin", genre: h),
            Def(chemin: "alerts.quiet.allow_waiting", libelle: "Prévenir quand même si une session attend ma réponse", genre: b),
        ]),
        Groupe(titre: "Chat et sessions", reglages: [
            Def(chemin: "chat.rights", libelle: "Droits des nouveaux chats", genre: .choix(droits)),
            Def(chemin: "chat.auto_clear", libelle: "Effacement automatique : Claude vide la conversation (/clear) en fin de sujet", genre: b),
            Def(chemin: "chat.idle_suspend_min", libelle: "Mise en veille d'un chat inactif (minutes, 0 = jamais)", genre: n(0, 1440, entier: true)),
            Def(chemin: "sessions.idle_hours", libelle: "Session inactive après (heures)", genre: n(0.01, 720)),
        ]),
        Groupe(titre: "Git", reglages: [
            Def(chemin: "git.fetch_minutes", libelle: "Fetch automatique (minutes, 0 = jamais)", genre: n(0, 1440, entier: true)),
            Def(chemin: "git.layout", libelle: "Disposition de la page Git (bureau)",
                genre: .choix([Option(valeur: "A", libelle: "A"), Option(valeur: "B", libelle: "B"), Option(valeur: "C", libelle: "C")])),
            Def(chemin: "git.avatars", libelle: "Avatars des auteurs (bureau)", genre: b),
        ]),
        Groupe(titre: "Tâches de nuit", reglages: [
            Def(chemin: "tasks.enabled", libelle: "Lancer les tâches", genre: b),
            Def(chemin: "tasks.night.start", libelle: "Début de la nuit", genre: h),
            Def(chemin: "tasks.night.end", libelle: "Fin de la nuit", genre: h),
            Def(chemin: "tasks.max_attempts", libelle: "Relances après une limite atteinte", genre: n(1, 10, entier: true)),
        ]),
        Groupe(titre: "Archive des conversations", reglages: [
            Def(chemin: "archive.enabled", libelle: "Archiver les conversations", genre: b),
            Def(chemin: "archive.idle_days", libelle: "Archiver après (jours inactifs)", genre: n(0, 3650, entier: true)),
            Def(chemin: "archive.max_age_days", libelle: "Supprimer après (jours, 0 = jamais)", genre: n(0, 36500, entier: true)),
        ]),
        Groupe(titre: "Mises à jour", reglages: [Def(chemin: "updates.enabled", libelle: "Chercher les nouvelles versions", genre: b)]),
    ]

    /// Valeur au chemin `a.b.c` des réglages, ou nil.
    static func lire(_ reglages: JSON, _ chemin: String) -> JSON? {
        var e: JSON? = reglages
        for k in chemin.split(separator: ".") {
            guard let v = e?[String(k)] else { return nil }
            e = v
        }
        return e
    }

    /// Copie des réglages avec `valeur` au chemin (après un enregistrement réussi).
    static func ecrire(_ reglages: JSON, _ chemin: String, _ valeur: JSON) -> JSON {
        let cles = chemin.split(separator: ".").map(String.init)
        func dans(_ o: JSON, _ i: Int) -> JSON {
            var obj = o.objet ?? [:]
            let k = cles[i]
            obj[k] = i == cles.count - 1 ? valeur : dans(obj[k] ?? .vide, i + 1)
            return .objet(obj)
        }
        return cles.isEmpty ? reglages : dans(reglages, 0)
    }

    static func booleen(_ e: JSON?) -> Bool { return e?.booleen ?? false }

    /// Texte à montrer dans un champ (nombre sans « .0 » inutile).
    static func texte(_ e: JSON?) -> String {
        guard let e = e else { return "" }
        if let s = e.chaine { return s }
        if let n = e.nombre { return JSON.texteNombre(n) }
        return e.contenu ?? ""
    }

    /// Nombre saisi (virgule ou point), vérifié contre les bornes : (valeur, erreur).
    static func nombre(_ saisi: String, min: Double, max: Double, entier: Bool) -> (valeur: Double?, erreur: String?) {
        guard let d = Double(saisi.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: ",", with: ".")) else {
            return (nil, "Entre un nombre.")
        }
        if d < min || d > max { return (nil, "Entre \(JSON.texteNombre(min)) et \(JSON.texteNombre(max)).") }
        if entier && d != d.rounded(.down) { return (nil, "Entre un nombre entier.") }
        return (d, nil)
    }

    /// Heure `H:MM` ou `HH:MM` → `HH:MM`, ou nil.
    static func heure(_ saisi: String) -> String? {
        let t = saisi.trimmingCharacters(in: .whitespaces)
        guard TachesFond.heureValide(t) else { return nil }
        return t.count == 4 ? "0" + t : t
    }
}
