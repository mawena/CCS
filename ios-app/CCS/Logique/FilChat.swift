import Foundation

enum StatutAgent: Equatable { case travaille, fini, arrete }

enum ActionNote: Equatable { case compacter }

struct OptionQuestion: Equatable {
    var libelle: String
    var description: String
}

struct QuestionClaude: Equatable {
    var question: String
    var entete: String
    var plusieurs: Bool
    var options: [OptionQuestion]
}

/// Ce que montre le fil du chat. Valeurs immuables : un élément qui ne change pas reste égal à lui-même.
enum ElementFil: Equatable, Identifiable {
    struct MsgToi: Equatable {
        var cle: String
        var texte: String
        var images = 0
        var msgId = ""
    }

    struct MsgClaude: Equatable {
        var cle: String
        var texte: String
        var msgId = ""
        var fini = false
    }

    struct Outil: Equatable, Identifiable {
        var cle: String
        var nom: String
        var cible: String
        var details = ""
        var diff: Diff.Fichier? = nil
        var resultat: String? = nil
        var erreur = false
        var fini = false
        var imbrique = false
        var id: String { return cle }
    }

    struct Agent: Equatable {
        var cle: String
        var nom: String
        var consigne: String
        var arrierePlan: Bool
        var resultat: String? = nil
        var statut: StatutAgent = .travaille
    }

    struct Note: Equatable {
        var cle: String
        var texte: String
        var genre = "info"
        var action: ActionNote? = nil
    }

    struct Separateur: Equatable {
        var cle: String
        var auto: Bool
    }

    struct Demande: Equatable {
        var cle: String
        var outil: String
        var cible: String
        var details: String
        var description: String
    }

    struct Questions: Equatable {
        var cle: String
        var questions: [QuestionClaude]
    }

    /// Commande `!` lancée dans le dossier du projet.
    struct Commande: Equatable {
        var cle: String
        var commande: String
        var runId: String? = nil
        var sortie: String? = nil
        var code: Int? = nil
        var finie: Bool { return code != nil }
    }

    /// Le pont ne connaît plus ce chat : « Reprendre la conversation ».
    struct Arrete: Equatable {
        var cle: String
        var reprenable: Bool
    }

    case toi(MsgToi)
    case claude(MsgClaude)
    case outil(Outil)
    case agent(Agent)
    case note(Note)
    case separateur(Separateur)
    case demande(Demande)
    case questions(Questions)
    case commande(Commande)
    case arrete(Arrete)

    var cle: String {
        switch self {
        case .toi(let e): return e.cle
        case .claude(let e): return e.cle
        case .outil(let e): return e.cle
        case .agent(let e): return e.cle
        case .note(let e): return e.cle
        case .separateur(let e): return e.cle
        case .demande(let e): return e.cle
        case .questions(let e): return e.cle
        case .commande(let e): return e.cle
        case .arrete(let e): return e.cle
        }
    }

    var id: String { return cle }

    /// Même élément avec une autre clé (historique rechargé : clés uniques).
    func avecCle(_ c: String) -> ElementFil {
        switch self {
        case .toi(var e): e.cle = c; return .toi(e)
        case .claude(var e): e.cle = c; return .claude(e)
        case .outil(var e): e.cle = c; return .outil(e)
        case .note(var e): e.cle = c; return .note(e)
        default: return self
        }
    }
}

/// Sous-agent : pastille au-dessus du fil et sa vue (ses textes et outils).
struct VueAgent: Equatable, Identifiable {
    var id: String
    var nom: String
    var statut: StatutAgent
    var arrierePlan: Bool
}

/// Ce que l'écran doit faire après un événement.
enum Effet: Hashable { case demanderContexte, tourFini, sessionConnue, nouveauHello, mesureContexte, autorisationArrivee }

/// Liste avec index par clé : mise à jour d'un élément en O(1).
final class ListeFil {
    private(set) var elements: [ElementFil] = []
    private var pos: [String: Int] = [:]

    var taille: Int { return elements.count }

    func ajouter(_ e: ElementFil) {
        if let i = pos[e.cle] {
            elements[i] = e
            return
        }
        pos[e.cle] = elements.count
        elements.append(e)
    }

    subscript(cle: String) -> ElementFil? {
        guard let i = pos[cle] else { return nil }
        return elements[i]
    }

    func maj(_ cle: String, _ f: (ElementFil) -> ElementFil) {
        guard let i = pos[cle] else { return }
        elements[i] = f(elements[i])
    }

    func retirer(_ cle: String) {
        guard let i = pos.removeValue(forKey: cle) else { return }
        elements.remove(at: i)
        reindexer()
    }

