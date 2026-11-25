import Foundation
import AVFoundation
import Observation
import UIKit

/**
 * Oreille « bouton » de Jarvis : appairage (gardé dans le trousseau), un lien gardé ouvert tant
 * qu'on s'en sert (fermé après 2 min sans phrase), une phrase à la fois. Le micro tourne dès
 * l'appui ; son son attend le lien (tunnel Ricochet ouvert par le serveur) puis part en trames de
 * 100 ms. La réponse s'affiche et la voix de Jarvis est jouée ; s'il attend un oui / non, l'écoute
 * reprend toute seule (fin au silence).
 */
@MainActor
@Observable
final class OreilleJarvis {
    enum Genre { case moi, jarvis, erreur }

    struct Ligne: Identifiable {
        let id = UUID()
        let qui: String
        let texte: String
        let genre: Genre
    }

    private(set) var appairage: AppairageJarvis? = CoffreJarvis.lire()
    /// Texte d'état (vide : « Prêt. »).
    private(set) var etat = ""
    /// Le micro écoute (de l'appui à la fin de la phrase).
    private(set) var ecoute = false
    private(set) var journal: [Ligne] = []

    /// Identifiants du serveur CCS (ceux de l'appli).
    @ObservationIgnored var identifiants: () -> Identifiants? = { nil }

    @ObservationIgnored private var lien: LienJarvis? = nil
    @ObservationIgnored private var connexion: Task<LienJarvis, Error>? = nil
    @ObservationIgnored private var phrase: PhraseJarvis? = nil
    @ObservationIgnored private var numero = UInt32.random(in: 0..<0x7fff_ffff)
    @ObservationIgnored private let moteur = AVAudioEngine()
    @ObservationIgnored private var micro = false
    @ObservationIgnored private var lecteur: AVAudioPlayer? = nil
    @ObservationIgnored private let delegueLecture = DelegueLecture()
    @ObservationIgnored private var inactivite: Task<Void, Never>? = nil

    private static let historique = 20

    var nomCerveau: String {
        let n = appairage?.brainName ?? ""
        return n.isEmpty ? "Jarvis" : n
    }

    // MARK: appairage

    /// Nom de ce téléphone pour `jarvis ears`.
    static func nomParDefaut() -> String {
        return String("CCS iPhone (\(ModeleAppli.identifiantMateriel()))".prefix(60))
    }

    /// `pair` avec le code de `jarvis pair` : le cerveau répond `paired` (jeton donné une fois) puis ferme.
    func appairer(_ cible: CibleAppairage, nom: String) async throws {
        guard let i = identifiants(), let url = Adresse.oreilleJarvis(i.serveur, empreinte: cible.empreinte) else {
            throw ErreurJarvis("Connecte d'abord l'appli au serveur CCS.")
        }
        let l = LienJarvis(url: url, identifiants: i, premier: Jarvis.pair(code: cible.code, nom: nom))
        let m = try await l.ouvrir()
        l.fermer()
        guard case .appaire(let earId, let jeton, let cerveauId, let nomCerveau) = m, !earId.isEmpty, !jeton.isEmpty else {
            throw ErreurJarvis("Réponse inattendue de Jarvis.")
        }
        let a = AppairageJarvis(earId: earId, token: jeton, fingerprint: cible.empreinte,
                                brainName: nomCerveau.isEmpty ? "Jarvis" : nomCerveau, brainId: cerveauId)
        CoffreJarvis.ecrire(a)
        fermer()
        journal = []
        appairage = a
    }

    /// Oublie l'appairage sur ce téléphone (« jarvis unpair » le retire aussi côté Jarvis).
    func oublier() {
        fermer()
        CoffreJarvis.ecrire(nil)
        appairage = nil
        journal = []
    }

    // MARK: phrase

    /// Début d'une phrase. `auto` : fin au silence (appui court) ; sinon `finir()` au relâché.
    /// `suite` : réponse à une question de Jarvis (`listen_start` au lieu de `wake`).
    func commencer(auto: Bool, suite: Bool = false) {
        guard phrase == nil, appairage != nil else { return }
        arreterLecture()
        Lecteur.partage.arreter()
        numero &+= 1
        let n = numero
        phrase = PhraseJarvis(numero: n, auto: auto, suite: suite, maintenant: Jarvis.maintenantMs())
        ecoute = true
        etat = "Écoute…"
        Task { @MainActor in
            guard await AVAudioApplication.requestRecordPermission() else {
                self.abandonner()
                self.signaler("Micro refusé : autorise-le pour CCS (Réglages → Confidentialité → Micro).")
                return
            }
            guard self.phrase?.numero == n else { return }
            do {
                try self.ouvrirMicro(n)
            } catch {
                self.abandonner()
                self.signaler("Micro indisponible : " + error.localizedDescription)
                return
            }
            let l: LienJarvis
            do {
                l = try await self.connecter()
            } catch {
                guard self.phrase?.numero == n else { return }
                self.abandonner()
                if let e = error as? ErreurJarvis, e.refus == "unknown_ear" || e.refus == "bad_token" {
                    CoffreJarvis.ecrire(nil)
                    self.appairage = nil
                }
                self.signaler(error.localizedDescription)
                return
            }
            guard self.phrase?.numero == n else { return }
            self.inactivite?.cancel()
            l.envoyer(suite ? Jarvis.listenStart(n) : Jarvis.wake(n))
            self.phrase?.prete = true
            self.envoyerTrames(toutes: false)
            if self.phrase?.finie == true { self.terminer() }
        }
    }

