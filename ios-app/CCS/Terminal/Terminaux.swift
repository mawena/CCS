import Foundation

/**
 * Terminaux ouverts depuis l'appli (`web/terminal.js` + onglets de `web/sessions.js`) : ils
 * survivent à la navigation entre écrans. Les événements `term.output` et `term.exit` vont au bon
 * terminal ; après une reconnexion, chacun se rattache (`term.attach`) et réaffiche la fin de sa
 * sortie. La saisie part dans l'ordre (une file par terminal).
 */
@MainActor
@Observable
final class Terminaux {
    private let client: CcsClient
    private let dire: (String) -> Void
    @ObservationIgnored private var ecoute = false
    @ObservationIgnored private var dernierAvis = Date.distantPast

    private(set) var sessions: [SessionTerminal] = []

    /// Sortie arrivée avant la réponse de `term.open` (identifiant pas encore connu).
    @ObservationIgnored private var enAvance: [String: String] = [:]
    /// Saisie en attente, par terminal, envoyée dans l'ordre.
    @ObservationIgnored private var files: [String: [String]] = [:]
    @ObservationIgnored private var envoiEnCours: Set<String> = []

    init(client: CcsClient, dire: @escaping (String) -> Void) {
        self.client = client
        self.dire = dire
    }

    func session(_ id: String) -> SessionTerminal? { return sessions.first { $0.id == id } }

    private func ecouter() {
        if ecoute { return }
        ecoute = true
        client.ecouter("term.output", pour: self) { [weak self] d in
            guard let s = self else { return }
            let id = d.texte("term_id")
            let texte = d.texte("data")
            if let t = s.session(id) { t.recevoir(texte) }
            else if s.enAvance.count < 8 {
                let avant = s.enAvance[id] ?? ""
                if avant.utf8.count < 65_536 { s.enAvance[id] = avant + texte }
            }
        }
        client.ecouter("term.exit", pour: self) { [weak self] d in
            self?.session(d.texte("term_id"))?.terminer(d.entier("code"))
        }
        client.ecouterReconnexions(pour: self) { [weak self] in
            guard let s = self else { return }
            for t in s.sessions where t.fin == nil { Task { await s.rattacher(t) } }
        }
    }

    private func avis(_ m: String) {
        if Date().timeIntervalSince(dernierAvis) < 4 { return }
        dernierAvis = Date()
        dire(m)
    }

    private func nouvelle(_ id: String, nom: String, cwd: String, colonnes: Int, lignes: Int) -> SessionTerminal {
        let s = SessionTerminal(id: id, nom: nom, cwd: cwd, colonnes: colonnes, lignes: lignes) { [weak self] d in
            self?.entrer(id, d)
        }
        s.surTaille = { [weak self, weak s] _, _ in
            if let t = s { self?.envoyerTaille(t) }
        }
        sessions = sessions.filter { $0.id != id } + [s]
        files[id] = []
        return s
    }

    /// Nom affiché d'un terminal : le dernier dossier du chemin.
    nonisolated static func nomDossier(_ cwd: String) -> String {
        let n = cwd.split(separator: "/").last.map(String.init) ?? ""
        return n.isEmpty ? "Terminal" : n
    }

    /**
     * Nouveau terminal dans `cwd` : le shell de l'utilisateur, ou une commande permise par le pont
     * (`ccs add` et son nom de compte).
     */
    func ouvrir(cwd: String, colonnes: Int = 80, lignes: Int = 24, commande: String? = nil, nom: String? = nil) async throws -> SessionTerminal {
        ecouter()
        var p: [String: JSON] = ["cwd": .chaine(cwd), "cols": .nombre(Double(colonnes)), "rows": .nombre(Double(lignes))]
        if let c = commande {
            p["command"] = .chaine(c)
            p["name"] = .chaine(nom ?? "")
        }
        let r = try await client.appeler("term.open", p, en: TerminalOuvert.self)
        let s = nouvelle(r.termId, nom: commande != nil ? (nom ?? "") : Terminaux.nomDossier(cwd), cwd: cwd, colonnes: colonnes, lignes: lignes)
        if let avant = enAvance.removeValue(forKey: r.termId) { s.recevoir(avant) }
        return s
    }

    /// Terminaux du pont (ceux de la version web compris).
    func lister() async throws -> [InfoTerminal] {
        return try await client.appeler("term.list", en: ListeTerminaux.self).terms
    }

    /// Terminal connu du pont mais pas encore affiché ici : on s'y rattache.
    func reprendre(_ info: InfoTerminal) async -> SessionTerminal {
        ecouter()
        if let s = session(info.termId) { return s }
        let s = nouvelle(info.termId, nom: info.name, cwd: info.cwd, colonnes: 80, lignes: 24)
        await rattacher(s)
        return s
    }

    private func rattacher(_ s: SessionTerminal) async {
        do {
            let r = try await client.appeler("term.attach", ["term_id": .chaine(s.id)], en: SortieTerminal.self)
            s.remplacer(r.output)
            envoyerTaille(s)
        } catch let e as RpcErreur {
            if e.code != "hors_ligne" { s.terminer(-1) }
        } catch {}
    }

    /// Saisie (clavier, barre de touches, réponses de l'émulateur), dans l'ordre.
    func entrer(_ id: String, _ data: String) {
        guard !data.isEmpty, let s = session(id), s.fin == nil, files[id] != nil else { return }
        files[id]?.append(data)
        vider(id)
    }

    private func vider(_ id: String) {
        guard !envoiEnCours.contains(id), let f = files[id], !f.isEmpty else { return }
        // les morceaux en attente partent ensemble (frappe rapide, collage)
        let d = f.joined()
        files[id] = []
        envoiEnCours.insert(id)
        Task {
            do {
                _ = try await client.appeler("term.input", ["term_id": .chaine(id), "data": .chaine(d)])
            } catch let e as RpcErreur {
                if e.code == "introuvable" { session(id)?.terminer(-1) } else { avis("La saisie n'est pas partie : \(e.message)") }
            } catch {}
            envoiEnCours.remove(id)
            vider(id)
        }
    }

    private func envoyerTaille(_ s: SessionTerminal) {
        if s.fin != nil { return }
        Task {
            _ = try? await client.appeler("term.resize", ["term_id": .chaine(s.id), "cols": .nombre(Double(s.colonnes)), "rows": .nombre(Double(s.lignes))])
        }
    }

    /// Ferme le terminal sur le serveur (ce qui y tourne est arrêté) et le retire.
    func fermer(_ s: SessionTerminal) async throws {
        if s.fin == nil {
            do {
                _ = try await client.appeler("term.close", ["term_id": .chaine(s.id)])
            } catch let e as RpcErreur where e.code == "introuvable" {}
        }
        retirer(s)
    }

    /// Retire le terminal de l'appli seulement (il continue sur le serveur, rattachable).
    func retirer(_ s: SessionTerminal) {
        files.removeValue(forKey: s.id)
        sessions = sessions.filter { $0.id != s.id }
    }

    /// Déconnexion : plus aucun terminal affiché.
    func oublier() {
        files = [:]
        enAvance = [:]
        sessions = []
    }
}
