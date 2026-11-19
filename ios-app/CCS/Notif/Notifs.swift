import Foundation
import UserNotifications

/// Chat visé par une notification : de quoi le rouvrir d'un toucher.
struct CibleChat: Equatable {
    var chatId: String
    var cwd: String
    var sessionId: String?
    var chemin: String?
    var titre: String

    var infos: [String: String] {
        var d = ["chat": chatId, "cwd": cwd, "titre": titre]
        if let s = sessionId { d["session"] = s }
        if let c = chemin { d["chemin"] = c }
        return d
    }

    init(chatId: String, cwd: String, sessionId: String?, chemin: String?, titre: String) {
        self.chatId = chatId
        self.cwd = cwd
        self.sessionId = sessionId
        self.chemin = chemin
        self.titre = titre
    }

    init?(infos d: [AnyHashable: Any]) {
        guard let c = d["chat"] as? String, let w = d["cwd"] as? String else { return nil }
        chatId = c
        cwd = w
        sessionId = d["session"] as? String
        chemin = d["chemin"] as? String
        titre = (d["titre"] as? String) ?? ""
    }

    var destination: DestChat {
        return DestChat(cwd: cwd, sessionId: sessionId, chemin: chemin, titre: titre, chatId: chatId)
    }
}

/**
 * Notifications locales (pas d'APNs avec un identifiant Apple gratuit) : fin de tour, autorisation
 * ou question en attente, rappel. Une notification par chat et par demande ; « Autoriser » et
 * « Refuser » répondent sans ouvrir l'appli.
 */
enum Notifs {
    static let categorieAutorisation = "autorisation"
    static let actionAutoriser = "allow"
    static let actionRefuser = "deny"

    static func idFin(_ chatId: String) -> String { return chatId + "|fin" }
    static func idAttente(_ chatId: String, _ requestId: String) -> String { return chatId + "|" + requestId }

    static func preparer() {
        let c = UNUserNotificationCenter.current()
        let oui = UNNotificationAction(identifier: actionAutoriser, title: "Autoriser", options: [])
        let non = UNNotificationAction(identifier: actionRefuser, title: "Refuser", options: [.destructive])
        c.setNotificationCategories([
            UNNotificationCategory(identifier: categorieAutorisation, actions: [oui, non], intentIdentifiers: [], options: []),
        ])
        c.requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    /// Titre, sous-titre et corps d'une annonce (nil pour un retrait).
    static func contenu(_ a: Veilleur.Action) -> (sous: String, texte: String, demande: String?)? {
        switch a {
        case .finTour(_, let resume):
            return ("a terminé", resume, nil)
        case .attente(_, let r, let question, let texte):
            return ("attend ta réponse", (question ? "Question : " : "Autorisation : ") + texte, question ? nil : r)
        case .rappel(_, let r, let question, let texte, let minutes):
            return ("attend toujours ta réponse", "Toujours en attente depuis \(minutes) min — " + texte, question ? nil : r)
        default:
            return nil
        }
    }

    static func appliquer(_ a: Veilleur.Action, _ cible: CibleChat?) {
        let c = UNUserNotificationCenter.current()
        switch a {
        case .retirerFin(let chat):
            c.removeDeliveredNotifications(withIdentifiers: [idFin(chat)])
        case .retirerAttente(let chat, let r):
            c.removeDeliveredNotifications(withIdentifiers: [idAttente(chat, r)])
        case .retirerTout(let chat):
            c.getDeliveredNotifications { liste in
                let ids = liste.filter { $0.request.content.threadIdentifier == chat }.map { $0.request.identifier }
                if !ids.isEmpty { c.removeDeliveredNotifications(withIdentifiers: ids) }
            }
        case .finTour, .attente, .rappel:
            guard let cible = cible, let k = contenu(a) else { return }
            let demande = k.demande
            let n = UNMutableNotificationContent()
            n.title = cible.titre
            n.subtitle = k.sous
            n.body = k.texte
            n.sound = .default
            n.threadIdentifier = a.chatId
            var infos = cible.infos
            if let d = demande {
                n.categoryIdentifier = categorieAutorisation
                infos["demande"] = d
            }
            n.userInfo = infos
            let id: String
            switch a {
            case .attente(let chat, let r, _, _), .rappel(let chat, let r, _, _, _): id = idAttente(chat, r)
            default: id = idFin(a.chatId)
            }
            c.add(UNNotificationRequest(identifier: id, content: n, trigger: nil))
        }
    }

    /// Remplace l'alerte d'une demande par un message d'échec (réponse rapide impossible).
    static func echecReponse(_ chatId: String, _ requestId: String, _ message: String, _ cible: CibleChat?) {
        let n = UNMutableNotificationContent()
        n.title = "Réponse non envoyée"
        n.body = message
        n.threadIdentifier = chatId
        if let c = cible { n.userInfo = c.infos }
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: idAttente(chatId, requestId), content: n, trigger: nil))
    }
}
