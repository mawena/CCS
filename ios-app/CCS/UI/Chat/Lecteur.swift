import Foundation
import AVFoundation
import Observation

/**
 * Lecture à voix haute des réponses de Claude (`AVSpeechSynthesizer`, voix française) : une seule
 * à la fois pour toute l'appli. « Lire » dans le menu d'un message, ou chaque réponse terminée
 * quand le réglage « Lire les réponses à voix haute » est actif (`Prefs.lireReponses`).
 */
@MainActor
@Observable
final class Lecteur {
    static let partage = Lecteur()

    /// Clé (`ElementFil`) du message en cours de lecture.
    private(set) var enCours: String? = nil

    @ObservationIgnored private let synthe = AVSpeechSynthesizer()
    @ObservationIgnored private let delegue = Delegue()
    @ObservationIgnored private var phrase: AVSpeechUtterance? = nil

    private init() {
        synthe.delegate = delegue
        delegue.fini = { [weak self] u in self?.fini(u) }
    }

    func lit(_ cle: String) -> Bool { return enCours == cle }

    /// Second appui sur le même message : la lecture s'arrête.
    func basculer(_ cle: String, _ texte: String) {
        if lit(cle) { arreter() } else { lire(cle, texte) }
    }

    func lire(_ cle: String, _ markdown: String) {
        let texte = TexteParle.nettoyer(markdown)
        guard !texte.isEmpty else { return }
        if synthe.isSpeaking { synthe.stopSpeaking(at: .immediate) }
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try? session.setActive(true)
        let u = AVSpeechUtterance(string: texte)
        u.voice = AVSpeechSynthesisVoice(language: "fr-FR")
        u.rate = AVSpeechUtteranceDefaultSpeechRate
        phrase = u
        enCours = cle
        synthe.speak(u)
    }

    func arreter() {
        guard enCours != nil || synthe.isSpeaking else { return }
        phrase = nil
        enCours = nil
        synthe.stopSpeaking(at: .immediate)
        relacher()
    }

    /// Fin (ou annulation) d'une phrase : seule la phrase en cours compte (une nouvelle lecture remplace l'ancienne).
    private func fini(_ u: AVSpeechUtterance) {
        guard let p = phrase, p === u else { return }
        phrase = nil
        enCours = nil
        relacher()
    }

    /// Rend la main à l'audio des autres applis (la musique reprend son volume).
    private func relacher() {
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private final class Delegue: NSObject, AVSpeechSynthesizerDelegate {
        var fini: @MainActor (AVSpeechUtterance) -> Void = { _ in }

        func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
            signaler(utterance)
        }

        func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
            signaler(utterance)
        }

        private func signaler(_ u: AVSpeechUtterance) {
            let f = fini
            Task { @MainActor in f(u) }
        }
    }
}