    func prefixer(_ avant: [ElementFil]) {
        let neufs = avant.filter { pos[$0.cle] == nil }
        elements.insert(contentsOf: neufs, at: 0)
        reindexer()
    }

    func vider() {
        elements.removeAll()
        pos.removeAll()
    }

    private func reindexer() {
        pos.removeAll(keepingCapacity: true)
        for (i, e) in elements.enumerated() { pos[e.cle] = i }
    }
}

/**
 * Fil d'un chat : reçoit les événements numérotés du pont (`receive()` de `web/chat.js`) et tient
 * la liste des éléments à montrer, les sous-agents, la liste de tâches, l'état, le contexte.
 * Logique pure, utilisée depuis le fil principal (celui de l'écran).
 */
final class FilChat {
    private final class AgentInterne {
        let id: String
        let nom: String
        let arrierePlan: Bool
        var statut: StatutAgent = .travaille
        let fil = ListeFil()

        init(id: String, nom: String, arrierePlan: Bool) {
            self.id = id
            self.nom = nom
            self.arrierePlan = arrierePlan
        }
    }

    let fil = ListeFil()
    private var agents: [String: AgentInterne] = [:]
    private var ordreAgents: [String] = []
    private var outilDans: [String: ListeFil] = [:]      // tool_id → liste qui montre sa carte
    private var textes: [String: ListeFil] = [:]         // msg_id → liste qui montre le texte
    private var demandes: [String] = []                  // request_id en attente
    private var propres: Set<String> = []                // nonces de nos envois (écho ignoré)
    private var compteur = 0

    private(set) var seq = 0
    private(set) var sessionId: String?
    private(set) var etat = "starting"
    private(set) var reflechit = false
    private(set) var taches: [Tache] = []
    private(set) var contexte: MesureContexte?
    private(set) var commandes: [CommandeSlash] = []
    private(set) var modeles: [ModeleIa] = []
    /// Droits annoncés par Claude (Status, Maj+Tab au bureau) ; nil : pas d'annonce.
    private(set) var droitsAnnonces: String?
    /// Coût cumulé des tours (dollars).
    private(set) var coutTours = 0.0

    var vuesAgents: [VueAgent] {
        return ordreAgents.compactMap { id in
            guard let a = agents[id] else { return nil }
            return VueAgent(id: a.id, nom: a.nom, statut: a.statut, arrierePlan: a.arrierePlan)
        }
    }

    func filAgent(_ id: String) -> [ElementFil] { return agents[id]?.fil.elements ?? [] }

    private func cle(_ prefixe: String) -> String {
        compteur += 1
        return "\(prefixe)\(compteur)"
    }

    /// Nos propres envois : leur écho (UserSent) n'est pas montré deux fois.
    func retenirEnvoi(_ nonce: String) { propres.insert(nonce) }
    func oublierEnvoi(_ nonce: String) { propres.remove(nonce) }

    func definirSession(_ id: String?) {
        if let i = id, !i.isEmpty { sessionId = i }
    }

    /// Fil remis à zéro (le pont a redémarré, ou une autre conversation).
    func remettreAZero() {
        seq = 0
        fil.vider()
        agents.removeAll()
        ordreAgents.removeAll()
        outilDans.removeAll()
        textes.removeAll()
        demandes.removeAll()
        taches = []
        contexte = nil
        reflechit = false
    }

    // MARK: envois et notes de l'écran

    @discardableResult
    func bulleToi(_ texte: String, images: Int = 0, msgId: String = "") -> String {
        let c = cle("u")
        fil.ajouter(.toi(ElementFil.MsgToi(cle: c, texte: texte, images: images, msgId: msgId)))
        return c
    }

    @discardableResult
    func note(_ texte: String, genre: String = "info", action: ActionNote? = nil) -> String {
        let c = cle("n")
        fil.ajouter(.note(ElementFil.Note(cle: c, texte: texte, genre: genre, action: action)))
        return c
    }

    func commande(_ commande: String) -> String {
        let c = cle("s")
        fil.ajouter(.commande(ElementFil.Commande(cle: c, commande: commande)))
        return c
    }

    func majCommande(_ cle: String, _ f: (ElementFil.Commande) -> ElementFil.Commande) {
        fil.maj(cle) { e in
            if case .commande(let c) = e { return .commande(f(c)) }
            return e
        }
    }

    func arrete(reprenable: Bool) {
        if fil["arret"] == nil { fil.ajouter(.arrete(ElementFil.Arrete(cle: "arret", reprenable: reprenable))) }
        etat = "stopped"
    }

