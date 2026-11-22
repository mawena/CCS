import SwiftUI
import UIKit

/// Image jointe au prochain message.
struct PieceJointe: Identifiable, Equatable {
    let id = UUID()
    let typeMedia: String
    let base64: String
    let apercu: UIImage?
    let nom: String

    static func == (a: PieceJointe, b: PieceJointe) -> Bool { return a.id == b.id }
}

/// Ce que montre l'écran du chat, publié au plus toutes les 40 ms pendant une réponse.
struct VueChat {
    var lignes: [LigneFil] = []
    var agents: [VueAgent] = []
    var agentVu: String? = nil
    var lignesAgent: [LigneFil] = []
    var taches: [Tache] = []
    var etat = "starting"
    var reflechit = false
    var contexte = ""
    /// Couleur de « Contexte … » : vert, orange, rouge selon le seuil du contexte lourd.
    var niveauContexte: Jetons.Niveau? = nil
    var cout = ""
    var historiqueComplet = true
    /// Erreur d'ouverture (`chat.open` refusé).
    var ouverture: String? = nil
    /// Chat ouvert et rattaché une fois.
    var pret = false
}

/// Options du chat telles que l'écran les montre ; `pretes` : les vraies options sont connues.
struct ReglagesChat {
    var options = OptionsChat()
    var pretes = false
    var modeles: [ModeleIa] = []
}

/**
 * Un chat ouvert (`ChatView` de `web/chat.js`) : ouverture ou reprise (`chat.open`), rattachement
 * numéroté (`chat.attach` depuis le dernier numéro, après chaque reconnexion), historique du
 * journal, envoi, autorisations, questions, commandes `!`, étiquettes, contexte et coût.
 */
@MainActor
@Observable
final class ModeleChat {
    static let limite = 200
    static let maxImages = 5

    private let client: CcsClient
    private let avis: Avis
    let dest: DestChat
    private let fil = FilChat()

    private(set) var chatId: String? = nil
    private(set) var cwd: String
    @ObservationIgnored private var chemin: String? = nil
    @ObservationIgnored private var historique: Historique? = nil
    @ObservationIgnored private var sessionVue: String?             // session vue par le pont (une reprise peut en changer)
    @ObservationIgnored private var attache: Task<Void, Never>? = nil
    @ObservationIgnored private var demarre = false

    private final class Historique {
        let chemin: String
        var demarre = false
        var avant: Double? = nil
        var charges = 0
        var complet = false
        init(_ chemin: String) { self.chemin = chemin }
    }

    private(set) var vue = VueChat()
    /// Fichiers du projet (`work.files`, chemins relatifs) : liens des chemins cités par Claude.
    private(set) var fichiers: Set<String> = []
    @ObservationIgnored private var chargeFichiers = false

    /// Relit la liste des fichiers du projet (après un tour : Claude a pu en créer).
    func chargerFichiers() {
        guard let id = chatId, !chargeFichiers else { return }
        chargeFichiers = true
        Task { @MainActor [weak self] in
            guard let s = self else { return }
            if let r = try? await s.client.appeler("work.files", ["chat_id": .chaine(id)], delai: 20, en: IndexFichiers.self) {
                let f = Set(r.files)
                if f != s.fichiers { s.fichiers = f }
            }
            s.chargeFichiers = false
        }
    }
    private(set) var reglages = ReglagesChat()
    private(set) var citation: Citation.Cite? = nil
    private(set) var images: [PieceJointe] = []
    private(set) var saisie: String
    private(set) var envoiEnCours = false
    /// Message retenu : le cache a expiré, il relirait ce nombre de tokens au prix fort (confirmation).
    private(set) var confirmationCache: Int? = nil
    private(set) var etiquettes: [String: EntreeEtiquettes] = [:]
    private(set) var connues: [String] = []
    private(set) var commandes: [CommandeSlash] = []

