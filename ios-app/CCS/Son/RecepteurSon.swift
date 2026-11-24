import AVFoundation
import Foundation
import Network

/**
 * Sortie audio de l'iPhone : écoute en UDP (Network.framework) le flux RTP/Opus d'une source du
 * réseau maillé, le remet en ordre (tampon de gigue), le décode (Opus d'Apple) et le joue par
 * `AVAudioEngine`. L'horloge est celle de la carte son : chaque tampon joué en demande un autre
 * au tampon de gigue (trois de 20 ms toujours programmés d'avance). Session `.playback` : le son
 * continue en arrière-plan (`UIBackgroundModes: audio`). Arrêt sur demande ou après 10 s sans paquet.
 *
 * Tout se passe sur la file `file` ; `surFin` est rappelé sur le fil principal.
 */
final class RecepteurSon: @unchecked Sendable {
    /// Rappelé (fil principal) quand l'écoute s'arrête d'elle-même : raison.
    var surFin: ((String) -> Void)?

    private let file = DispatchQueue(label: "ccs.son.recepteur", qos: .userInteractive)
    private var ecouteur: NWListener?
    private var connexions: [NWConnection] = []
    /// Créés au départ de l'écoute seulement (pas de sortie audio touchée au lancement de l'appli).
    private var moteur: AVAudioEngine?
    private var lecteur: AVAudioPlayerNode?
    private var decodeur: DecodeurOpus?
    private var tampon = TamponGigue()
    private var enVol = 0
    private var actif = false
    private var dernierPaquet = Date()
    private var veille: DispatchSourceTimer?
    private var source: UInt32?
    private var observateur: NSObjectProtocol?

    /// Paquets reçus et perdus depuis le départ (pour l'écran Son).
    var bilan: (recues: Int, perdues: Int) {
        return file.sync { (tampon.recues, tampon.perdues) }
    }

    /// Se met à écouter sur `port` (UDP). Lance l'erreur si le port ou le son sont indisponibles.
    func demarrer(port: Int) throws {
        try file.sync {
            arreterSurFile()
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
            try session.setActive(true)
            guard let d = DecodeurOpus() else { throw ErreurSon("Décodeur Opus indisponible sur cet iPhone.") }
            decodeur = d
            tampon = TamponGigue(depart: 3, maximum: 7)
            source = nil
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
            for _ in 0..<3 { programmer() }
            observateur = NotificationCenter.default.addObserver(
                forName: .AVAudioEngineConfigurationChange, object: m, queue: nil) { [weak self] _ in
                self?.file.async { self?.relancerMoteur() }
            }
            let t = DispatchSource.makeTimerSource(queue: file)
            t.schedule(deadline: .now() + 1, repeating: 1)
            t.setEventHandler { [weak self] in
                guard let s = self, s.actif else { return }
                if Date().timeIntervalSince(s.dernierPaquet) > Son.silenceMax {
                    s.finirSurFile("Plus rien reçu depuis 10 s.")
                }
            }
            t.resume()
            veille = t
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
        if let s = source, s != e.ssrc { tampon = TamponGigue(depart: 3, maximum: 7) }
        source = e.ssrc
        dernierPaquet = Date()
        tampon.ajouter(sequence: e.sequence, trame)
    }

    // MARK: lecture

    /// Programme les 20 ms suivantes : trame décodée, ou silence (perte, attente).
    private func programmer() {
        guard actif, let lecteur = lecteur else { return }
        var tampon20: AVAudioPCMBuffer?
        if case .trame(let t) = tampon.sortir() { tampon20 = decodeur?.decoder(t) }
        guard let b = tampon20 ?? FormatsSon.silence() else { return }
        enVol += 1
        lecteur.scheduleBuffer(b, completionCallbackType: .dataConsumed) { [weak self] _ in
            guard let s = self else { return }
            s.file.async {
                s.enVol = max(0, s.enVol - 1)
                if s.actif && s.enVol < 3 { s.programmer() }
            }
        }
    }

    private func relancerMoteur() {
        guard actif, let moteur = moteur, let lecteur = lecteur else { return }
        if !moteur.isRunning { try? moteur.start() }
        if !lecteur.isPlaying { lecteur.play() }
        enVol = 0
        for _ in 0..<3 { programmer() }
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
        if let o = observateur { NotificationCenter.default.removeObserver(o) }
        observateur = nil
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
