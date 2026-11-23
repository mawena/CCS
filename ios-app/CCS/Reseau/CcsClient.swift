import Foundation
import Observation

/// État du WebSocket, montré par le bandeau de connexion.
enum EtatConnexion: Equatable {
    /// Pas démarré (pas d'identifiants) ou arrêté.
    case arrete
    case connexion(tentative: Int)
    case connecte
    /// Coupé ; nouvel essai dans `attente` secondes (ou plus tôt sur `reessayer()`).
    case horsLigne(raison: String, attente: Double)
    /// Le serveur refuse les identifiants (jeton révoqué, session Portier finie) : se reconnecter.
    case refuse(raison: String)

    var estConnecte: Bool {
        if case .connecte = self { return true }
        return false
    }
}

/**
 * Client du WebSocket `/api/ws` : appels RPC `async` (corrélés par id, avec délai), événements
 * poussés aux abonnés, reconnexion automatique (1 s, 2 s, 4 s… jusqu'à 30 s), état observable.
 *
 * Comme le client web (`ccs_app/web/api.js`) : un appel fait hors ligne attend dans la file et part
 * à la connexion ; un appel déjà envoyé quand la connexion tombe échoue (`hors_ligne`), car son sort
 * est inconnu. Les abonnés à `reconnexions` sont prévenus à chaque reconnexion pour se rattacher.
 * Tout se passe sur le fil principal : pas de verrou.
 */
@MainActor
@Observable
final class CcsClient {
    static let fermeParAuth = 4001
    /// La machine pilotée est injoignable (hors ligne, tunnel coupé) : on retente plus tard.
    static let machineInjoignable = 4010
    static let ceServeur = "Ce serveur"
    nonisolated private static let cleMachine = "machine"
    nonisolated private static let cleNomMachine = "machine-nom"
    private static let maxAttentes = 100

    private(set) var etat: EtatConnexion = .arrete

    /**
     * Machine pilotée (vide : ce serveur), gardée dans les préférences ; la connexion passe alors
     * par le pont du serveur jusqu'à celui de l'autre machine (`?machine=<id>`), comme le web.
     */
    private(set) var machine: String

    /// Connexion fixée sur une machine (onglet Fichiers d'un autre appareil) : la machine pilotée
    /// gardée dans les préférences n'est ni lue ni modifiée.
    let fixe: Bool

    /// Nom affiché de la machine pilotée : « Ce serveur », ou son nom gardé au choix.
    var nomMachine: String {
        if machine.isEmpty { return CcsClient.ceServeur }
        let n = Prefs.lire(CcsClient.cleNomMachine) ?? ""
        return n.trimmingCharacters(in: .whitespaces).isEmpty ? machine : n
    }

    /// Appelé quand le serveur refuse les identifiants (l'appli revient à l'écran de connexion).
    @ObservationIgnored var surRefus: ((String) -> Void)? = nil

    private let delaiAppel: Double
    private let attenteMin: Double
    private let attenteMax: Double

    private struct Attente {
        let texte: String
        let suite: CheckedContinuation<JSON, Error>
        var envoye: Bool
    }

    private struct Abonne {
        let nom: String
        let rappel: (JSON) -> Void
        /// Abonné rattaché à un objet : oublié tout seul quand l'objet disparaît.
        weak var proprietaire: AnyObject?
        let lie: Bool
    }

    @ObservationIgnored private var attentes: [Int: Attente] = [:]
    @ObservationIgnored private var suivant = 1
    @ObservationIgnored private var abonnes: [UUID: Abonne] = [:]
    @ObservationIgnored private var abonnesReconnexion: [UUID: () -> Void] = [:]

    @ObservationIgnored private var identifiants: Identifiants? = nil
    @ObservationIgnored private var tache: URLSessionWebSocketTask? = nil
    @ObservationIgnored private var ouverte = false          // la tâche courante a dit « ouvert »
    @ObservationIgnored private var dejaOuvert = false
    @ObservationIgnored private var tentative = 0
    @ObservationIgnored private var attente: Double
    @ObservationIgnored private var attenteTache: Task<Void, Never>? = nil
    @ObservationIgnored private var pingTache: Task<Void, Never>? = nil
    @ObservationIgnored private var pingNumero = 0
    @ObservationIgnored private var pingsEnAttente: Set<Int> = []
    private let delegue: DelegueWebSocket
    private let session: URLSession

    /// `machineFixe` : connexion fixée sur cette machine (vide : le serveur), sans toucher à la machine pilotée.
    init(delaiAppel: Double = 30, attenteMin: Double = 1, attenteMax: Double = 30, machineFixe: String? = nil) {
        self.machine = machineFixe ?? (Prefs.lire(CcsClient.cleMachine) ?? "")
        self.fixe = machineFixe != nil
        self.delaiAppel = delaiAppel
        self.attenteMin = attenteMin
        self.attenteMax = attenteMax
        self.attente = attenteMin
        let d = DelegueWebSocket()
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 60
        config.httpShouldSetCookies = false
        self.delegue = d
        self.session = URLSession(configuration: config, delegate: d, delegateQueue: nil)
        d.client = self
    }

