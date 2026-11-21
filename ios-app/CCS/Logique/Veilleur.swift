import Foundation

/**
 * Décide des notifications à partir des événements des chats (`chat.event`), sans iOS : fin de
 * tour (retour au repos après un travail), autorisation ou question en attente, rappel unique d'une
 * attente trop longue (comme le rappel d'attente du bureau, `daemon.py`). Port du `Veilleur` Android.
 *
 * Pas de notification pour le chat affiché à l'écran (`afficher`) ; celles qu'il avait sont retirées.
 * Les événements rejoués au premier rattachement d'un chat sont lus en `silencieux` : ils
 * renseignent l'état et les attentes en cours sans rien annoncer (déjà vus ailleurs).
 */
final class Veilleur {
    enum Action: Equatable {
        case finTour(chatId: String, resume: String)
        case attente(chatId: String, requestId: String, question: Bool, texte: String)
        case rappel(chatId: String, requestId: String, question: Bool, texte: String, minutes: Int)
        case retirerFin(chatId: String)
        case retirerAttente(chatId: String, requestId: String)
        /// Toutes les notifications du chat (chat affiché ou fermé).
        case retirerTout(chatId: String)

        var chatId: String {
            switch self {
            case .finTour(let c, _), .attente(let c, _, _, _), .rappel(let c, _, _, _, _),
                 .retirerFin(let c), .retirerAttente(let c, _), .retirerTout(let c):
                return c
            }
        }

        var estRetrait: Bool {
            switch self {
            case .retirerFin, .retirerAttente, .retirerTout: return true
            default: return false
            }
        }
    }

    private final class Suivi {
        var etat: String
        var interrompu = false
        var dernierTexte = ""
        init(_ e: String) { etat = e }
    }

    private final class EnAttente {
        let chatId: String
        let requestId: String
        let question: Bool
        let texte: String
        let depuis: Double
        var rappele = false
        init(_ c: String, _ r: String, _ q: Bool, _ t: String, _ d: Double) {
            chatId = c
            requestId = r
            question = q
            texte = t
            depuis = d
        }
    }

    private var chats: [String: Suivi] = [:]
    /// Clé : chat|demande ; l'ordre d'arrivée est gardé à part.
    private var attentes: [String: EnAttente] = [:]
    private var ordre: [String] = []

    /// Chat affiché à l'écran (nil : aucun, ou appli en arrière-plan).
    private(set) var affiche: String?

    private static let travail: Set<String> = ["busy", "permission"]
    private static let maxResume = 300

    func etat(_ chatId: String) -> String? { return chats[chatId]?.etat }

    func attentes(_ chatId: String) -> [String] {
        return enOrdre.filter { $0.chatId == chatId }.map { $0.requestId }
    }

    private var enOrdre: [EnAttente] { return ordre.compactMap { attentes[$0] } }

    /// État lu dans `chat.list` / `chat.attach` : fait foi, sans alerte.
    func connaitre(_ chatId: String, _ etat: String) {
        let s = suivi(chatId, defaut: etat)
        s.etat = etat
        if etat != "permission" && etat != "busy" { _ = retirerAttentes(chatId) }
    }

    /// Chats fermés dans le pont : leurs notifications partent.
    func garderSeulement(_ ouverts: Set<String>) -> [Action] {
        let partis = chats.keys.filter { !ouverts.contains($0) }.sorted()
        for id in partis {
            chats.removeValue(forKey: id)
            _ = retirerAttentes(id)
        }
        return partis.map { .retirerTout(chatId: $0) }
    }

    func afficher(_ chatId: String?) -> [Action] {
        affiche = chatId
        if let c = chatId { return [.retirerTout(chatId: c)] }
        return []
    }

