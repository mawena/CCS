import AVFoundation
import Foundation
import Network

/**
 * Sortie audio de l'iPhone : écoute en UDP (Network.framework) le flux RTP/Opus d'une source du
 * réseau maillé, le remet en ordre (tampon de gigue), le décode (Opus d'Apple) et le joue par
 * `AVAudioEngine`. L'horloge est celle de la carte son : chaque tampon joué en demande un autre
 * au tampon de gigue adaptatif (`GigueAdaptative` : 30 ms au départ, de 20 à 150 ms selon les
 * pertes ; trames de 10 ou 20 ms). Au moins 20 ms (et deux tampons) toujours programmés d'avance ;
 * tampon matériel demandé à 5 ms. Session `.playback` : le son continue en arrière-plan
 * (`UIBackgroundModes: audio`). Arrêt sur demande ou après 10 s sans paquet.
 *
 * Mode permanent (« Rester à l'écoute ») : l'écoute ne s'arrête plus après 10 s de silence, le
 * lecteur joue du silence en attendant (la session audio reste active, l'appli n'est pas
 * suspendue en arrière-plan) et tout paquet RTP, de n'importe quelle source, est joué tout de
 * suite. `surSon` signale l'arrivée d'un son et son silence prolongé.
 *
 * Interruptions (appel, autre appli audio) : le moteur s'arrête, puis repart à la fin de
 * l'interruption ; services audio réinitialisés : tout est reconstruit sur le même port.
 *
 * Tout se passe sur la file `file` ; `surFin` est rappelé sur le fil principal.
 */
final class RecepteurSon: @unchecked Sendable {
    /// Rappelé (fil principal) quand l'écoute s'arrête d'elle-même : raison.
    var surFin: ((String) -> Void)?
    /// Mode permanent, rappelé (fil principal) quand un son arrive (true) ou se tait 10 s (false).
    var surSon: ((Bool) -> Void)?

    private let file = DispatchQueue(label: "ccs.son.recepteur", qos: .userInteractive)
    private var ecouteur: NWListener?
    private var connexions: [NWConnection] = []
    /// Créés au départ de l'écoute seulement (pas de sortie audio touchée au lancement de l'appli).
    private var moteur: AVAudioEngine?
    private var lecteur: AVAudioPlayerNode?
    private var decodeur: DecodeurOpus?
    private var gigue = GigueAdaptative()
    /// Tampons programmés sur le lecteur et pas encore joués, et leur durée (échantillons).
    private var enVol = 0
    private var enVolEchantillons = 0
    private var actif = false
    private var dernierPaquet = Date()
    private var veille: DispatchSourceTimer?
    private var source: UInt32?
    private var observateurs: [NSObjectProtocol] = []
    private var permanent = false
    private var port = 0
    /// Mode permanent : un son est en cours (paquet reçu depuis moins de 10 s).
    private var sonEnCours = false
    /// Interruption en cours (appel…) : rien n'est programmé jusqu'à sa fin.
    private var interrompu = false

    /// Écoute ouverte (récepteur UDP et moteur), et sur quel port.
    var ecoute: (port: Int, permanent: Bool)? {
        return file.sync { actif ? (port, permanent) : nil }
    }

    /// Paquets reçus et perdus depuis le départ (pour l'écran Son).
    var bilan: (recues: Int, perdues: Int) {
        return file.sync { (gigue.recues, gigue.perdues) }
    }

    /// Retard visé par le tampon de gigue (ms), pour l'écran Son.
    var retardMs: Int {
        return file.sync { gigue.cibleMs }
    }

    /// Se met à écouter sur `port` (UDP), en mode permanent ou non. Lance l'erreur si le port ou
    /// le son sont indisponibles.
    func demarrer(port: Int, permanent: Bool = false) throws {
        try file.sync { try demarrerSurFile(port: port, permanent: permanent) }
    }

    /// Passe en mode permanent ou en sort sans couper l'écoute.
    func changerMode(permanent p: Bool) {
        file.sync {
            permanent = p
            dernierPaquet = Date()
            if !p { sonEnCours = false }
        }
    }

