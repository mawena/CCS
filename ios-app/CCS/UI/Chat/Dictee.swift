import Foundation
import AVFoundation
import Speech
import Observation

/**
 * Dictée dans la saisie du chat (`SFSpeechRecognizer` fr-FR + `AVAudioEngine`) : un appui démarre,
 * un nouvel appui arrête ; arrêt tout seul après ~2 s de silence. Le texte reconnu s'ajoute en
 * direct à ce qui était déjà saisi, sans rien envoyer : on relit, puis on envoie.
 */
@MainActor
@Observable
final class Dictee {
    enum Etat { case arretee, demande, ecoute }

    private(set) var etat: Etat = .arretee

    @ObservationIgnored private let reconnaisseur = SFSpeechRecognizer(locale: Locale(identifier: "fr-FR"))
    @ObservationIgnored private let moteur = AVAudioEngine()
    @ObservationIgnored private var requete: SFSpeechAudioBufferRecognitionRequest? = nil
    @ObservationIgnored private var tache: SFSpeechRecognitionTask? = nil
    @ObservationIgnored private var silence: Task<Void, Never>? = nil
    /// Numéro de la dictée : les résultats d'une dictée précédente sont ignorés.
    @ObservationIgnored private var tour = 0
    /// Saisie au départ de la dictée.
    @ObservationIgnored private var base = ""
    @ObservationIgnored private var ecrire: (String) -> Void = { _ in }
    @ObservationIgnored private var dire: (String) -> Void = { _ in }

    /// Silence qui arrête la dictée (après un premier mot), et attente du premier mot.
    private static let delaiSilence: UInt64 = 2_000_000_000
    private static let delaiPremierMot: UInt64 = 6_000_000_000

    /// Démarre ou arrête. `ecrire` reçoit la saisie complète (saisie de départ + texte dicté).
    func basculer(depuis saisie: String, ecrire: @escaping (String) -> Void, dire: @escaping (String) -> Void) {
        if etat != .arretee {
            arreter()
            return
        }
        self.ecrire = ecrire
        self.dire = dire
        etat = .demande
        Task { @MainActor in
            let ok = await self.autoriser()
            guard self.etat == .demande else { return }        // arrêtée pendant la demande
            if ok { self.lancer(saisie) } else { self.etat = .arretee }
        }
    }

    func arreter() {
        switch etat {
        case .arretee:
            return
        case .demande:
            etat = .arretee
            return
        case .ecoute:
            break
        }
        etat = .arretee
        silence?.cancel()
        silence = nil
        couperMicro()
        requete?.endAudio()                 // le résultat final arrive encore (même tour)
        requete = nil
        let n = tour
        let t = tache
        Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            t?.cancel()
            if let s = self, s.tour == n { s.tache = nil }
        }
    }

    /// Arrêt sans suite (message envoyé, écran quitté) : le résultat final ne réécrit plus la saisie.
    func abandonner() {
        arreter()
        tour += 1
        tache?.cancel()
        tache = nil
    }

    // MARK: autorisations

    private func autoriser() async -> Bool {
        let statut = await withCheckedContinuation { (c: CheckedContinuation<SFSpeechRecognizerAuthorizationStatus, Never>) in
            SFSpeechRecognizer.requestAuthorization { s in c.resume(returning: s) }
        }
        switch statut {
        case .authorized:
            break
        case .restricted:
            dire("La reconnaissance vocale n'est pas permise sur ce téléphone.")
            return false
        default:
            dire("Dictée impossible : autorise la reconnaissance vocale pour CCS (Réglages → Confidentialité → Reconnaissance vocale).")
            return false
        }
        guard await AVAudioApplication.requestRecordPermission() else {
            dire("Dictée impossible : autorise le micro pour CCS (Réglages → Confidentialité → Micro).")
            return false
        }
        guard let r = reconnaisseur, r.isAvailable else {
            dire("Reconnaissance vocale indisponible pour le moment (réseau ?).")
            return false
        }
        return true
    }

    // MARK: écoute

    private func lancer(_ saisie: String) {
        guard let r = reconnaisseur else { etat = .arretee; return }
        Lecteur.partage.arreter()               // pas de lecture à voix haute pendant qu'on dicte
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.record, mode: .measurement, options: [.duckOthers])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            dire("Micro indisponible : " + error.localizedDescription)
            etat = .arretee
            return
        }
        let entree = moteur.inputNode
        guard entree.outputFormat(forBus: 0).sampleRate > 0 else {
            relacherSession()
            dire("Aucun micro disponible.")
            etat = .arretee
            return
        }
        tour += 1
        let n = tour
        base = saisie
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        req.addsPunctuation = true
        requete = req
        Dictee.brancher(entree, req)
        moteur.prepare()
        do {
            try moteur.start()
        } catch {
            couperMicro()
            requete = nil
            dire("Micro indisponible : " + error.localizedDescription)
            etat = .arretee
            return
        }
        etat = .ecoute
        tache = Dictee.reconnaitre(r, req) { [weak self] texte, fini, echec in
            self?.recevoir(n, texte, fini, echec)
        }
        attendreSilence(Dictee.delaiPremierMot)
    }

    private func recevoir(_ n: Int, _ texte: String?, _ fini: Bool, _ echec: Bool) {
        guard n == tour else { return }
        if let t = texte, !t.isEmpty {
            ecrire(TexteParle.joindre(base, t))
            if etat == .ecoute { attendreSilence(Dictee.delaiSilence) }
        }
        if fini || echec {
            if etat == .ecoute {
                if echec && texte == nil { dire("Rien entendu.") }
                arreter()
            }
            tache = nil
        }
    }

    /// (Re)lance le compte à rebours : sans nouveau résultat avant la fin, la dictée s'arrête.
    private func attendreSilence(_ delai: UInt64) {
        silence?.cancel()
        let n = tour
        silence = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: delai)
            guard !Task.isCancelled, let s = self, s.tour == n, s.etat == .ecoute else { return }
            s.arreter()
        }
    }

    private func couperMicro() {
        if moteur.isRunning { moteur.stop() }
        moteur.inputNode.removeTap(onBus: 0)
        relacherSession()
    }

    private func relacherSession() {
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    // Hors de l'acteur principal : le micro et la reconnaissance rappellent sur leurs propres files.

    nonisolated private static func brancher(_ entree: AVAudioInputNode, _ req: SFSpeechAudioBufferRecognitionRequest) {
        let format = entree.outputFormat(forBus: 0)
        entree.installTap(onBus: 0, bufferSize: 1024, format: format) { tampon, _ in
            req.append(tampon)
        }
    }

    nonisolated private static func reconnaitre(
        _ r: SFSpeechRecognizer,
        _ req: SFSpeechAudioBufferRecognitionRequest,
        _ rendre: @escaping @MainActor (String?, Bool, Bool) -> Void
    ) -> SFSpeechRecognitionTask {
        return r.recognitionTask(with: req) { resultat, erreur in
            let texte = resultat?.bestTranscription.formattedString
            let fini = resultat?.isFinal ?? false
            let echec = erreur != nil
            Task { @MainActor in rendre(texte, fini, echec) }
        }
    }
}