    // MARK: démarrage et arrêt

    /// Se connecte (ou se reconnecte) avec ces identifiants.
    func demarrer(_ i: Identifiants) {
        arreter()
        identifiants = i
        dejaOuvert = false
        tentative = 0
        attente = attenteMin
        connecter()
    }

    func arreter() {
        identifiants = nil
        attenteTache?.cancel()
        attenteTache = nil
        fermerTache()
        echouerTout("hors_ligne", "Déconnecté.")
        etat = .arrete
    }

    /**
     * Pilote une autre machine (`id` vide : ce serveur). Les appels en cours appartiennent à
     * l'ancienne : ils sont rejetés (`hors_ligne`) et la connexion repart tout de suite.
     */
    func changerMachine(_ id: String, nom: String = "") {
        if !fixe { Prefs.ecrire(CcsClient.cleNomMachine, id.isEmpty || nom.isEmpty ? nil : nom) }
        if id == machine { return }
        if !fixe { Prefs.ecrire(CcsClient.cleMachine, id.isEmpty ? nil : id) }
        machine = id
        // arrêté ou refusé : le choix sert à la prochaine connexion
        guard identifiants != nil else { return }
        if case .refuse = etat { return }
        attenteTache?.cancel()
        attenteTache = nil
        fermerTache()
        echouerTout("hors_ligne", "Machine changée.")
        tentative = 0
        attente = attenteMin
        connecter()
    }

    /// Nouvel essai tout de suite si la connexion attend (réseau revenu, appli au premier plan).
    func reessayer() {
        guard identifiants != nil else { return }
        switch etat {
        case .horsLigne:
            attenteTache?.cancel()
            attenteTache = nil
            connecter()
        case .connecte:
            verifier()
        default:
            break
        }
    }

