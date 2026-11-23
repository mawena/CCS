import Foundation

/**
 * Un WebSocket `/api/jarvis/oreille` du serveur CCS (même jeton d'appareil ou cookies de Portier que
 * `/api/ws`). Le premier message (`hello` ou `pair`) part dès l'ouverture ; `ouvrir()` rend la
 * première réponse du cerveau (`welcome`, `paired`) ou échoue (refus, relais en erreur, fermeture,
 * 30 s sans réponse). Ensuite, les messages arrivent dans `surMessage` et la fin dans `surFin`
 * (texte à montrer, ou nil si la fermeture est normale), sur le fil principal.
 */
@MainActor
final class LienJarvis {
    var surMessage: (MessageCerveau) -> Void = { _ in }
    var surFin: (String?) -> Void = { _ in }
    /// Le cerveau a répondu : on peut parler.
    private(set) var pret = false

    private let session: URLSession
    private let delegue: DelegueLienJarvis
    private let tache: URLSessionWebSocketTask
    private let premier: String
    private var attente: CheckedContinuation<MessageCerveau, Error>? = nil
    private var relais: String? = nil
    private var fini = false
    private var ping: Task<Void, Never>? = nil
    private var delai: Task<Void, Never>? = nil

    init(url: URL, identifiants: Identifiants, premier: String) {
        let d = DelegueLienJarvis()
        let s = URLSession(configuration: .default, delegate: d, delegateQueue: nil)
        var r = URLRequest(url: url)
        r.timeoutInterval = 30
        identifiants.authentifier(&r)
        let t = s.webSocketTask(with: r)
        // la voix de Jarvis arrive en base64 dans `response` (plus d'1 Mo pour une longue phrase)
        t.maximumMessageSize = 8 * 1024 * 1024
        delegue = d
        session = s
        tache = t
        self.premier = premier
    }

    func ouvrir() async throws -> MessageCerveau {
        return try await withCheckedThrowingContinuation { (c: CheckedContinuation<MessageCerveau, Error>) in
            attente = c
            delegue.ouvert = { [weak self] in
                DispatchQueue.main.async { MainActor.assumeIsolated { self?.ouvert() } }
            }
            delegue.ferme = { [weak self] code, raison in
                DispatchQueue.main.async { MainActor.assumeIsolated { self?.finir(code: code, raison: raison) } }
            }
            delegue.echec = { [weak self] statut in
                DispatchQueue.main.async { MainActor.assumeIsolated { self?.echec(statut) } }
            }
            delai = Task { @MainActor [weak self] in
                try? await Task.sleep(nanoseconds: 30_000_000_000)
                guard !Task.isCancelled, let s = self, s.attente != nil else { return }
                s.rejeter(ErreurJarvis("Jarvis ne répond pas (30 s)."))
                s.fermer()
            }
            tache.resume()
            recevoir()
        }
    }

    func envoyer(_ texte: String) {
        guard !fini else { return }
        tache.send(.string(texte)) { _ in }
    }

    func envoyer(_ donnees: Data) {
        guard !fini else { return }
        tache.send(.data(donnees)) { _ in }
    }

    /// Fermeture voulue : pas de message.
    func fermer() {
        guard !fini else { return }
        fini = true
        pret = false
        nettoyer()
        tache.cancel(with: .normalClosure, reason: nil)
        session.invalidateAndCancel()
    }

    // MARK: interne

    private func ouvert() {
        guard !fini else { return }
        envoyer(premier)
        // le serveur envoie ses pings ; les nôtres gardent le lien vivant derrière nginx
        ping = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 20_000_000_000)
                guard !Task.isCancelled, let s = self, !s.fini else { return }
                s.tache.sendPing { _ in }
            }
        }
    }

    private func recevoir() {
        tache.receive { [weak self] resultat in
            DispatchQueue.main.async { MainActor.assumeIsolated { self?.recu(resultat) } }
        }
    }

    private func recu(_ resultat: Result<URLSessionWebSocketTask.Message, Error>) {
        guard !fini else { return }
        switch resultat {
        case .success(let m):
            if case .string(let t) = m { traiter(Jarvis.lire(t)) }
            recevoir()
        case .failure:
            // code de fermeture parfois connu un peu après l'échec de la lecture (délégué)
            let code = tache.closeCode.rawValue
            if code != 0 && code != URLSessionWebSocketTask.CloseCode.invalid.rawValue {
                finir(code: code, raison: tache.closeReason.flatMap { String(data: $0, encoding: .utf8) } ?? "")
            } else {
                Task { @MainActor [weak self] in
                    try? await Task.sleep(nanoseconds: 300_000_000)
                    self?.finir(code: 1006, raison: "")
                }
            }
        }
    }

    private func traiter(_ m: MessageCerveau) {
        switch m {
        case .relais(let t):
            relais = t                      // la fermeture suit (4011 si Jarvis est injoignable)
        case .refus(let motif, let essais):
            if attente != nil {
                rejeter(ErreurJarvis(Jarvis.texteRefus(motif, essais: essais), refus: motif))
                fermer()
            } else {
                surMessage(m)
            }
        case .bienvenue, .appaire:
            if let c = attente {
                attente = nil
                delai?.cancel()
                pret = true
                c.resume(returning: m)
            } else {
                surMessage(m)
            }
        default:
            surMessage(m)
        }
    }

    private func echec(_ statut: Int?) {
        guard !fini else { return }
        switch statut {
        case 401: terminer("Session CCS refusée : reconnecte l'appli.")
        case 403: terminer("Accès refusé par le serveur CCS.")
        case .some(let s) where s >= 400: terminer("Erreur \(s) du serveur CCS.")
        default:
            // fin de la tâche : la fermeture (code, raison) arrive d'habitude juste avant ou après
            Task { @MainActor [weak self] in
                try? await Task.sleep(nanoseconds: 300_000_000)
                self?.finir(code: 1006, raison: "")
            }
        }
    }

    private func finir(code: Int, raison: String) {
        guard !fini else { return }
        let normale = code == 1000 && relais == nil
        terminer(normale && attente == nil ? nil : Jarvis.texteFermeture(code: code, relais: relais, raison: raison))
    }

    private func terminer(_ texte: String?) {
        guard !fini else { return }
        fini = true
        let etaitPret = pret
        pret = false
        nettoyer()
        tache.cancel(with: .normalClosure, reason: nil)
        session.invalidateAndCancel()
        if attente != nil {
            rejeter(ErreurJarvis(texte ?? "Connexion au relais de Jarvis perdue."))
        } else if etaitPret {
            surFin(texte)
        }
    }

    private func rejeter(_ e: ErreurJarvis) {
        guard let c = attente else { return }
        attente = nil
        delai?.cancel()
        c.resume(throwing: e)
    }

    private func nettoyer() {
        ping?.cancel()
        ping = nil
        delai?.cancel()
        delai = nil
    }
}

/// Délégué de la session : ouverture, fermeture (code, raison) et échec de la poignée de main.
final class DelegueLienJarvis: NSObject, URLSessionWebSocketDelegate {
    // appelés sur la file de la session : ils ne font que repasser sur le fil principal
    var ouvert: @Sendable () -> Void = {}
    var ferme: @Sendable (Int, String) -> Void = { _, _ in }
    var echec: @Sendable (Int?) -> Void = { _ in }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol proto: String?) {
        ouvert()
    }

    func urlSession(
        _ session: URLSession, webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?
    ) {
        ferme(closeCode.rawValue, reason.flatMap { String(data: $0, encoding: .utf8) } ?? "")
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        echec((task.response as? HTTPURLResponse)?.statusCode)
    }
}
