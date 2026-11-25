import SwiftUI
import UIKit
import WebKit

/// État de l'appli : adresse du serveur, identifiants gardés, connexion, thème, avis.
@MainActor
@Observable
final class ModeleAppli {
    let client: CcsClient
    let avis: Avis
    /// Terminaux ouverts dans l'appli (ils survivent à la navigation).
    let terminaux: Terminaux
    /// Veille des chats : notifications locales (fin de tour, demande en attente).
    let veille: Veille
    /// Mot de passe root demandé par la machine pilotée (`root.*`) : feuille, bandeau, avis.
    let root: GardienRoot
    /// Oreille « bouton » de Jarvis (Plus → Jarvis, raccourci « Parler à Jarvis »).
    let jarvis: OreilleJarvis
    /// Appareil ouvert dans l'onglet Fichiers et sa connexion à part (autre que la machine pilotée).
    let fichiers: ConnexionFichiers
    /// Son partagé sur le réseau maillé : annonce, réception, envoi (écran Plus → Son).
    let son: SonPartage
    /// L'écran Son est à ouvrir (notification « Touchez pour envoyer le son vers X »).
    var ouvrirSon = false
    /// Partage reçu (« Ouvrir dans CCS », `ccs://partager`) : la feuille de partage s'ouvre.
    var partage: Partage? = nil
    /// Chat à ouvrir (toucher sur une notification, partage livré).
    var aOuvrir: DestChat? = nil
    /// Autres machines connues (dernière liste reçue, gardée si la connexion est coupée).
    private(set) var machines: [Machine] = ModeleAppli.lireMachines()
    /// Feuille « Machine pilotée » ouverte (bandeau, Sessions, Plus).
    var choixMachine = false
    /// Sessions ouvertes sur les autres machines (`machines.chats`), lues seulement quand on pilote ce serveur.
    private(set) var chatsAutres: [ChatsMachine] = []
    /// Lecture de `machines.chats` en cours (elle peut prendre plusieurs secondes).
    private(set) var chercheChatsAutres = false

    private(set) var adresse: String
    private(set) var identifiants: Identifiants? = nil
    /// Pourquoi on est revenu à l'écran de connexion (jeton révoqué…), affiché une fois.
    var avisConnexion: String? = nil
    private(set) var theme: Theme

    /// Coûts des conversations déjà lus (clé : chemin + date), demandés un à la fois.
    @ObservationIgnored var couts: [String: String] = [:]
    @ObservationIgnored private var fileCouts: Task<Void, Never>? = nil

    init() {
        let c = CcsClient()
        let av = Avis()
        client = c
        avis = av
        terminaux = Terminaux(client: c, dire: { m in av.dire(m) })
        veille = Veille(client: c)
        root = GardienRoot(client: c, dire: { m in av.dire(m) })
        jarvis = OreilleJarvis()
        fichiers = ConnexionFichiers(principal: c)
        son = SonPartage(client: c, dire: { m in av.dire(m) })
        let a = Prefs.adresse
        adresse = a
        theme = Prefs.theme
        let i = Coffre.lire()
        identifiants = (i?.serveur == a) ? i : nil
        client.surRefus = { [weak self] raison in
            self?.oublier()
            self?.avisConnexion = raison + " Reconnecte-toi."
        }
        veille.ouvrir = { [weak self] d in self?.aOuvrir = d }
        veille.ouvrirSon = { [weak self] in
            self?.ouvrirSon = true
            self?.son.demanderDiffusion()
        }
        jarvis.identifiants = { [weak self] in self?.identifiants }
        fichiers.identifiants = { [weak self] in self?.identifiants }
        if let i = identifiants { demarrer(i) }
    }

    private func demarrer(_ i: Identifiants) {
        guard i.portier else {
            client.demarrer(i)
            veille.demarrer()
            son.demarrer()
            return
        }
        // connexion Portier sans jeton d'appareil : on le demande une fois, avant le WebSocket
        Task { @MainActor in
            let jeton = await ApiHttp.jetonAppli(i, nom: ModeleAppli.nomModele())
            var j = i
            if let t = jeton {
                j.jeton = t
                Coffre.ecrire(j)
                self.identifiants = j
            }
            if self.identifiants != nil, case .arrete = self.client.etat { self.client.demarrer(j); self.veille.demarrer(); self.son.demarrer() }
        }
    }

    func changerTheme(_ t: Theme) {
        theme = t
        Prefs.theme = t
    }

    func connecte(_ i: Identifiants) {
        Coffre.ecrire(i)
        identifiants = i
        avisConnexion = nil
        client.demarrer(i)
        veille.demarrer()
        son.demarrer()
    }

    func deconnecter() {
        let portier = identifiants?.viaPortier == true
        // le pont oublie l'iPhone comme sortie et source audio (`audio.forget`, 2 s au plus)
        Task { @MainActor in
            await son.quitter()
            oublier()
            if portier {
                let magasin = WKWebsiteDataStore.default()
                magasin.removeData(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes(), modifiedSince: Date.distantPast) {}
            }
        }
    }