    /// Appui court : l'écoute s'arrêtera au silence.
    func passerEnAuto() {
        guard phrase != nil, ecoute else { return }
        phrase?.auto = true
        etat = "Écoute… (fin au silence, ou touche encore)"
    }

    /// Fin de la phrase (relâché, second appui, silence, 14 s) : `listen_end` dès que le lien est prêt.
    func finir() {
        guard var p = phrase, !p.finie else { return }
        p.finie = true
        phrase = p
        couperMicro()
        ecoute = false
        if p.prete { terminer() } else { etat = "Connexion à Jarvis…" }
    }

    /// Écran quitté, appli en arrière-plan, déconnexion : tout s'arrête.
    func fermer() {
        inactivite?.cancel()
        inactivite = nil
        abandonner()
        arreterLecture()
        connexion?.cancel()
        connexion = nil
        lien?.fermer()
        lien = nil
        relacherSession()
        etat = ""
    }

    // MARK: lien

    private func connecter() async throws -> LienJarvis {
        if let l = lien, l.pret { return l }
        if let c = connexion { return try await c.value }
        guard let a = appairage, let i = identifiants(), let url = Adresse.oreilleJarvis(i.serveur, empreinte: a.fingerprint) else {
            throw ErreurJarvis("Connecte d'abord l'appli au serveur CCS.")
        }
        let l = LienJarvis(url: url, identifiants: i, premier: Jarvis.hello(a))
        l.surMessage = { [weak self] m in self?.recu(m) }
        l.surFin = { [weak self, weak l] texte in self?.fin(l, texte) }
        let t = Task { @MainActor () throws -> LienJarvis in
            let premier = try await l.ouvrir()
            if case .bienvenue(let nom) = premier, !nom.isEmpty, var a = self.appairage, a.brainName != nom {
                a.brainName = nom
                CoffreJarvis.ecrire(a)
                self.appairage = a
            }
            return l
        }
        connexion = t
        defer { if connexion == t { connexion = nil } }
        let pret = try await t.value
        lien = pret
        armerInactivite()                   // annulé dès qu'une phrase part
        return pret
    }

    private func fin(_ l: LienJarvis?, _ texte: String?) {
        guard let l = l, l === lien else { return }
        lien = nil
        let attendait = phrase != nil || etat == "Jarvis réfléchit…"
        abandonner()
        etat = ""
        if let t = texte { signaler(t) } else if attendait { signaler("Lien avec Jarvis fermé.") }
    }

    private func recu(_ m: MessageCerveau) {
        switch m {
        case .stop(let n):
            if phrase?.numero == n {
                abandonner()
                signaler("Jarvis est occupé par une autre phrase : réessaie dans un instant.")
            }
        case .entendu(let texte, let voix, let audio, let attendReponse):
            armerInactivite()
            etat = ""
            ajouter("Toi", texte, .moi)
            ajouter(nomCerveau, voix, .jarvis)
            jouer(audio, puisEcouter: attendReponse)
        case .reponse(let voix):
            armerInactivite()
            etat = ""
            ajouter(nomCerveau, voix, .jarvis)
        case .erreur(let t):
            armerInactivite()
            etat = ""
            signaler(t)
        case .refus(let motif, let essais):
            signaler(Jarvis.texteRefus(motif, essais: essais))
        default:
            break
        }
    }