    /// Retour au premier plan : la connexion a pu mourir pendant que l'appli dormait ; un ping le dit.
    func verifier() {
        guard let t = tache, ouverte else { return }
        pingNumero += 1
        let n = pingNumero
        pingsEnAttente.insert(n)
        t.sendPing { [weak self] erreur in
            let c = self
            let echec = erreur != nil
            Task { @MainActor in
                c?.pingsEnAttente.remove(n)
                if echec { c?.fin(t, refus: false, raison: "Connexion perdue.") }
            }
        }
        // pas de réponse en 10 s : la connexion est morte sans le dire (réseau changé, veille)
        Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 10_000_000_000)
            guard let s = self, s.pingsEnAttente.contains(n) else { return }
            s.pingsEnAttente.remove(n)
            s.fin(t, refus: false, raison: "Connexion perdue.")
        }
    }

    // MARK: appels

    func appeler(_ methode: String, _ params: [String: JSON] = [:], delai: Double? = nil) async throws -> JSON {
        switch etat {
        case .arrete: throw RpcErreur("hors_ligne", "Pas connecté.")
        case .refuse(let raison): throw RpcErreur("refuse", raison)
        default: break
        }
        if attentes.count >= CcsClient.maxAttentes { throw RpcErreur("trop", "Trop de demandes en attente.") }
        let id = suivant
        suivant += 1
        let texte = CodecRpc.requete(id: id, methode: methode, params: params)
        let duree = delai ?? delaiAppel
        return try await withCheckedThrowingContinuation { (suite: CheckedContinuation<JSON, Error>) in
            self.attentes[id] = Attente(texte: texte, suite: suite, envoye: false)
            self.envoyer(id)
            Task { @MainActor [weak self] in
                try? await Task.sleep(nanoseconds: UInt64(duree * 1_000_000_000))
                self?.terminer(id, .failure(RpcErreur("delai", "Pas de réponse du serveur.")))
            }
        }
    }

    /// Appel dont la réponse est lue en modèle : `try await client.appeler("accounts.state", en: EtatComptes.self)`.
    func appeler<T: LisibleJSON>(_ methode: String, _ params: [String: JSON] = [:], delai: Double? = nil, en type: T.Type) async throws -> T {
        let r = try await appeler(methode, params, delai: delai)
        return T(json: r)
    }

    private func envoyer(_ id: Int) {
        guard let t = tache, ouverte, var a = attentes[id], !a.envoye else { return }
        a.envoye = true
        attentes[id] = a
        t.send(.string(a.texte)) { _ in }      // un échec d'envoi se voit par la fin de la connexion
    }

    private func terminer(_ id: Int, _ r: Result<JSON, Error>) {
        guard let a = attentes.removeValue(forKey: id) else { return }
        a.suite.resume(with: r)
    }

    private func echouerTout(_ code: String, _ message: String, seulementEnvoyes: Bool = false) {
        for (id, a) in attentes {
            if seulementEnvoyes && !a.envoye { continue }
            terminer(id, .failure(RpcErreur(code, message)))
        }
    }

    // MARK: événements

    /// S'abonne aux événements `nom` (`chat.event`, `chat.tags`…) ; rend le jeton pour `oublier`.
    @discardableResult
    func ecouter(_ nom: String, _ rappel: @escaping (JSON) -> Void) -> UUID {
        let id = UUID()
        abonnes[id] = Abonne(nom: nom, rappel: rappel, proprietaire: nil, lie: false)
        return id
    }

    /// Abonnement qui vit tant que `proprietaire` (un modèle d'écran) existe.
    @discardableResult
    func ecouter(_ nom: String, pour proprietaire: AnyObject, _ rappel: @escaping (JSON) -> Void) -> UUID {
        let id = UUID()
        abonnes[id] = Abonne(nom: nom, rappel: rappel, proprietaire: proprietaire, lie: true)
        return id
    }

    /// Prévenu à chaque reconnexion (pas à la première ouverture).
    @discardableResult
    func ecouterReconnexions(_ rappel: @escaping () -> Void) -> UUID {
        let id = UUID()
        abonnesReconnexion[id] = rappel
        return id
    }

    func oublier(_ id: UUID) {
        abonnes.removeValue(forKey: id)
        abonnesReconnexion.removeValue(forKey: id)
    }

    /// Événements `nom` en flux, pour `.task { for await d in client.flux("…") { … } }`.
    func flux(_ nom: String) -> AsyncStream<JSON> {
        return AsyncStream { (suite: AsyncStream<JSON>.Continuation) in
            let id = self.ecouter(nom) { d in suite.yield(d) }
            suite.onTermination = { [weak self] _ in
                let c = self
                Task { @MainActor in c?.oublier(id) }
            }
        }
    }

    /// Reconnexions en flux.
    func fluxReconnexions() -> AsyncStream<Void> {
        return AsyncStream { (suite: AsyncStream<Void>.Continuation) in
            let id = self.ecouterReconnexions { suite.yield(()) }
            suite.onTermination = { [weak self] _ in
                let c = self
                Task { @MainActor in c?.oublier(id) }
            }
        }
    }

    // MARK: connexion

    private func connecter() {
        guard let i = identifiants, let url = Adresse.ws(i.serveur, "api/ws", machine: machine) else {
            etat = .refuse(raison: "Adresse du serveur invalide.")
            return
        }
        fermerTache()
        tentative += 1
        etat = .connexion(tentative: tentative)
        var r = URLRequest(url: url)
        r.timeoutInterval = 20
        i.authentifier(&r)
        let t = session.webSocketTask(with: r)
        t.maximumMessageSize = 64 * 1024 * 1024
        tache = t
        ouverte = false
        t.resume()
        recevoir(t)
    }

    private func fermerTache() {
        pingTache?.cancel()
        pingTache = nil
        if let t = tache {
            tache = nil
            t.cancel(with: .normalClosure, reason: nil)
        }
        ouverte = false
    }

    private func recevoir(_ t: URLSessionWebSocketTask) {
        t.receive { [weak self] resultat in
            let c = self
            Task { @MainActor in c?.recu(resultat, t) }
        }
    }

    private func recu(_ resultat: Result<URLSessionWebSocketTask.Message, Error>, _ t: URLSessionWebSocketTask) {
        guard t === tache else { return }
        switch resultat {
        case .failure:
            // la cause exacte (fermeture, refus) arrive aussi par le délégué ; sinon : connexion perdue
            let code = t.closeCode.rawValue
            if code != 0 && code != URLSessionWebSocketTask.CloseCode.invalid.rawValue {
                let f = CcsClient.fermeture(code, "", fixe: fixe)
                fin(t, refus: f.refus, raison: f.raison)
            } else if let statut = (t.response as? HTTPURLResponse)?.statusCode, statut >= 400 {
                let f = CcsClient.refusHttp(statut)
                fin(t, refus: f.refus, raison: f.raison)
            } else {
                fin(t, refus: false, raison: ouverte ? "Connexion perdue." : "Serveur injoignable.")
            }
        case .success(let m):
            switch m {
            case .string(let texte): traiter(texte)
            case .data(let d): if let texte = String(data: d, encoding: .utf8) { traiter(texte) }
            @unknown default: break
            }
            recevoir(t)
        }
    }

    private func traiter(_ texte: String) {
        guard let m = CodecRpc.decoder(texte) else { return }
        switch m {
        case .resultat(let id, let r):
            terminer(id, .success(r))
        case .echec(let id, let code, let message):
            if let i = id { terminer(i, .failure(RpcErreur(code, message))) }
        case .evenement(let nom, let donnees):
            diffuser(nom, donnees)
        }
    }

    private static let reconnexion = "__reconnexion"

    private func diffuser(_ nom: String, _ donnees: JSON) {
        for (id, a) in abonnes where a.nom == nom {
            if a.lie && a.proprietaire == nil {
                abonnes.removeValue(forKey: id)
            } else {
                a.rappel(donnees)
            }
        }
    }

    /// Reconnexions pour un modèle d'écran (oublié tout seul quand il disparaît).
    @discardableResult
    func ecouterReconnexions(pour proprietaire: AnyObject, _ rappel: @escaping () -> Void) -> UUID {
        return ecouter(CcsClient.reconnexion, pour: proprietaire) { _ in rappel() }
    }

    fileprivate func ouvert(_ t: URLSessionWebSocketTask) {
        guard t === tache else { return }
        ouverte = true
        attente = attenteMin
        tentative = 0
        for id in attentes.keys.sorted() { envoyer(id) }
        etat = .connecte
        if dejaOuvert {
            for r in Array(abonnesReconnexion.values) { r() }
            diffuser(CcsClient.reconnexion, .vide)
        }
        dejaOuvert = true
        pingTache?.cancel()
        pingTache = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 25_000_000_000)
                if Task.isCancelled { return }
                self?.verifier()
            }
        }
    }

    fileprivate func ferme(_ t: URLSessionWebSocketTask, code: Int, raison: String) {
        let f = CcsClient.fermeture(code, raison, fixe: fixe)
        fin(t, refus: f.refus, raison: f.raison)
    }

    fileprivate func echoue(_ t: URLSessionTask, statut: Int?) {
        guard let ws = t as? URLSessionWebSocketTask else { return }
        if let s = statut, s >= 400 {
            let f = CcsClient.refusHttp(s)
            fin(ws, refus: f.refus, raison: f.raison)
        } else {
            fin(ws, refus: false, raison: ouverte ? "Connexion perdue." : "Serveur injoignable.")
        }
    }

    /// Fin de la connexion `t` (une seule fois) : refus définitif, ou nouvel essai plus tard.
    private func fin(_ t: URLSessionWebSocketTask, refus: Bool, raison: String) {
        guard t === tache else { return }
        fermerTache()
        echouerTout("hors_ligne", "Connexion perdue.", seulementEnvoyes: true)
        if refus {
            echouerTout("refuse", raison)
            etat = .refuse(raison: raison)
            identifiants = nil
            surRefus?(raison)
            return
        }
        let delai = attente
        etat = .horsLigne(raison: raison, attente: delai)
        attente = min(attente * 2, attenteMax)
        attenteTache?.cancel()
        attenteTache = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(delai * 1_000_000_000))
            if Task.isCancelled { return }
            self?.connecter()
        }
    }

    private static func fermeture(_ code: Int, _ raison: String, fixe: Bool = false) -> (refus: Bool, raison: String) {
        switch code {
        case fermeParAuth: return (true, "Session terminée.")
        case machineInjoignable:
            let defaut = fixe ? "Machine injoignable." : "La machine pilotée est injoignable."
            return (false, raison.trimmingCharacters(in: .whitespaces).isEmpty ? defaut : raison)
        case 1011: return (false, "Pont injoignable sur le serveur.")
        case 1012: return (false, "Connexion au pont perdue.")
        default: return (false, raison.trimmingCharacters(in: .whitespaces).isEmpty ? "Connexion fermée." : raison)
        }
    }

    private static func refusHttp(_ statut: Int) -> (refus: Bool, raison: String) {
        switch statut {
        case 401: return (true, "Identifiants refusés par le serveur.")
        case 403: return (true, "Accès refusé par le serveur.")
        default: return (false, "Erreur \(statut) du serveur.")
        }
    }
}

/// Délégué de la session : ouverture, fermeture et échec du WebSocket, renvoyés au client sur le fil principal.
final class DelegueWebSocket: NSObject, URLSessionWebSocketDelegate {
    weak var client: CcsClient?

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol proto: String?) {
        let c = client
        Task { @MainActor in c?.ouvert(webSocketTask) }
    }

    func urlSession(
        _ session: URLSession, webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?
    ) {
        let c = client
        let texte = reason.flatMap { String(data: $0, encoding: .utf8) } ?? ""
        let code = closeCode.rawValue
        Task { @MainActor in c?.ferme(webSocketTask, code: code, raison: texte) }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        let c = client
        let statut = (task.response as? HTTPURLResponse)?.statusCode
        Task { @MainActor in c?.echoue(task, statut: statut) }
    }
}