    private func demarrerSurFile(port: Int, permanent: Bool) throws {
        arreterSurFile()
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
        // simples souhaits : iOS peut garder sa fréquence et un tampon plus grand
        try? session.setPreferredSampleRate(Double(Rtp.frequence))
        try? session.setPreferredIOBufferDuration(Son.tamponMateriel)
        try session.setActive(true)
        guard let d = DecodeurOpus() else { throw ErreurSon("Décodeur Opus indisponible sur cet iPhone.") }
        decodeur = d
        gigue = GigueAdaptative()
        source = nil
        self.port = port
        self.permanent = permanent
        sonEnCours = false
        interrompu = false
        guard let p = NWEndpoint.Port(rawValue: UInt16(clamping: port)) else { throw ErreurSon("Port UDP invalide.") }
        let params = NWParameters.udp
        params.allowLocalEndpointReuse = true
        let l = try NWListener(using: params, on: p)
        l.newConnectionHandler = { [weak self] c in self?.accueillir(c) }
        l.stateUpdateHandler = { [weak self] e in
            if case .failed(let err) = e { self?.finir("Écoute UDP impossible : \(err.localizedDescription)") }
        }
        l.start(queue: file)
        ecouteur = l
        let m = AVAudioEngine()
        let j = AVAudioPlayerNode()
        m.attach(j)
        m.connect(j, to: m.mainMixerNode, format: FormatsSon.pcm)
        moteur = m
        lecteur = j
        try m.start()
        j.play()
        actif = true
        dernierPaquet = Date()
        enVol = 0
        enVolEchantillons = 0
        remplir()
        observer(m)
        let t = DispatchSource.makeTimerSource(queue: file)
        t.schedule(deadline: .now() + 1, repeating: 1)
        t.setEventHandler { [weak self] in
            guard let s = self, s.actif else { return }
            guard Date().timeIntervalSince(s.dernierPaquet) > Son.silenceMax else { return }
            if !s.permanent {
                s.finirSurFile("Plus rien reçu depuis 10 s.")
            } else if s.sonEnCours {
                s.sonEnCours = false
                let rappel = s.surSon
                DispatchQueue.main.async { rappel?(false) }
            }
        }
        t.resume()
        veille = t
    }

