import AppIntents
import Observation

/**
 * Ce qui demande l'écran Jarvis depuis l'extérieur : raccourci « Parler à Jarvis » (App Intent),
 * lien `ccs://jarvis`, adresse d'appairage `jarvis://pair?…` (QR code scanné par l'appareil photo).
 * L'écran principal ouvre Plus → Jarvis ; l'écran Jarvis prend la demande (écoute ou adresse).
 */
@MainActor
@Observable
final class DemandeJarvis {
    static let partage = DemandeJarvis()

    /// Change à chaque demande (l'écran principal s'y abonne).
    private(set) var compteur = 0
    @ObservationIgnored private var ecouter = false
    @ObservationIgnored private var adresse: String? = nil
    @ObservationIgnored private var vu = 0

    private init() {}

    /// Ouvre l'écran Jarvis, déjà en écoute (fin au silence).
    func demanderEcoute() {
        ecouter = true
        compteur += 1
    }

    /// Ouvre l'écran Jarvis avec l'adresse d'appairage remplie.
    func demanderAppairage(_ uri: String) {
        adresse = uri
        compteur += 1
    }

    /// Vrai une fois par demande : l'écran principal ouvre alors l'écran Jarvis.
    func prendreOuverture() -> Bool {
        defer { vu = compteur }
        return compteur != vu
    }

    func prendreEcoute() -> Bool {
        defer { ecouter = false }
        return ecouter
    }

    func prendreAdresse() -> String? {
        defer { adresse = nil }
        return adresse
    }
}

/// « Parler à Jarvis » (Raccourcis, Siri, bouton Action) : ouvre CCS sur le bouton, en écoute.
struct IntentionParlerAJarvis: AppIntent {
    static var title: LocalizedStringResource = "Parler à Jarvis"
    static var description = IntentDescription("Ouvre CCS sur le bouton de Jarvis, déjà en écoute : parle, l'écoute s'arrête quand tu te tais.")
    static var openAppWhenRun: Bool = true

    @MainActor
    func perform() async throws -> some IntentResult {
        DemandeJarvis.partage.demanderEcoute()
        return .result()
    }
}

struct RaccourcisCCS: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: IntentionParlerAJarvis(),
            phrases: ["Parler à Jarvis avec \(.applicationName)", "Jarvis dans \(.applicationName)"],
            shortTitle: "Parler à Jarvis",
            systemImageName: "waveform"
        )
    }
}