    func repris() { fil.retirer("arret") }

    func changerEtat(_ e: String?) {
        guard let e = e, !e.isEmpty else { return }
        etat = e
        if e != "busy" { reflechit = false }
    }

    func retirerDemande(_ requestId: String) {
        demandes.removeAll { $0 == requestId }
        fil.retirer(requestId)
    }

    // MARK: événements du pont

    /// Événement numéroté : ignoré s'il est déjà vu (rattachement).
    @discardableResult
    func recevoir(_ numero: Int, _ ev: EvChat) -> Set<Effet> {
        if numero > 0 {
            if numero <= seq { return [] }
            seq = numero
        }
        if let p = ev.parent, let agent = agents[p] {
            evenementAgent(agent, ev)
            return []
        }
        var effets = Set<Effet>()
        switch ev {
        case .initial(let sid, _, _):
            definirSession(sid)
            effets.insert(.sessionConnue)
        case .hello(let cmds, let mods, _):
            commandes = cmds
            modeles = mods
            effets.insert(.nouveauHello)
        case .statut(let droits):
            if !droits.isEmpty { droitsAnnonces = droits == "default" ? "manual" : droits }
        case .commandeLocale(let texte):
            if !texte.isEmpty { note(texte) }
            effets.insert(.demanderContexte)
        case .delta(let msgId, let texte, _):
            texteClaude(msgId, (texteDe(msgId) ?? "") + texte, fini: false, liste: fil)
        case .texte(let msgId, let texte, _):
            texteClaude(msgId, texte, fini: true, liste: fil)
        case .reflexion:
            reflechit = true
        case .outilLance(let toolId, let nom, let entree, let parentId):
            outil(toolId: toolId, nom: nom, entree: entree, liste: fil, imbrique: parentId != nil)
        case .outilFini(let toolId, let texte, let erreur, _):
            resultat(toolId, texte, erreur)
            agentFini(toolId)
        case .avisTache(let toolId, _, let resume):
            outilDans[toolId]?.maj(toolId) { e in
                if case .outil(var o) = e { o.fini = true; return .outil(o) }
                return e
            }
            agentFini(toolId, avis: true)
            if !resume.isEmpty { note(resume) }
        case .taches(let t):
            taches = t
        case .autorisation(let requestId, let outil, let affiche, let entree, let description, _):
            demande(requestId: requestId, outil: outil, affiche: affiche, entree: entree, description: description)
            effets.insert(.autorisationArrivee)
        case .envoye(let texte, let images, let nonce, let uuid):
            if propres.contains(nonce) {
                propres.remove(nonce)
            } else {
                bulleToi(texte, images: images, msgId: uuid)
            }
        case .reglee(let requestId, _):
            retirerDemande(requestId)
        case .tour(let ok, _, let coutUsd, let texte, let limite, let interrompu):
            if interrompu {
                note("Arrêté.")
                arreterAgents()
            } else if limite {
                note("Limite d'usage atteinte : " + (texte.isEmpty ? "attends la fin de la période ou change de compte." : texte), genre: "warning")
            } else if !ok {
                note(texte.isEmpty ? "Claude n'a pas pu finir sa réponse." : texte, genre: "error")
            }
            coutTours += coutUsd
            for d in demandes { fil.retirer(d) }
            demandes.removeAll()
            effets.insert(.tourFini)
            effets.insert(.demanderContexte)
        case .compacte:
            note("Conversation compactée.")
        case .reinitialise(let declencheur):
            fil.ajouter(.separateur(ElementFil.Separateur(cle: cle("r"), auto: EvChat.estAuto(declencheur))))
        case .note(let texte, let genre):
            note(texte, genre: (genre == "warning" || genre == "error") ? genre : "info")
        case .nouvelEssai(let tentative, let delaiS):
            note("Nouvel essai (\(tentative)) dans \(Int(delaiS.rounded())) s…", genre: "warning")
        case .etat(let e):
            changerEtat(e)
        case .contexte(let c):
            contexte = c
            effets.insert(.mesureContexte)
        case .optionRefusee(let quoi, let erreur):
            note("Réglage refusé (\(quoi)) : \(erreur)", genre: "warning")
        case .demandeInconnue(let sousType):
            note("Demande non prise en charge : \(sousType)", genre: "warning")
        case .fin(let code, let demande):
            arreterAgents()
            if !demande, let c = code, c != 0 { note("Claude s'est arrêté (code \(c)).", genre: "error") }
        case .etiquettesChangees, .autre:
            break
        }
        return effets
    }