    nonisolated private static let cleMachines = "machines"

    nonisolated private static func lireMachines() -> [Machine] {
        guard let t = Prefs.lire(cleMachines), let d = t.data(using: .utf8) else { return [] }
        return (try? JSONDecoder().decode([Machine].self, from: d)) ?? []
    }

    /// Le choix de machine n'a de sens que s'il existe une autre machine (ou qu'on en pilote une).
    var choixMachinePossible: Bool { return !client.machine.isEmpty || !machines.isEmpty }

    /// Relit `machines.list` ; rend le message du serveur (ou nil). Garde l'ancienne liste en cas d'échec.
    @discardableResult
    func rafraichirMachines() async -> String? {
        guard let r = try? await client.appeler("machines.list", delai: 15, en: ListeMachines.self) else { return nil }
        let autres = r.autres
        if autres != machines { machines = autres }
        if let d = try? JSONEncoder().encode(autres) { Prefs.ecrire(ModeleAppli.cleMachines, String(decoding: d, as: UTF8.self)) }
        return r.message
    }

    /**
     * Relit les sessions des autres machines (`machines.chats`, demandé au serveur lui-même : seulement
     * quand il est la machine pilotée). Tout échec (ancien serveur sans la méthode, délai) : rien.
     */
    func rafraichirChatsAutres() async {
        guard client.machine.isEmpty, client.etat.estConnecte else {
            if !client.machine.isEmpty { chatsAutres = [] }
            return
        }
        if chercheChatsAutres { return }
        chercheChatsAutres = true
        defer { chercheChatsAutres = false }
        let r = try? await client.appeler("machines.chats", delai: 50, en: ChatsMachines.self)
        // machine changée pendant l'appel : la réponse ne vaut plus
        guard client.machine.isEmpty else { chatsAutres = []; return }
        let autres = r?.machines ?? []
        if autres != chatsAutres { chatsAutres = autres }
    }

    /**
     * Ouvre un chat d'une autre machine : elle devient la machine pilotée, puis le chat s'ouvre dès
     * que la connexion relayée est prête (20 s au plus ; sinon un avis).
     */
    func ouvrirSurMachine(_ id: String, nom: String, _ dest: DestChat) {
        choisirMachine(id, nom: nom)
        Task { @MainActor in
            for _ in 0..<80 {
                if self.client.machine != id { return }          // autre choix entre-temps
                if self.client.etat.estConnecte {
                    self.aOuvrir = dest
                    return
                }
                try? await Task.sleep(nanoseconds: 250_000_000)
            }
            if self.client.machine == id { self.avis.dire("« \(nom) » ne répond pas : le chat n'a pas pu s'ouvrir.") }
        }
    }

    /// Pilote `id` (vide : ce serveur) : terminaux et notifications de l'ancienne machine sont oubliés.
    func choisirMachine(_ id: String, nom: String) {
        if id == client.machine { return }
        terminaux.oublier()
        veille.oublierChats()
        root.vider()
        fichiers.fermer()
        client.changerMachine(id, nom: nom)
    }

    private func oublier() {
        client.arreter()
        Coffre.ecrire(nil)
        identifiants = nil
        couts = [:]
        terminaux.oublier()
        veille.arreter()
        root.vider()
        jarvis.fermer()
        fichiers.oublier()
        son.arreter()
    }

    /// Coût court d'une conversation (« 0,42 $ ») ; le coût est un plus : un échec est tu.
    func cout(chemin: String, cle: String) async -> String? {
        if let c = couts[cle] { return c }
        let precedent = fileCouts
        let t = Task { @MainActor () -> String? in
            _ = await precedent?.value
            if let c = self.couts[cle] { return c }
            guard let r = try? await self.client.appeler("conversations.cost", ["path": .chaine(chemin)], en: Cout.self) else { return nil }
            self.couts[cle] = r.short
            return r.short
        }
        fileCouts = Task { @MainActor in _ = await t.value }
        return await t.value
    }

    /// Rend false si l'adresse est invalide.
    func changerAdresse(_ texte: String) -> Bool {
        guard let a = Prefs.changerAdresse(texte) else { return false }
        adresse = a
        return true
    }

    /// Modèle de l'appareil (`iPhone14,2`), pour nommer le jeton d'appareil.
    static func identifiantMateriel() -> String {
        var u = utsname()
        uname(&u)
        let brut = withUnsafeBytes(of: &u.machine) { (p: UnsafeRawBufferPointer) -> String in
            let octets = p.prefix { $0 != 0 }
            return String(decoding: octets, as: UTF8.self)
        }
        return brut.isEmpty ? UIDevice.current.model : brut
    }

    /// Nom du jeton demandé après Portier.
    static func nomModele() -> String {
        return String("\(UIDevice.current.model) \(identifiantMateriel())".prefix(60))
    }

    /// Nom de l'appareil donné à l'appairage.
    static func nomAppareil() -> String {
        return String("Appli iOS (\(UIDevice.current.model) \(identifiantMateriel()))".prefix(60))
    }
}
