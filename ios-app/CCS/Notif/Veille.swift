import Foundation
import UIKit
import UserNotifications

/**
 * Veille des chats du pont tant que l'appli tourne (au premier plan, ou juste passée en arrière-plan
 * le temps qu'iOS lui laisse) : rattache le WebSocket à tous les chats ouverts (`chat.list` puis
 * `chat.attach`, à chaque connexion et chaque minute pour ceux ouverts ailleurs), lit leurs
 * événements et confie la décision au `Veilleur`. Port de `notif/Veille.kt`.
 */
@MainActor
final class Veille: NSObject, UNUserNotificationCenterDelegate {
    private let client: CcsClient
    /// Ouvre un chat (toucher sur une notification).
    var ouvrir: ((DestChat) -> Void)?
    /// Toucher la notification du son partagé (« Touchez pour envoyer le son vers X »).
    var ouvrirSon: (() -> Void)?

    private let veilleur = Veilleur()
    private var derniers: [String: Int] = [:]            // chat → dernier numéro lu
    private var infos: [String: ChatOuvert] = [:]
    private var titres: [String: String] = [:]           // conversation → titre
    private var seuil: Double? = 600
    private var seuilLu = false
    private var active = false
    private var minuterie: Task<Void, Never>?
    private var derniereSynchro = Date.distantPast
    private var synchroEnCours = false
    private var synchroDemandee = false
    /// Ordres traités un à la fois, dans l'ordre d'arrivée.
    private var file: [() async -> Void] = []
    private var traitement = false

    private var chatVisible: String?
    private var premierPlan = true
    private var tacheFond: UIBackgroundTaskIdentifier = .invalid

    private static let rejoues = 200

    init(client: CcsClient) {
        self.client = client
        super.init()
        UNUserNotificationCenter.current().delegate = self
    }