    private func texteDe(_ msgId: String) -> String? {
        guard let l = textes[msgId], case .claude(let m)? = l["m" + msgId] else { return nil }
        return m.texte
    }

    private func texteClaude(_ msgId: String, _ texte: String, fini: Bool, liste: ListeFil) {
        let l: ListeFil
        if let deja = textes[msgId] {
            l = deja
        } else {
            l = liste
            textes[msgId] = liste
        }
        let c = "m" + msgId
        if l[c] == nil {
            l.ajouter(.claude(ElementFil.MsgClaude(cle: c, texte: texte, msgId: msgId, fini: fini)))
        } else {
            l.maj(c) { e in
                if case .claude(var m) = e {
                    m.texte = texte
                    m.fini = fini || m.fini
                    return .claude(m)
                }
                return e
            }
        }
    }

    private func outil(toolId: String, nom: String, entree: JSON, liste: ListeFil, imbrique: Bool) {
        if liste === fil && Outils.agents.contains(nom) {
            carteAgent(toolId: toolId, entree: entree)
            return
        }
        outilDans[toolId] = liste
        liste.ajouter(.outil(ElementFil.Outil(
            cle: toolId, nom: nom, cible: Outils.cible(nom, entree), details: Outils.details(entree),
            diff: Diff.deOutil(nom, entree), imbrique: imbrique
        )))
    }

    private func resultat(_ toolId: String, _ texte: String, _ erreur: Bool) {
        outilDans[toolId]?.maj(toolId) { e in
            switch e {
            case .outil(var o):
                o.resultat = texte
                o.erreur = erreur
                o.fini = true
                return .outil(o)
            case .agent(var a):
                a.resultat = texte
                return .agent(a)
            default:
                return e
            }
        }
    }

    private func carteAgent(toolId: String, entree e: JSON) {
        var nom = e.texte("description")
        if nom.isEmpty { nom = e.texte("subagent_type") }
        if nom.isEmpty { nom = "Sous-agent" }
        nom = String(nom.prefix(60))
        let fond = e.bool("run_in_background")
        if agents[toolId] == nil { ordreAgents.append(toolId) }
        agents[toolId] = AgentInterne(id: toolId, nom: nom, arrierePlan: fond)
        outilDans[toolId] = fil
        let consigne = e.texte("prompt")
        fil.ajouter(.agent(ElementFil.Agent(cle: toolId, nom: nom, consigne: consigne.isEmpty ? Outils.details(e) : consigne, arrierePlan: fond)))
    }

    private func evenementAgent(_ a: AgentInterne, _ ev: EvChat) {
        switch ev {
        case .outilLance(let toolId, let nom, let entree, _):
            if nom != "TodoWrite" { outil(toolId: toolId, nom: nom, entree: entree, liste: a.fil, imbrique: false) }
        case .outilFini(let toolId, let texte, let erreur, _):
            resultat(toolId, texte, erreur)
        case .texte(let msgId, let texte, _):
            if !texte.isEmpty { texteClaude(msgId, texte, fini: true, liste: a.fil) }
        case .delta(let msgId, let texte, _):
            texteClaude(msgId, (texteDe(msgId) ?? "") + texte, fini: false, liste: a.fil)
        default:
            break
        }
    }

    /// Fin d'un sous-agent : son résultat (premier plan) ou son avis de fin (arrière-plan).
    private func agentFini(_ id: String, avis: Bool = false, arret: Bool = false) {
        guard let a = agents[id] else { return }
        if a.statut != .travaille || (a.arrierePlan && !avis && !arret) { return }
        a.statut = arret ? .arrete : .fini
        let statut = a.statut
        fil.maj(id) { e in
            if case .agent(var g) = e {
                g.statut = statut
                return .agent(g)
            }
            return e
        }
    }

    private func arreterAgents() {
        for id in ordreAgents { agentFini(id, arret: true) }
    }

    private func demande(requestId: String, outil: String, affiche: String, entree: JSON, description: String) {
        if !demandes.contains(requestId) { demandes.append(requestId) }
        if outil == "AskUserQuestion" {
            fil.ajouter(.questions(ElementFil.Questions(cle: requestId, questions: FilChat.questions(entree))))
            return
        }
        fil.ajouter(.demande(ElementFil.Demande(
            cle: requestId, outil: affiche.isEmpty ? outil : affiche, cible: Outils.cible(outil, entree),
            details: Outils.details(entree), description: description
        )))
    }

    // MARK: historique

