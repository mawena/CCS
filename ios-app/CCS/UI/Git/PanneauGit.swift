import SwiftUI

private enum VueGit: String, CaseIterable, Hashable {
    case changements = "Changements", historique = "Historique", branches = "Branches"
}

/// Diff ouvert : `diff` nul pendant le chargement.
private struct Ouvert {
    var diff: DiffGit?
}

/**
 * Git d'un projet (`web/git.js`) : branche et suivi, fetch / pull / push (confirmés, push forcé à
 * part), fichiers indexés / modifiés / non suivis, diff dépliable, indexation par fichier et par
 * morceau, commit (message proposé, amend confirmé), historique par pages et branches.
 */
@MainActor
struct PanneauGit: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.naviguer) private var naviguer
    let cwd: String

    @State private var vue: VueGit = .changements
    @State private var statut: EtatGit? = nil
    @State private var erreur: String? = nil
    @State private var ouverts: [String: Ouvert] = [:]
    @State private var journal: JournalGit? = nil
    @State private var refs: RefsGit? = nil
    @State private var travail: String? = nil
    @State private var message = ""
    @State private var amend = false
    @State private var demandes = Demandes()

    private var client: CcsClient { return modele.client }
    private var libre: Bool { return travail == nil }

    var body: some View {
        VStack(spacing: 0) {
            if let t = travail { BandeauTravail(texte: t) }
            if let s = statut {
                if !s.repo {
                    EtatVide("Ce dossier n'est pas un dépôt git.")
                    Spacer()
                } else {
                    liste(s)
                }
            } else if let e = erreur {
                EtatErreur(message: e) { Task { await actualiser() } }
                Spacer()
            } else {
                Chargement()
                Spacer()
            }
        }
        .task(id: client.etat.estConnecte) {
            guard client.etat.estConnecte else { return }
            await actualiser()
        }
        .task(id: "\(vue.rawValue)|\(client.etat.estConnecte)") {
            guard client.etat.estConnecte else { return }
            if vue == .historique && journal == nil { await chargerJournal(depuisDebut: true) }
            if vue == .branches && refs == nil {
                do { refs = try await client.appeler("git.refs", params(), en: RefsGit.self) } catch { modele.avis.dire(texteErreur(error)) }
            }
        }
        .demandes(demandes)
    }

    private func liste(_ s: EtatGit) -> some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(s.branch.name ?? "HEAD détachée").font(.system(.body, design: .monospaced).weight(.semibold))
                            Text(GitVue.synchro(s.branch)).font(.footnote).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Menu {
                            Button(role: .destructive) { reseau("git.push", force: true) } label: { Label("Push forcé…", systemImage: "exclamationmark.arrow.triangle.2.circlepath") }
                            Button { Task { await actualiser() } } label: { Label("Actualiser", systemImage: "arrow.clockwise") }
                        } label: {
                            Image(systemName: "ellipsis.circle")
                        }
                        .buttonStyle(.borderless)
                        .accessibilityLabel("Plus d'actions Git")
                    }
                    HStack(spacing: 8) {
                        Button("Fetch") { reseau("git.fetch") }
                        Button(s.branch.behind > 0 ? "Pull ↓\(s.branch.behind)" : "Pull") { reseau("git.pull") }
                        Button(s.branch.ahead > 0 ? "Push ↑\(s.branch.ahead)" : "Push") { reseau("git.push") }
                    }
                    .buttonStyle(.bordered)
                    .disabled(!libre)
                }
                Picker("Vue", selection: $vue) {
                    ForEach(VueGit.allCases, id: \.self) { v in Text(v.rawValue).tag(v) }
                }
                .pickerStyle(.segmented)
                .listRowSeparator(.hidden)
            }
            switch vue {
            case .changements:
                changements(s)
                sectionCommit(s)
            case .historique:
                historique
            case .branches:
                branches
            }
        }
        .listStyle(.insetGrouped)
        .refreshable { await actualiser() }
    }

    // MARK: changements

    @ViewBuilder
    private func changements(_ s: EtatGit) -> some View {
        let groupes = GitVue.groupes(s)
        if groupes.isEmpty {
            Section { EtatVide("Rien à valider : le dossier est propre.") }
        }
        if s.truncated {
            Section { EtatVide("Trop de fichiers : seuls les premiers sont montrés.") }
        }
        ForEach(groupes, id: \.titre) { g in
            Section {
                ForEach(g.fichiers, id: \.path) { f in
                    ligneFichier(f, g)
                }
            } header: {
                HStack {
                    Text("\(g.titre) (\(g.fichiers.count))")
                    Spacer()
                    Button(g.tout) { indexer(g.methode, g.fichiers.map { $0.path }) }
                        .font(.caption).textCase(nil).disabled(!libre)
                }
            }
        }
    }

    @ViewBuilder
    private func ligneFichier(_ f: FichierGit, _ g: GitVue.Groupe) -> some View {
        let cle = GitVue.cle(g.cote, f.path)
        let lettre = g.lettre(f)
        HStack(spacing: 10) {
            Text(lettre).font(.system(.body, design: .monospaced).weight(.bold)).foregroundStyle(couleurMarque(lettre)).frame(width: 20)
            VStack(alignment: .leading, spacing: 2) {
                Text(Fichiers.nom(f.path)).lineLimit(1).truncationMode(.middle)
                let dossier = f.path.contains("/") ? Fichiers.parent(f.path) : ""
                Text([GitVue.marque(lettre), dossier].filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.head)
            }
            Spacer(minLength: 4)
            Button(g.verbe) { indexer(g.methode, [f.path]) }
                .buttonStyle(.borderless).font(.subheadline).disabled(!libre)
        }
        .contentShape(Rectangle())
        .onTapGesture { basculer(cle) }
        if let o = ouverts[cle] {
            diffOuvert(o.diff, f, g.cote, lettre)
        }
    }

    @ViewBuilder
    private func diffOuvert(_ d: DiffGit?, _ f: FichierGit, _ cote: GitVue.Cote, _ lettre: String) -> some View {
        if let d = d {
            if let vide = GitVue.sansDiff(d) {
                Text(vide).font(.footnote).foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    let parMorceau = GitVue.parMorceau(lettre, d)
                    ForEach(Array(d.hunks.enumerated()), id: \.offset) { i, h in
                        HStack {
                            Text(h.header).font(.system(size: 11, design: .monospaced)).foregroundStyle(Color.accentCcs).lineLimit(1)
                            Spacer()
                            if parMorceau {
                                Button(cote == .index ? "Désindexer ce morceau" : "Indexer ce morceau") { morceau(f, cote, i, h.header) }
                                    .buttonStyle(.borderless).font(.caption).disabled(!libre)
                            }
                        }
                        CorpsDiff(lignesDiff: GitVue.lignes(h))
                    }
                    if d.truncated { Text("Diff tronqué : seules les premières lignes sont montrées.").font(.footnote) }
                }
            }
        } else {
            Chargement(texte: "Chargement du diff…")
        }
    }

    private func sectionCommit(_ s: EtatGit) -> some View {
        Section("Commit") {
            TextField("Message du commit", text: $message, axis: .vertical)
                .lineLimit(3...10)
            Toggle("Modifier le dernier commit (amend)", isOn: Binding<Bool>(
                get: { amend },
                set: { v in
                    amend = v
                    if v && message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { message = s.dernierMessage }
                }
            ))
            HStack {
                Button("Commit") { commit() }
                    .buttonStyle(.borderedProminent)
                    .disabled(!libre || !GitVue.peutCommit(s, amend: amend))
                if !s.proposed.trimmingCharacters(in: .whitespaces).isEmpty {
                    Spacer()
                    Button("Message proposé") { message = s.proposed }.buttonStyle(.borderless).disabled(!libre)
                }
            }
        }
    }

    // MARK: historique et branches

    @ViewBuilder
    private var historique: some View {
        Section {
            if let j = journal {
                if j.commits.isEmpty { EtatVide("Aucun commit pour l'instant.") }
                ForEach(j.commits) { c in
                    Button {
                        naviguer(.commit(cwd: cwd, id: c.id))
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(c.subject).lineLimit(2).foregroundStyle(.primary)
                            Text("\(c.short) · \(c.author) · \(Format.ilYA(c.time))")
                                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                }
                if j.more {
                    Button("Plus de commits") { Task { await chargerJournal(depuisDebut: false) } }
                }
            } else {
                Chargement()
            }
        }
    }

    @ViewBuilder
    private var branches: some View {
        if let r = refs {
            let tete = r.refs.first { $0.kind == "head" }?.target
            let groupes = GitVue.refs(r.refs)
            if groupes.isEmpty { Section { EtatVide("Aucune branche.") } }
            ForEach(groupes, id: \.titre) { g in
                Section("\(g.titre) (\(g.refs.count))") {
                    ForEach(g.refs, id: \.name) { x in
                        HStack {
                            Text(x.name).font(.system(.body, design: .monospaced))
                                .fontWeight(x.kind == "branch" && x.target == tete ? .bold : .regular)
                                .lineLimit(1)
                            Spacer()
                            Text(String(x.target.prefix(8))).font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        } else {
            Section { Chargement() }
        }
    }

    // MARK: actions

    private func params(_ plus: [String: JSON] = [:]) -> [String: JSON] {
        var p: [String: JSON] = ["cwd": .chaine(cwd)]
        p.merge(plus) { _, b in b }
        return p
    }

    private func basculer(_ cle: String) {
        if ouverts[cle] != nil {
            ouverts[cle] = nil
        } else {
            ouverts[cle] = Ouvert(diff: nil)
            Task { await chargerDiff(cle) }
        }
    }

    private func chargerDiff(_ cle: String) async {
        guard let i = cle.firstIndex(of: ":") else { return }
        let cote = String(cle[cle.startIndex..<i])
        let chemin = String(cle[cle.index(after: i)...])
        do {
            let r = try await client.appeler("git.diff", params(["path": .chaine(chemin), "staged": .booleen(cote == GitVue.Cote.index.rawValue)]),
                                             en: ReponseDiff.self)
            if ouverts[cle] != nil { ouverts[cle] = Ouvert(diff: r.diff ?? DiffGit(path: chemin)) }
        } catch {
            ouverts[cle] = nil
            modele.avis.dire(texteErreur(error))
        }
    }

    private func chargerJournal(depuisDebut: Bool) async {
        let deja = depuisDebut ? [] : (journal?.commits ?? [])
        do {
            let r = try await client.appeler("git.log", params(["skip": .de(deja.count)]), en: JournalGit.self)
            journal = JournalGit(commits: deja + r.commits, more: r.more)
        } catch {
            modele.avis.dire(texteErreur(error))
        }
    }

    private func actualiser() async {
        do {
            let s = try await client.appeler("git.status", params(), en: EtatGit.self)
            statut = s
            erreur = nil
            let garder = GitVue.clesGardees(Set(ouverts.keys), s)
            for k in ouverts.keys where !garder.contains(k) { ouverts[k] = nil }
            for k in garder { await chargerDiff(k) }
            if vue == .historique { await chargerJournal(depuisDebut: true) }
            if vue == .branches { refs = try? await client.appeler("git.refs", params(), en: RefsGit.self) }
        } catch {
            erreur = texteErreur(error)
            if statut != nil { modele.avis.dire(texteErreur(error)) }
        }
    }

    /// Écriture (une à la fois), puis actualisation.
    private func agir(_ libelle: String, fait: String = "", _ action: @escaping () async throws -> Void, apres: @escaping () -> Void = {}) {
        guard travail == nil else { return }
        travail = libelle
        Task { @MainActor in
            var ok = false
            do {
                try await action()
                ok = true
                if !fait.isEmpty { modele.avis.dire(fait) }
            } catch {
                modele.avis.dire(texteErreur(error), long: true)
            }
            travail = nil
            if ok { apres() }
            await actualiser()
        }
    }

    private func indexer(_ methode: String, _ chemins: [String]) {
        agir(methode == "git.stage" ? "Indexation…" : "Désindexation…") {
            _ = try await client.appeler(methode, params(["paths": .de(chemins)]))
        }
    }

    private func morceau(_ f: FichierGit, _ cote: GitVue.Cote, _ i: Int, _ entete: String) {
        agir(cote == .index ? "Désindexation du morceau…" : "Indexation du morceau…") {
            _ = try await client.appeler("git.hunk", params([
                "path": .chaine(f.path), "index": .de(i), "header": .chaine(entete),
                "action": .chaine(cote == .index ? "unstage" : "stage"),
            ]))
        }
    }

    private func reseau(_ methode: String, force: Bool = false) {
        guard let b = statut?.branch else { return }
        Task { @MainActor in
            let (titre, texte, bouton) = PanneauGit.textes(methode, force, b)
            guard await demandes.confirmer(titre, texte, bouton, danger: force) else { return }
            let nom = methode == "git.fetch" ? "Fetch" : (methode == "git.pull" ? "Pull" : (force ? "Push forcé" : "Push"))
            agir("\(nom) en cours…", fait: "\(nom) terminé.") {
                _ = try await client.appeler(methode, params(methode == "git.push" ? ["force": .booleen(force)] : [:]), delai: 320)
            }
        }
    }

    private static func textes(_ methode: String, _ force: Bool, _ b: BrancheGit) -> (String, String, String) {
        switch methode {
        case "git.fetch":
            return ("Fetch ?", "Récupère les nouveautés du dépôt distant, sans rien changer à ta branche.", "Fetch")
        case "git.pull":
            return (b.name.map { "Pull sur « \($0) » ?" } ?? "Pull ?", GitVue.textePull(b), "Pull")
        default:
            if force {
                return ("Push forcé ?", "Le dépôt distant sera écrasé par ta branche (avec garde-fou : refusé si quelqu'un a poussé entre-temps).", "Pousser de force")
            }
            return (b.name.map { "Pousser « \($0) » ?" } ?? "Pousser ?", GitVue.textePush(b), "Pousser")
        }
    }

    private func commit() {
        if message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            modele.avis.dire("Écris le message du commit.")
            return
        }
        Task { @MainActor in
            if amend {
                guard await demandes.confirmer("Modifier le dernier commit ?",
                                               "Son contenu et son message seront remplacés. Si tu l'as déjà poussé, il faudra un push forcé.",
                                               "Modifier") else { return }
            }
            let a = amend
            let m = message
            agir("Commit…", fait: a ? "Commit modifié." : "Commit créé.", {
                _ = try await client.appeler("git.commit", params(["message": .chaine(m), "amend": .booleen(a)]), delai: 120)
            }, apres: {
                message = ""
                amend = false
                journal = nil
            })
        }
    }
}