    @ObservationIgnored private var sessionEtiquettes: String? = nil
    @ObservationIgnored private var shells: [String: String] = [:]         // run_id → clé de la carte
    @ObservationIgnored private var shellsTot: [String: JSON] = [:]        // fins arrivées avant la réponse du pont
    @ObservationIgnored private var notesShell: [String] = []
    @ObservationIgnored private var lourd = false
    @ObservationIgnored private var reglagesContexte: (actif: Bool, seuil: Int)? = nil
    @ObservationIgnored private var publication: Task<Void, Never>? = nil
    @ObservationIgnored private var contexteTache: Task<Void, Never>? = nil
    @ObservationIgnored private var brouillonTache: Task<Void, Never>? = nil
    @ObservationIgnored private var commandesTache: Task<Void, Never>? = nil
    @ObservationIgnored private var agentVu: String? = nil

    init(client: CcsClient, avis: Avis, dest: DestChat) {
        self.client = client
        self.avis = avis
        self.dest = dest
        self.chatId = dest.chatId
        self.cwd = dest.cwd
        self.chemin = dest.chemin
        self.historique = dest.chemin.map { Historique($0) }
        self.saisie = Prefs.lire("brouillon:" + dest.cle) ?? ""
        lireCitation()
    }

    var sessionId: String? { return fil.sessionId }

    /// Démarre une fois (premier affichage) : abonnements, ouverture, rattachement.
    func demarrer() {
        if demarre { return }
        demarre = true
        client.ecouter("chat.event", pour: self) { [weak self] d in
            guard let s = self, let id = s.chatId, d.texte("chat_id") == id else { return }
            s.recevoir(d)
        }
        client.ecouter("chat.tags", pour: self) { [weak self] d in
            guard let s = self else { return }
            let sid = d.texte("session_id")
            if !sid.isEmpty && sid == s.fil.sessionId { s.appliquerEtiquette(d.texte("msg_id"), EvChat.etiquettes(d["entry"])) }
        }
        client.ecouter("shell.done", pour: self) { [weak self] d in
            guard let s = self, let id = s.chatId, d.texte("chat_id") == id else { return }
            s.finShell(d)
        }
        client.ecouterReconnexions(pour: self) { [weak self] in
            guard let s = self else { return }
            s.attacher()
            Task { @MainActor in await s.sonderShells() }
        }
        Task { @MainActor in
            await ouvrir()
            await envoyerPrevu()
        }
    }

    /// Écran quitté : le brouillon est gardé.
    func quitter() {
        sauverBrouillon()
    }

    /**
     * Texte prévu à l'ouverture (« Faire… » d'une tâche de la feuille de route dans un nouveau
     * chat) : envoyé une seule fois, même si l'écran est recréé.
     */
    private func envoyerPrevu() async {
        guard let texte = dest.aEnvoyer, let jeton = dest.jeton else { return }
        let cle = "envoye:" + jeton
        if chatId == nil || Prefs.lire(cle) != nil { return }
        Prefs.ecrire(cle, "1")
        _ = await livrer(texte, [], nil) { [weak self] in self?.envoyerTexte(texte) }
    }

    // MARK: ouverture et rattachement

    /// Conversation de l'historique sans chat dans le pont : on la reprend (`chat.open`), comme le web.
    private func ouvrir() async {
        if chatId == nil {
            var params: [String: JSON] = ["cwd": .chaine(cwd)]
            if let s = dest.sessionId { params["session_id"] = .chaine(s) }
            do {
                let r = try await client.appeler("chat.open", params, delai: 60, en: ChatOuvert.self)
                adopter(r)
            } catch {
                vue.ouverture = texteErreur(error)
                return
            }
        }
        attacher()
    }

    private func adopter(_ r: ChatOuvert) {
        chatId = r.chatId
        if !r.cwd.isEmpty { cwd = r.cwd }
        if chemin == nil, let p = r.path {
            chemin = p
            if historique == nil { historique = Historique(p) }
        }
        fil.definirSession(r.sessionId ?? dest.sessionId)
        if let o = r.options { appliquerOptions(o) }
        if r.seq == 0 { fil.changerEtat("starting") }
    }

    func reessayerOuverture() {
        vue.ouverture = nil
        Task { @MainActor in await ouvrir() }
    }

    /// Les rattachements se font l'un après l'autre (ouverture puis reconnexion rapprochées).
    func attacher() {
        let precedent = attache
        attache = Task { @MainActor [weak self] in
            _ = await precedent?.value
            await self?.rattacher()
        }
    }