    func demarrer() {
        if active { return }
        active = true
        Notifs.preparer()
        client.ecouter("chat.event", pour: self) { [weak self] d in
            self?.mettre { await self?.pousse(d) }
        }
        client.ecouterReconnexions(pour: self) { [weak self] in
            self?.seuilLu = false
            self?.mettre { await self?.synchroniser(tous: true) }
        }
        mettre { [weak self] in await self?.attendreConnexionPuisSynchroniser() }
        minuterie = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 60_000_000_000)
                self?.mettre { await self?.tic() }
            }
        }
    }

    func arreter() {
        active = false
        minuterie?.cancel()
        minuterie = nil
        file = []
        derniers = [:]
        infos = [:]
        titres = [:]
        _ = veilleur.garderSeulement([])
        UNUserNotificationCenter.current().removeAllDeliveredNotifications()
    }

    /**
     * Autre machine pilotée : la veille partage le client de l'appli, donc suit la machine (comme
     * le web) ; ce qu'elle savait des chats de l'ancienne est oublié avant la reconnexion.
     */
    func oublierChats() {
        mettre { [weak self] in self?.viderChats() }
    }

    private func viderChats() {
        derniers = [:]
        infos = [:]
        titres = [:]
        _ = veilleur.garderSeulement([])
        UNUserNotificationCenter.current().removeAllDeliveredNotifications()
    }

    // MARK: écran

    /// Chat affiché à l'écran (nil quand on le quitte).
    func afficher(_ chatId: String?) {
        chatVisible = chatId
        appliquerAffiche()
    }

    func quitter(_ chatId: String?) {
        if let c = chatId, chatVisible == c { afficher(nil) }
    }

    /// Premier plan / arrière-plan : en arrière-plan, aucun chat n'est « vu » et on demande à iOS
    /// un peu de temps pour finir d'écouter (une trentaine de secondes, selon le système).
    func premierPlan(_ actif: Bool) {
        premierPlan = actif
        appliquerAffiche()
        if actif {
            finirTacheFond()
            UNUserNotificationCenter.current().setBadgeCount(0) { _ in }
        } else if tacheFond == .invalid {
            tacheFond = UIApplication.shared.beginBackgroundTask(withName: "Veille des chats") { [weak self] in
                self?.finirTacheFond()
            }
        }
    }

    private func finirTacheFond() {
        if tacheFond != .invalid {
            UIApplication.shared.endBackgroundTask(tacheFond)
            tacheFond = .invalid
        }
    }

    private func appliquerAffiche() {
        let a = premierPlan ? chatVisible : nil
        if a == veilleur.affiche { return }
        executer(veilleur.afficher(a))
    }

    // MARK: file

    private func mettre(_ o: @escaping () async -> Void) {
        guard active else { return }
        file.append(o)
        if traitement { return }
        traitement = true
        Task {
            while !file.isEmpty {
                let o = file.removeFirst()
                await o()
            }
            traitement = false
        }
    }

    private func attendreConnexionPuisSynchroniser() async {
        if client.etat.estConnecte { await synchroniser(tous: true) }
        // sinon : la reconnexion (ou le premier tic connecté) s'en charge
    }

    private func tic() async {
        let maintenant = Date().timeIntervalSince1970
        if client.etat.estConnecte && Date().timeIntervalSince(derniereSynchro) >= 60 {
            await synchroniser(tous: derniers.isEmpty)
        }
        executer(veilleur.rappels(maintenant: maintenant, seuil: seuil))
    }

    /**
     * `tous` : après une connexion, chaque chat est rattaché (la nouvelle connexion ne l'est pas
     * encore). Sinon (chaque minute), seuls les chats nouveaux le sont : les autres poussent déjà.
     */
    private func synchroniser(tous: Bool) async {
        synchroDemandee = false
        derniereSynchro = Date()
        if !seuilLu { await lireSeuil() }
        guard let chats = try? await client.appeler("chat.list", en: ListeChats.self).chats else { return }
        let ids = Set(chats.map { $0.chatId })
        executer(veilleur.garderSeulement(ids))
        derniers = derniers.filter { ids.contains($0.key) }
        for c in chats {
            infos[c.chatId] = c
            let connu = derniers[c.chatId]
            if !tous && connu != nil { continue }
            let silencieux = connu == nil
            let depuis = connu ?? max(0, c.seq - Veille.rejoues)
            guard let r = try? await client.appeler("chat.attach", ["chat_id": .chaine(c.chatId), "since": .nombre(Double(depuis))]) else { continue }
            if connu == nil { derniers[c.chatId] = depuis }
            for item in r.liste("events") { await traiter(c.chatId, item, silencieux: silencieux) }
            let etat = r.texte("state")
            if !etat.isEmpty { veilleur.connaitre(c.chatId, etat) }
            if silencieux { veilleur.marquerAnciennes(maintenant: Date().timeIntervalSince1970, seuil: seuil) }
        }
    }

    /// Rappel d'attente du serveur (`alerts.waiting_reminder`, `alerts.waiting_reminder_min`).
    private func lireSeuil() async {
        guard let r = try? await client.appeler("settings.get") else { return }
        let a = r["settings"]?["alerts"] ?? .vide
        let actif = a.bool("waiting_reminder", true)
        let min = a.entier("waiting_reminder_min", 10)
        seuil = actif && min > 0 ? Double(min) * 60 : nil
        seuilLu = true
    }

    private func pousse(_ d: JSON) async {
        let id = d.texte("chat_id")
        if id.isEmpty { return }
        if derniers[id] == nil {
            // chat ouvert depuis ce téléphone (chat.open nous y rattache) : relire la liste
            if synchroDemandee { return }
            synchroDemandee = true
            mettre { [weak self] in await self?.synchroniser(tous: false) }
            return
        }
        await traiter(id, d, silencieux: false)
    }

    private func traiter(_ chatId: String, _ item: JSON, silencieux: Bool) async {
        guard let seq = item.entierOuNul("seq") else { return }
        if seq <= (derniers[chatId] ?? 0) { return }
        derniers[chatId] = seq
        guard let ev = item["event"], ev.objet != nil else { return }
        let ts = item.doubleOuNul("ts") ?? Date().timeIntervalSince1970
        let actions = veilleur.recevoir(chatId, EvChat.lire(ev), ts: ts, silencieux: silencieux)
        for a in actions {
            switch a {
            case .finTour, .attente, .rappel: await titrer(a.chatId)
            default: break
            }
        }
        executer(actions)
    }

    private func executer(_ actions: [Veilleur.Action]) {
        for a in actions { Notifs.appliquer(a, cible(a.chatId)) }
    }

    func cible(_ chatId: String) -> CibleChat? {
        guard let c = infos[chatId] else { return nil }
        let t = c.sessionId.flatMap { titres[$0] } ?? Format.base(c.cwd)
        return CibleChat(chatId: c.chatId, cwd: c.cwd, sessionId: c.sessionId, chemin: c.path, titre: t)
    }

    /// Titre de la conversation (`projects.list` du dossier), lu une fois ; sinon le nom du dossier.
    private func titrer(_ chatId: String) async {
        guard let c = infos[chatId], let sid = c.sessionId, titres[sid] == nil else { return }
        guard let l = try? await client.appeler("projects.list", ["cwd": .chaine(c.cwd)], delai: 5, en: ListeProjets.self) else { return }
        if let conv = l.conversations.first(where: { $0.sessionId == sid }) { titres[sid] = conv.titre }
    }

    // MARK: UNUserNotificationCenterDelegate

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list, .sound])
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let infos = response.notification.request.content.userInfo
        let action = response.actionIdentifier
        let demande = infos["demande"] as? String
        let cible = CibleChat(infos: infos)
        Task { @MainActor in
            if let c = cible, let d = demande, action == Notifs.actionAutoriser || action == Notifs.actionRefuser {
                await self.repondre(c, d, action)
            } else if let c = cible, action == UNNotificationDefaultActionIdentifier {
                self.ouvrir?(c.destination)
            } else if infos["son"] != nil, action == UNNotificationDefaultActionIdentifier {
                self.ouvrirSon?()
            }
            completionHandler()
        }
    }

    private func repondre(_ c: CibleChat, _ demande: String, _ decision: String) async {
        let t = UIApplication.shared.beginBackgroundTask(withName: "Réponse à Claude", expirationHandler: nil)
        defer { UIApplication.shared.endBackgroundTask(t) }
        do {
            _ = try await client.appeler("chat.answer", ["chat_id": .chaine(c.chatId), "request_id": .chaine(demande), "decision": .chaine(decision)], delai: 9)
            UNUserNotificationCenter.current().removeDeliveredNotifications(withIdentifiers: [Notifs.idAttente(c.chatId, demande)])
        } catch {
            Notifs.echecReponse(c.chatId, demande, texteErreur(error), c)
        }
    }
}