    /// Changement de route (casque, AirPlay…), interruption (appel, autre appli), services audio
    /// réinitialisés.
    private func observer(_ m: AVAudioEngine) {
        let nc = NotificationCenter.default
        observateurs.append(nc.addObserver(forName: .AVAudioEngineConfigurationChange, object: m, queue: nil) { [weak self] _ in
            self?.file.async { self?.relancerMoteur() }
        })
        observateurs.append(nc.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: nil) { [weak self] n in
            let brut = n.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            let type = brut.flatMap { AVAudioSession.InterruptionType(rawValue: $0) }
            self?.file.async { self?.interruption(type) }
        })
        observateurs.append(nc.addObserver(forName: AVAudioSession.mediaServicesWereResetNotification, object: nil, queue: nil) { [weak self] _ in
            self?.file.async {
                guard let s = self, s.actif else { return }
                do { try s.demarrerSurFile(port: s.port, permanent: s.permanent) } catch {
                    s.arreterSurFile()
                    let rappel = s.surFin
                    let raison = "Son indisponible après la réinitialisation d'iOS : \(error.localizedDescription)"
                    DispatchQueue.main.async { rappel?(raison) }
                }
            }
        })
    }

    /// Début : le moteur est coupé par iOS, on attend. Fin (même sans « reprendre » conseillé : on
    /// joue en `mixWithOthers`) : session réactivée, moteur relancé. Un échec est retenté au
    /// prochain changement de configuration.
    private func interruption(_ type: AVAudioSession.InterruptionType?) {
        guard actif, let type = type else { return }
        switch type {
        case .began:
            interrompu = true
        case .ended:
            interrompu = false
            try? AVAudioSession.sharedInstance().setActive(true)
            gigue = GigueAdaptative(cibleMs: gigue.cibleMs)
            relancerMoteur()
        @unknown default:
            break
        }
    }

    func arreter() {
        file.sync { arreterSurFile() }
    }

    // MARK: réception

    private func accueillir(_ c: NWConnection) {
        connexions.append(c)
        c.stateUpdateHandler = { [weak self, weak c] e in
            switch e {
            case .failed, .cancelled:
                guard let s = self, let c = c else { return }
                s.connexions.removeAll { $0 === c }
            default: break
            }
        }
        c.start(queue: file)
        lire(c)
    }

    private func lire(_ c: NWConnection) {
        c.receiveMessage { [weak self, weak c] donnees, _, _, erreur in
            guard let s = self, let c = c, s.actif else { return }
            if let d = donnees { s.recu(d) }
            if erreur == nil { s.lire(c) }
        }
    }

    private func recu(_ d: Data) {
        guard let (e, trame) = Rtp.lire(d), e.type == Rtp.typeOpus, !trame.isEmpty else { return }
        // une autre source a pris la place (nouvel envoi) : on repart de zéro
        if let s = source, s != e.ssrc { gigue = GigueAdaptative() }
        source = e.ssrc
        dernierPaquet = Date()
        if permanent && !sonEnCours {
            sonEnCours = true
            let rappel = surSon
            DispatchQueue.main.async { rappel?(true) }
        }
        gigue.ajouter(sequence: e.sequence, trame)
    }

    // MARK: lecture

    /// Programme d'avance au moins `Son.avanceMinMs` (20 ms) et `Son.tamponsEnVolMin` tampons.
    private func remplir() {
        let minimum = Son.avanceMinMs * Rtp.frequence / 1000
        while actif && (enVol < Son.tamponsEnVolMin || enVolEchantillons < minimum) {
            if !programmer() { return }
        }
    }

    /// Programme la trame suivante (10 ou 20 ms) : trame décodée, ou silence de même durée
    /// (perte, attente). False si rien n'a pu être programmé.
    @discardableResult
    private func programmer() -> Bool {
        guard actif, !interrompu, let lecteur = lecteur else { return false }
        var decode: AVAudioPCMBuffer?
        if case .trame(let t) = gigue.sortir() { decode = decodeur?.decoder(t) }
        guard let b = decode ?? FormatsSon.silence(AVAudioFrameCount(gigue.echantillons)) else { return false }
        let n = Int(b.frameLength)
        enVol += 1
        enVolEchantillons += n
        lecteur.scheduleBuffer(b, completionCallbackType: .dataConsumed) { [weak self] _ in
            guard let s = self else { return }
            s.file.async {
                s.enVol = max(0, s.enVol - 1)
                s.enVolEchantillons = max(0, s.enVolEchantillons - n)
                s.remplir()
            }
        }
        return true
    }

    private func relancerMoteur() {
        guard actif, !interrompu, let moteur = moteur, let lecteur = lecteur else { return }
        if !moteur.isRunning {
            do { try moteur.start() } catch { return }
        }
        if !lecteur.isPlaying { lecteur.play() }
        enVol = 0
        enVolEchantillons = 0
        remplir()
    }

    // MARK: arrêt

    private func finir(_ raison: String) {
        file.async { [weak self] in self?.finirSurFile(raison) }
    }

    private func finirSurFile(_ raison: String) {
        guard actif else { return }
        arreterSurFile()
        let rappel = surFin
        DispatchQueue.main.async { rappel?(raison) }
    }

    private func arreterSurFile() {
        let etaitActif = actif || ecouteur != nil
        actif = false
        veille?.cancel()
        veille = nil
        for o in observateurs { NotificationCenter.default.removeObserver(o) }
        observateurs = []
        sonEnCours = false
        interrompu = false
        ecouteur?.cancel()
        ecouteur = nil
        for c in connexions { c.cancel() }
        connexions = []
        lecteur?.stop()
        moteur?.stop()
        lecteur = nil
        moteur = nil
        if etaitActif {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }
}

struct ErreurSon: LocalizedError {
    let message: String
    init(_ m: String) { message = m }
    var errorDescription: String? { return message }
}