    /// Messages du journal d'avant le tampon du pont, ajoutés en tête du fil.
    func prefixerHistorique(_ messages: [MessageHistorique]) {
        var n = 0
        var avant: [ElementFil] = []
        for m in messages {
            n += 1
            switch m.role {
            case "utilisateur":
                avant.append(.toi(ElementFil.MsgToi(cle: "h\(n)-\(m.uuid)", texte: m.text, images: 0, msgId: m.uuid)))
            case "assistant":
                avant.append(.claude(ElementFil.MsgClaude(cle: "h\(n)-\(m.msgId)", texte: m.text, msgId: m.msgId, fini: true)))
            case "outil":
                if let t = m.tool {
                    avant.append(.outil(ElementFil.Outil(
                        cle: "h\(n)-\(t.toolId)", nom: t.name, cible: t.target, resultat: t.result, erreur: t.erreur, fini: true
                    )))
                }
            default:
                if !m.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    avant.append(.note(ElementFil.Note(cle: "h\(n)", texte: m.text)))
                }
            }
        }
        // les clés « hN » doivent rester uniques d'un chargement à l'autre (tout le journal après les 200 derniers)
        fil.prefixer(avant.map { e in
            compteur += 1
            return e.avecCle(e.cle + ":\(compteur)")
        })
    }

    static func questions(_ e: JSON) -> [QuestionClaude] {
        return e.liste("questions").compactMap { q in
            guard case .objet = q else { return nil }
            let options: [OptionQuestion] = q.liste("options").compactMap { op in
                guard case .objet = op else { return nil }
                return OptionQuestion(libelle: op.texte("label"), description: op.texte("description"))
            }
            return QuestionClaude(question: q.texte("question"), entete: q.texte("header"), plusieurs: q.bool("multiSelect"), options: options)
        }
    }
}

/// Ligne de l'écran : un élément, ou plusieurs actions qui se suivent réunies (« 3 actions »).
enum LigneFil: Equatable, Identifiable {
    case seul(ElementFil, grise: Bool)
    case groupe([ElementFil.Outil], grise: Bool)

    var cle: String {
        switch self {
        case .seul(let e, _): return e.cle
        case .groupe(let o, _): return "g:" + (o.first?.cle ?? "")
        }
    }

    var id: String { return cle }

    /// Avant un « Nouvelle conversation » : Claude ne le voit plus (grisé).
    var grise: Bool {
        switch self {
        case .seul(_, let g): return g
        case .groupe(_, let g): return g
        }
    }

    var element: ElementFil? {
        if case .seul(let e, _) = self { return e }
        return nil
    }

    /// Lignes à montrer : actions consécutives regroupées, éléments d'avant le dernier séparateur grisés.
    static func de(_ elements: [ElementFil]) -> [LigneFil] {
        var dernier = -1
        for (i, e) in elements.enumerated() {
            if case .separateur = e { dernier = i }
        }
        var out: [LigneFil] = []
        out.reserveCapacity(elements.count)
        var suite: [ElementFil.Outil] = []
        var suiteGrise = false
        func vider() {
            if suite.count >= 2 {
                out.append(.groupe(suite, grise: suiteGrise))
            } else {
                for o in suite { out.append(.seul(.outil(o), grise: suiteGrise)) }
            }
            suite = []
        }
        for (i, e) in elements.enumerated() {
            let grise = i < dernier
            if case .outil(let o) = e {
                if !suite.isEmpty && suiteGrise != grise { vider() }
                suite.append(o)
                suiteGrise = grise
            } else {
                vider()
                out.append(.seul(e, grise: grise))
            }
        }
        vider()
        return out
    }

    /// Texte d'une ligne pour la recherche dans le fil.
    static func texte(_ l: LigneFil) -> String {
        switch l {
        case .groupe(let o, _): return o.map { texte(ElementFil.outil($0)) }.joined(separator: "\n")
        case .seul(let e, _): return texte(e)
        }
    }

    static func texte(_ e: ElementFil) -> String {
        switch e {
        case .toi(let m): return m.texte
        case .claude(let m): return m.texte
        case .outil(let o): return [Outils.libelle(o.nom), o.cible, o.resultat ?? ""].joined(separator: " ")
        case .agent(let a): return a.nom + " " + a.consigne + " " + (a.resultat ?? "")
        case .note(let n): return n.texte
        case .demande(let d): return d.outil + " " + d.cible
        case .questions(let q): return q.questions.map { $0.question }.joined(separator: " ")
        case .commande(let c): return c.commande + " " + (c.sortie ?? "")
        case .separateur, .arrete: return ""
        }
    }
}