    /// Un événement du chat ; `ts` en secondes.
    func recevoir(_ chatId: String, _ ev: EvChat, ts: Double, silencieux: Bool = false) -> [Action] {
        let s = suivi(chatId, defaut: "idle")
        let vu = silencieux || affiche == chatId
        var out: [Action] = []
        switch ev {
        case .etat(let e):
            let avant = s.etat
            s.etat = e
            if e == "idle" && Veilleur.travail.contains(avant) {
                if !s.interrompu && !vu { out.append(.finTour(chatId: chatId, resume: Veilleur.resumer(s.dernierTexte))) }
                s.interrompu = false
                out += retirerAttentes(chatId)
            } else if e == "busy" && !Veilleur.travail.contains(avant) {
                s.interrompu = false
                s.dernierTexte = ""
                out.append(.retirerFin(chatId: chatId))     // nouveau tour : l'ancienne fin ne sert plus
            } else if e == "stopped" || e == "suspended" {
                out += retirerAttentes(chatId)
            }
        case .texte(_, let texte, let parent):
            if parent == nil && !texte.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { s.dernierTexte = texte }
        case .tour(_, _, _, let texte, _, let interrompu, _):
            if interrompu { s.interrompu = true }
            if !texte.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { s.dernierTexte = texte }
        case .autorisation(let requestId, let outil, let affiche, let entree, _, _):
            let question = outil == "AskUserQuestion"
            let texte: String
            if question {
                let q = FilChat.questions(entree).first?.question ?? ""
                texte = q.isEmpty ? "Claude te pose une question." : q
            } else {
                let quoi = affiche.isEmpty ? Outils.libelle(outil) : affiche
                let cible = Outils.cible(outil, entree)
                texte = cible.isEmpty ? quoi : "\(quoi) : \(cible)"
            }
            let k = Veilleur.cle(chatId, requestId)
            if attentes[k] == nil { ordre.append(k) }
            attentes[k] = EnAttente(chatId, requestId, question, texte, ts)
            if !vu { out.append(.attente(chatId: chatId, requestId: requestId, question: question, texte: texte)) }
        case .reglee(let requestId, _):
            let k = Veilleur.cle(chatId, requestId)
            let avait = attentes.removeValue(forKey: k) != nil
            ordre.removeAll { $0 == k }
            if avait || !silencieux { out.append(.retirerAttente(chatId: chatId, requestId: requestId)) }
        case .fin:
            s.etat = "stopped"
            out += retirerAttentes(chatId)
        default:
            break
        }
        return silencieux ? out.filter { $0.estRetrait } : out
    }

    /**
     * Rappels dus : attentes d'au moins `seuil` secondes, pas encore rappelées. Une attente vue sur
     * le chat affiché compte comme vue (pas de rappel).
     */
    func rappels(maintenant: Double, seuil: Double?) -> [Action] {
        guard let seuil = seuil, seuil > 0 else { return [] }
        var out: [Action] = []
        for a in enOrdre {
            if a.rappele || maintenant - a.depuis < seuil { continue }
            a.rappele = true
            if a.chatId == affiche { continue }
            out.append(.rappel(chatId: a.chatId, requestId: a.requestId, question: a.question, texte: a.texte,
                               minutes: Int((maintenant - a.depuis) / 60)))
        }
        return out
    }

    /// Attentes trouvées au premier rattachement déjà plus vieilles que le seuil : pas de rappel.
    func marquerAnciennes(maintenant: Double, seuil: Double?) {
        guard let seuil = seuil, seuil > 0 else { return }
        for a in enOrdre where maintenant - a.depuis >= seuil { a.rappele = true }
    }

    private func suivi(_ chatId: String, defaut: String) -> Suivi {
        if let s = chats[chatId] { return s }
        let s = Suivi(defaut)
        chats[chatId] = s
        return s
    }

    private func retirerAttentes(_ chatId: String) -> [Action] {
        let parties = enOrdre.filter { $0.chatId == chatId }
        for a in parties {
            let k = Veilleur.cle(chatId, a.requestId)
            attentes.removeValue(forKey: k)
            ordre.removeAll { $0 == k }
        }
        return parties.map { .retirerAttente(chatId: chatId, requestId: $0.requestId) }
    }

    private static func cle(_ c: String, _ r: String) -> String { return c + "|" + r }

    /// Fin de la réponse de Claude, sur une ligne, pour le corps de la notification.
    static func resumer(_ texte: String) -> String {
        let t = texte.replacingOccurrences(of: "[`*_#>]+", with: "", options: .regularExpression)
            .replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
        if t.isEmpty { return "Prêt pour la suite." }
        if t.count <= maxResume { return t }
        return String(t.prefix(maxResume - 1)).trimmingCharacters(in: .whitespaces) + "…"
    }
}