    private func demanderAttache(_ depuis: Int) async -> JSON? {
        guard let id = chatId else { return nil }
        do {
            return try await client.appeler("chat.attach", ["chat_id": .chaine(id), "since": .de(depuis)])
        } catch let e as RpcErreur {
            if e.code == "introuvable" {
                perdu()
            } else if e.code != "hors_ligne" {
                fil.note(e.message, genre: "error")
                publier()
            }
            return nil
        } catch {
            return nil
        }
    }

    private func rattacher() async {
        guard chatId != nil else { return }
        guard var r = await demanderAttache(fil.seq) else { return }
        let seqPont = r.entierOuNul("seq")
        let sid = r.texte("session_id")
        let enRetard = seqPont != nil && seqPont! < fil.seq
        let autre = !sid.isEmpty && sessionVue != nil && sid != sessionVue
        if enRetard || autre {
            remettreAZero(nouvelleSession: autre)
            guard let r2 = await demanderAttache(0) else { return }
            r = r2
        }
        if !sid.isEmpty {
            fil.definirSession(sid)
            sessionVue = sid
            chargerEtiquettes()
        }
        let p = r.texte("path")
        if !p.isEmpty {
            if chemin == nil { chemin = p }
            if historique == nil && !autre { historique = Historique(p) }
        }
        if let o = r["options"], case .objet = o {
            appliquerOptions(OptionsChat(json: o))
        } else if !reglages.pretes {
            reglages.pretes = true
        }
        fil.repris()
        for item in r.liste("events") { traiter(item) }
        fil.changerEtat(r.texte("state"))
        vue.pret = true
        publier(tout: true)
        await demarrerHistorique(r.doubleOuNul("history_before"))
    }

    private func remettreAZero(nouvelleSession: Bool) {
        sessionVue = nil
        fil.remettreAZero()
        shells.removeAll()
        shellsTot.removeAll()
        agentVu = nil
        lourd = false
        if nouvelleSession {
            historique = nil
        } else if let h = historique {
            historique = Historique(h.chemin)
        }
    }

    /// Le pont ne connaît plus ce chat (redémarrage) : carte « Reprendre la conversation ».
    private func perdu() {
        if let h = historique, !h.demarre {
            Task { @MainActor in await demarrerHistorique(nil) }
        }
        fil.arrete(reprenable: fil.sessionId != nil)
        publier(tout: true)
    }

    func reprendre() {
        guard let sid = fil.sessionId else { return }
        Task { @MainActor in
            do {
                let r = try await client.appeler("chat.open", ["cwd": .chaine(cwd), "session_id": .chaine(sid)], delai: 60, en: ChatOuvert.self)
                fil.repris()
                remettreAZero(nouvelleSession: false)
                if let p = r.path ?? chemin { historique = Historique(p) } else { historique = nil }
                adopter(r)
                attacher()
            } catch {
                avis.dire(texteErreur(error), action: "Réessayer") { [weak self] in self?.reprendre() }
            }
        }
    }

    // MARK: événements

    private func recevoir(_ d: JSON) {
        traiter(d)
        publier()
    }

    private func traiter(_ item: JSON) {
        guard let brut = item["event"], case .objet = brut else { return }
        let ev = EvChat.lire(brut)
        let numero = item.entier("seq")
        let effets = fil.recevoir(numero, ev)
        if case .etiquettesChangees(let sid, let msgId, let entree) = ev, sid == fil.sessionId {
            appliquerEtiquette(msgId, entree)
        }
        if case .statut = ev, let d = fil.droitsAnnonces {
            reglages.options.rights = d
        }
        for e in effets {
            switch e {
            case .sessionConnue:
                sessionVue = fil.sessionId
                chargerEtiquettes()
            case .nouveauHello:
                reglages.modeles = fil.modeles
                if !fil.commandes.isEmpty { commandes = fil.commandes }
            case .demanderContexte:
                demanderContexte()
            case .tourFini:
                lireCout()
            case .mesureContexte:
                if let c = fil.contexte { verifierContexte(c) }
            case .autorisationArrivee:
                agentVu = nil        // la demande est dans le fil : on y revient
            }
        }
    }