    private func armerInactivite() {
        inactivite?.cancel()
        inactivite = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: Jarvis.inactiviteS * 1_000_000_000)
            guard !Task.isCancelled, let s = self, s.phrase == nil else { return }
            s.lien?.fermer()
            s.lien = nil
            if s.lecteur == nil { s.relacherSession() }
        }
    }

    // MARK: son de la phrase

    private func morceau(_ n: UInt32, _ e: [Int16], _ fort: Bool) {
        guard var p = phrase, p.numero == n, !p.finie else { return }
        let stop = p.ajouter(e, fort: fort, maintenant: Jarvis.maintenantMs())
        phrase = p
        envoyerTrames(toutes: false)
        if stop { finir() }
    }

    private func envoyerTrames(toutes: Bool) {
        guard var p = phrase else { return }
        let trames = p.trames(toutes: toutes)
        phrase = p
        for t in trames { lien?.envoyer(t) }
    }

    private func terminer() {
        guard let p = phrase else { return }
        envoyerTrames(toutes: true)
        let vide = p.sansParole
        lien?.envoyer(Jarvis.listenEnd(p.numero, sansParole: vide))
        phrase = nil
        ecoute = false
        etat = vide ? "" : "Jarvis réfléchit…"
        if vide { signaler("Rien entendu.") }
        armerInactivite()
    }

    /// Phrase abandonnée (erreur, lien coupé, autre oreille) : `listen_end` sans parole si elle avait commencé.
    private func abandonner() {
        guard let p = phrase else { return }
        phrase = nil
        ecoute = false
        couperMicro()
        if p.prete && !p.finie { lien?.envoyer(Jarvis.listenEnd(p.numero, sansParole: true)) }
        etat = ""
    }

    private func ouvrirMicro(_ n: UInt32) throws {
        try activerSession()
        let entree = moteur.inputNode
        let format = entree.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else { throw ErreurJarvis("aucun micro disponible.") }
        entree.removeTap(onBus: 0)
        OreilleJarvis.brancher(entree, format, Reechantillonneur(frequence: format.sampleRate)) { [weak self] e, fort in
            self?.morceau(n, e, fort)
        }
        micro = true
        moteur.prepare()
        do {
            try moteur.start()
        } catch {
            couperMicro()
            throw error
        }
    }

    private func couperMicro() {
        guard micro else { return }
        micro = false
        if moteur.isRunning { moteur.stop() }
        moteur.inputNode.removeTap(onBus: 0)
    }

    /// Hors de l'acteur principal : le micro rappelle sur son propre fil ; les morceaux repartent
    /// dans l'ordre sur le fil principal.
    nonisolated private static func brancher(
        _ entree: AVAudioInputNode, _ format: AVAudioFormat, _ r: Reechantillonneur,
        _ rendre: @escaping @MainActor ([Int16], Bool) -> Void
    ) {
        entree.installTap(onBus: 0, bufferSize: 2048, format: format) { tampon, _ in
            guard let canal = tampon.floatChannelData?[0] else { return }
            let flottants = Array(UnsafeBufferPointer(start: canal, count: Int(tampon.frameLength)))
            let fort = Jarvis.rms(flottants) > Jarvis.seuilParole
            let e = r.pousser(flottants)
            DispatchQueue.main.async { MainActor.assumeIsolated { rendre(e, fort) } }
        }
    }

    // MARK: voix de Jarvis

    private func jouer(_ audio: VoixJarvis?, puisEcouter: Bool) {
        arreterLecture()
        let pcm = audio.map { Jarvis.decoderPcm($0.pcm) } ?? []
        guard let a = audio, !pcm.isEmpty, (try? activerSession()) != nil,
              let p = try? AVAudioPlayer(data: Jarvis.wav(pcm, frequence: a.frequence)) else {
            if puisEcouter { commencer(auto: true, suite: true) }
            return
        }
        delegueLecture.fini = { [weak self, weak p] in
            guard let s = self, let p = p, s.lecteur === p else { return }
            s.lecteur = nil
            if puisEcouter { s.commencer(auto: true, suite: true) } else if s.phrase == nil { s.relacherSession() }
        }
        p.delegate = delegueLecture
        lecteur = p
        p.play()
    }

    private func arreterLecture() {
        guard let p = lecteur else { return }
        lecteur = nil
        p.delegate = nil
        p.stop()
    }

    /// Micro et haut-parleur ensemble (la réponse à une question suit la voix de Jarvis).
    private func activerSession() throws {
        let s = AVAudioSession.sharedInstance()
        try s.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetooth, .duckOthers])
        try s.setActive(true)
    }

    /// Rend la main à l'audio des autres applis.
    private func relacherSession() {
        guard phrase == nil, lecteur == nil else { return }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    // MARK: journal

    private func ajouter(_ qui: String, _ texte: String, _ genre: Genre) {
        guard !texte.isEmpty else { return }
        journal.insert(Ligne(qui: qui, texte: texte, genre: genre), at: 0)
        if journal.count > OreilleJarvis.historique { journal.removeLast(journal.count - OreilleJarvis.historique) }
    }

    private func signaler(_ texte: String) {
        ajouter("", texte, .erreur)
        if !ecoute { etat = "" }
    }

    private final class DelegueLecture: NSObject, AVAudioPlayerDelegate {
        var fini: @MainActor () -> Void = {}

        func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
            let f = fini
            DispatchQueue.main.async { MainActor.assumeIsolated { f() } }
        }

        func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
            let f = fini
            DispatchQueue.main.async { MainActor.assumeIsolated { f() } }
        }
    }
}