    /// Publie la vue ; pendant une réponse, au plus toutes les 40 ms (un seul calcul pour plusieurs morceaux).
    private func publier(tout: Bool = false) {
        if tout {
            publication?.cancel()
            publication = nil
            calculer()
            return
        }
        if publication != nil { return }
        publication = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 40_000_000)
            guard let s = self, !Task.isCancelled else { return }
            s.publication = nil
            s.calculer()
        }
    }

    private func calculer() {
        var v = vue
        v.lignes = LigneFil.de(fil.fil.elements)
        v.agents = fil.vuesAgents
        v.agentVu = agentVu
        v.lignesAgent = agentVu.map { LigneFil.de(fil.filAgent($0)) } ?? []
        v.taches = fil.taches
        v.etat = fil.etat
        v.reflechit = fil.reflechit
        let seuil = reglagesContexte?.seuil ?? 0          // 0 : seuil par défaut (150 000)
        if let c = fil.contexte, c.total > 0 {
            v.contexte = "Contexte \(c.pourcentage) %"
            v.niveauContexte = Jetons.niveau(c.total, seuil: seuil)
        } else if let u = fil.dernierUsage, u.contexte > 0 {
            v.contexte = "Contexte \(Jetons.court(u.contexte))"
            v.niveauContexte = Jetons.niveau(u.contexte, seuil: seuil)
        } else {
            v.contexte = fil.contexte.map { "Contexte \($0.pourcentage) %" } ?? ""
            v.niveauContexte = nil
        }
        v.historiqueComplet = historique?.complet ?? true
        vue = v
    }

    func voirAgent(_ id: String?) {
        agentVu = id
        publier(tout: true)
    }

    // MARK: historique

    private func demarrerHistorique(_ avant: Double?) async {
        guard let h = historique, !h.demarre else { return }
        h.demarre = true
        h.avant = avant
        guard let r = await lireHistorique(h, ModeleChat.limite) else {
            h.demarre = false
            return
        }
        if historique !== h { return }
        h.charges = r.count
        h.complet = r.count < ModeleChat.limite
        fil.prefixerHistorique(r)
        publier(tout: true)
    }

    private func lireHistorique(_ h: Historique, _ limite: Int) async -> [MessageHistorique]? {
        var params: [String: JSON] = ["path": .chaine(h.chemin), "limit": .de(limite)]
        if let a = h.avant { params["before"] = .nombre(a) }
        do {
            return try await client.appeler("conversations.messages", params, delai: 60, en: Messages.self).messages
        } catch let e as RpcErreur {
            return e.code == "introuvable" ? [] : nil      // chat neuf : pas encore de journal
        } catch {
            return nil
        }
    }

    /// Pour la recherche et les étiquettes : ajoute les messages plus anciens que les 200 derniers.
    func chargerToutHistorique() async {
        guard let h = historique, !h.complet, h.demarre else { return }
        h.complet = true
        guard let r = await lireHistorique(h, 100_000) else {
            h.complet = false
            return
        }
        if historique !== h { return }
        fil.prefixerHistorique(Array(r.prefix(max(0, r.count - h.charges))))
        h.charges = r.count
        publier(tout: true)
    }

    func chargerPlus() {
        Task { @MainActor in await chargerToutHistorique() }
    }

    // MARK: options

    private func appliquerOptions(_ o: OptionsChat) {
        var p = o
        p.rights = (o.rights == "default" || o.rights.isEmpty) ? "manual" : o.rights
        reglages.options = p
        reglages.pretes = true
    }

    func changerOptions(_ o: OptionsChat) {
        if !reglages.pretes { return }
        reglages.options = o
        appel("chat.options", ["options": o.enJSON])
    }

    // MARK: saisie, citation, images

    private var cleBrouillon: String { return "brouillon:" + dest.cle }
    private var cleCitation: String { return "citation:" + dest.cle }

    func saisir(_ t: String) {
        saisie = t
        brouillonTache?.cancel()
        brouillonTache = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 300_000_000)
            if Task.isCancelled { return }
            self?.sauverBrouillon()
        }
        if t.hasPrefix("/") && commandes.isEmpty { chargerCommandes() }
    }

    private func sauverBrouillon() {
        Prefs.ecrire(cleBrouillon, saisie.isEmpty ? nil : saisie)
    }

    func citer(_ c: Citation.Cite?) {
        citation = c
        Prefs.ecrire(cleCitation, c.map { $0.auteur.rawValue + "\n" + $0.texte })
    }

    private func lireCitation() {
        guard let brut = Prefs.lire(cleCitation), let fin = brut.firstIndex(of: "\n") else { return }
        guard let auteur = Citation.Auteur(rawValue: String(brut[brut.startIndex..<fin])) else { return }
        let texte = String(brut[brut.index(after: fin)...])
        if !texte.isEmpty { citation = Citation.Cite(auteur: auteur, texte: texte) }
    }

    func joindre(_ p: PieceJointe) {
        if images.count < ModeleChat.maxImages { images.append(p) }
    }

    func retirerImage(_ p: PieceJointe) {
        images.removeAll { $0.id == p.id }
    }

    func dire(_ texte: String) { avis.dire(texte) }

    private func chargerCommandes() {
        guard let id = chatId else { return }
        if commandesTache != nil { return }
        commandesTache = Task { @MainActor [weak self] in
            guard let s = self else { return }
            if let r = try? await s.client.appeler("work.commands", ["chat_id": .chaine(id)]) {
                s.lireReglagesContexte(r)
                let liste = r.liste("commands").compactMap { c -> CommandeSlash? in
                    let n = c.texte("name")
                    return n.isEmpty ? nil : CommandeSlash(nom: n, description: c.texte("description"), indice: c.texte("hint"))
                }
                if !liste.isEmpty { s.commandes = liste }
            }
            s.commandesTache = nil
        }
    }

    // MARK: envoi

    /// Bouton Envoyer : commande `!`, sinon message (avec images et citation). Cache expiré
    /// depuis le dernier tour : confirmation d'abord (le message relirait tout le contexte).
    func envoyer() {
        let texte = saisie.trimmingCharacters(in: .whitespacesAndNewlines)
        let imgs = images
        if (texte.isEmpty && imgs.isEmpty) || envoiEnCours { return }
        if let cmd = Envoi.commandeShell(texte, images: imgs.count) {
            saisir("")
            lancerShell(cmd)
            return
        }
        if let n = fil.cacheExpire, !(Envoi.estCommandeSlash(texte) && imgs.isEmpty) {
            confirmationCache = n
            return
        }
        envoyerMaintenant()
    }

    /// « Envoyer quand même » : le message part malgré le cache expiré.
    func envoyerQuandMeme() {
        confirmationCache = nil
        envoyerMaintenant()
    }

    /// « Compacter d'abord » : `/compact`, le message reste dans la saisie.
    func compacterDabord() {
        confirmationCache = nil
        envoyerTexte("/compact")
    }

    func annulerEnvoi() { confirmationCache = nil }

    private func envoyerMaintenant() {
        let texte = saisie.trimmingCharacters(in: .whitespacesAndNewlines)
        let imgs = images
        if (texte.isEmpty && imgs.isEmpty) || envoiEnCours { return }
        envoiEnCours = true
        Task { @MainActor in
            let cite = citation
            let ok = await livrer(texte, imgs, cite) { [weak self] in self?.envoyerMaintenant() }
            if ok {
                let envoyees = Set(imgs.map { $0.id })
                images.removeAll { envoyees.contains($0.id) }
                if citation == cite && !(Envoi.estCommandeSlash(texte) && imgs.isEmpty) { citer(nil) }
                if saisie.trimmingCharacters(in: .whitespacesAndNewlines) == texte { saisir("") }
            }
            envoiEnCours = false
        }
    }

    /// Texte préparé ailleurs (bouton « Compacter ») : envoyé sans toucher à la saisie.
    func envoyerTexte(_ texte: String) {
        Task { @MainActor in
            _ = await livrer(texte, [], nil) { [weak self] in self?.envoyerTexte(texte) }
        }
    }

    private func livrer(_ texte: String, _ imgs: [PieceJointe], _ cite: Citation.Cite?, reessai: @escaping () -> Void) async -> Bool {
        guard let id = chatId else {
            avis.dire("Le chat n'est pas encore ouvert.")
            return false
        }
        let pret = Envoi.preparer(texte, images: imgs.count, citation: cite, notesShell: notesShell)
        let nonce = String(Int(Date().timeIntervalSince1970 * 1000), radix: 36) + "-" + String(Int.random(in: 0..<1_000_000_000), radix: 36)
        let uuid = Envoi.nouvelUuid()
        fil.retenirEnvoi(nonce)
        let params: [String: JSON] = [
            "chat_id": .chaine(id), "text": .chaine(pret.envoye), "shown": .chaine(pret.montre),
            "nonce": .chaine(nonce), "uuid": .chaine(uuid),
            "images": .tableau(imgs.map { JSON.objet(["media_type": .chaine($0.typeMedia), "data": .chaine($0.base64)]) }),
        ]
        let r: JSON
        do {
            r = try await client.appeler("chat.send", params, delai: 60)
        } catch {
            fil.oublierEnvoi(nonce)
            avis.dire("Le message n'est pas parti : " + texteErreur(error), action: "Réessayer", faire: reessai)
            return false
        }
        if !r.bool("ok") {
            fil.oublierEnvoi(nonce)
            avis.dire("Le message n'est pas parti : Claude n'a pas pu démarrer.", action: "Réessayer", faire: reessai)
            return false
        }
        if !pret.commande { notesShell.removeAll() }
        agentVu = nil
        let u = r.texte("uuid")
        fil.bulleToi(pret.montre, images: imgs.count, msgId: u.isEmpty ? uuid : u)
        publier(tout: true)
        return true
    }

    func interrompre() { appel("chat.interrupt") }

    func repondre(_ requestId: String, _ decision: String, _ motif: String = "") {
        appel("chat.answer", ["request_id": .chaine(requestId), "decision": .chaine(decision), "message": .chaine(motif)])
    }

    /// Réponses aux questions de Claude : question → texte, ou liste (choix multiple).
    func repondreQuestions(_ requestId: String, _ reponses: [String: JSON]) {
        appel("chat.questions", ["request_id": .chaine(requestId), "answers": .objet(reponses)])
    }

    private func appel(_ methode: String, _ params: [String: JSON] = [:]) {
        guard let id = chatId else { return }
        var p = params
        p["chat_id"] = .chaine(id)
        Task { @MainActor in
            do {
                _ = try await client.appeler(methode, p)
            } catch {
                fil.note(texteErreur(error), genre: "error")
                publier()
            }
        }
    }

    // MARK: commandes `!`

    private func lancerShell(_ commande: String) {
        guard let id = chatId else { return }
        let cle = fil.commande(commande)
        publier(tout: true)
        Task { @MainActor in
            let r: JSON
            do {
                r = try await client.appeler("shell.run", ["chat_id": .chaine(id), "command": .chaine(commande)])
            } catch {
                terminerShell(cle, commande, 127, texteErreur(error), false)
                return
            }
            let run = r.texte("run_id")
            shells[run] = cle
            fil.majCommande(cle) { c in
                var n = c
                n.runId = run
                return n
            }
            publier()
            if let tot = shellsTot.removeValue(forKey: run) { finShell(tot) }
        }
    }

    func arreterShell(_ runId: String) {
        Task { @MainActor in _ = try? await client.appeler("shell.stop", ["run_id": .chaine(runId)]) }
    }

    private func finShell(_ d: JSON) {
        let run = d.texte("run_id")
        guard let cle = shells.removeValue(forKey: run) else {
            shellsTot[run] = d
            return
        }
        var cmd = ""
        if case .commande(let c)? = fil.fil[cle] { cmd = c.commande }
        terminerShell(cle, cmd, d.entierOuNul("code") ?? -1, d.texte("output"), d.bool("truncated"))
    }

    private func terminerShell(_ cle: String, _ commande: String, _ code: Int, _ sortie: String, _ tronquee: Bool) {
        let texte = sortie + (tronquee ? "\n[sortie tronquée]" : "")
        fil.majCommande(cle) { c in
            var n = c
            n.code = code
            n.sortie = texte.isEmpty ? "(aucune sortie)" : texte
            return n
        }
        notesShell.append(Envoi.noteShell(commande, code: code, sortie: sortie, tronquee: tronquee))
        publier()
    }

    private func sonderShells() async {
        for run in Array(shells.keys) {
            guard let r = try? await client.appeler("shell.poll", ["run_id": .chaine(run)]) else { continue }
            if r.bool("done") { finShell(r) }
        }
    }

    // MARK: contexte et coût

    /// « Contexte N % » n'arrive qu'en réponse à chat.context : on le demande après chaque tour.
    private func demanderContexte() {
        contexteTache?.cancel()
        contexteTache = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 400_000_000)
            guard let s = self, !Task.isCancelled else { return }
            if s.fil.etat != "stopped" { s.appel("chat.context") }
        }
    }

    private func lireReglagesContexte(_ r: JSON) {
        guard let c = r["context"], case .objet = c else { return }
        reglagesContexte = (actif: c.bool("enabled"), seuil: c.entier("threshold_tokens"))
        publier()
    }

    private func verifierContexte(_ ev: MesureContexte) {
        Task { @MainActor in
            if reglagesContexte == nil, let id = chatId {
                if let r = try? await client.appeler("work.commands", ["chat_id": .chaine(id)]) { lireReglagesContexte(r) }
            }
            guard let rc = reglagesContexte else { return }
            let d = AlerteContexte.decider(ev, actif: rc.actif, seuil: rc.seuil, dejaLourd: lourd)
            lourd = d.lourd
            if let gain = d.gain {
                fil.note(
                    "Contexte lourd : \(Format.milliers(ev.total)) jetons. Compacter libérerait environ \(Format.milliers(gain)) jetons (estimation).",
                    genre: "warning", action: .compacter
                )
                publier()
            }
        }
    }

    private func lireCout() {
        Task { @MainActor in
            if chemin == nil {
                // chat neuf : le journal existe depuis le premier tour, le pont donne son chemin
                if let r = await demanderAttache(fil.seq) {
                    let p = r.texte("path")
                    if !p.isEmpty {
                        chemin = p
                        if historique == nil {
                            let h = Historique(p)
                            h.demarre = true
                            h.complet = true
                            historique = h
                        }
                    }
                }
            }
            guard let p = chemin else { return }
            if let c = try? await client.appeler("conversations.cost", ["path": .chaine(p)], en: Cout.self) {
                vue.cout = c.short
            }
        }
    }

    // MARK: étiquettes

    private func chargerEtiquettes() {
        guard let sid = fil.sessionId, sid != sessionEtiquettes else { return }
        sessionEtiquettes = sid
        Task { @MainActor in
            guard let r = try? await client.appeler("chat.tags", ["session_id": .chaine(sid)]) else { return }
            if fil.sessionId != sid { return }
            var t: [String: EntreeEtiquettes] = [:]
            for (k, v) in r["messages"]?.objet ?? [:] {
                if let e = EvChat.etiquettes(v) { t[k] = e }
            }
            etiquettes = t
            connues = r.listeTextes("known")
        }
    }

    private func appliquerEtiquette(_ msgId: String, _ e: EntreeEtiquettes?) {
        if msgId.isEmpty { return }
        if let e = e {
            etiquettes[msgId] = e
            let vues = Set(connues.map { $0.lowercased() })
            connues += e.etiquettes.filter { !vues.contains($0.lowercased()) }
        } else {
            etiquettes.removeValue(forKey: msgId)
        }
    }

    func etiqueter(_ msgId: String, _ liste: [String], texte: String, role: String) {
        guard let sid = fil.sessionId else { return }
        Task { @MainActor in
            do {
                let r = try await client.appeler("chat.tag", [
                    "session_id": .chaine(sid), "msg_id": .chaine(msgId), "text": .chaine(texte), "role": .chaine(role),
                    "tags": .de(liste),
                ])
                if fil.sessionId == sid { appliquerEtiquette(msgId, EvChat.etiquettes(r["entry"])) }
            } catch {
                avis.dire("Étiquettes non enregistrées : " + texteErreur(error))
            }
        }
    }
}
