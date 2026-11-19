import SwiftUI

/// Onglet Git : choisir un projet de CCS, puis son dépôt.
@MainActor
struct EcranGitOnglet: View {
    @Environment(ModeleAppli.self) private var modele
    @State private var liste: ListeProjets? = nil
    @State private var erreur: String? = nil

    var body: some View {
        List {
            if let l = liste {
                let projets = l.projets.filter { $0.exists && $0.cwd != nil }
                if projets.isEmpty { EtatVide("Aucun projet : ajoute-en un depuis Sessions ou Fichiers.") }
                ForEach(projets) { p in
                    NavigationLink(value: Destination.gitProjet(p.cwd ?? "")) {
                        HStack(spacing: 12) {
                            Image(systemName: "arrow.triangle.branch").foregroundStyle(Color.accentCcs)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(p.name.isEmpty ? Format.base(p.cwd) : p.name)
                                Text(p.cwd ?? "").font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.head)
                            }
                        }
                    }
                }
            } else if let e = erreur {
                EtatErreur(message: e) { Task { await charger() } }
            } else {
                Chargement()
            }
        }
        .navigationTitle("Git")
        .refreshable { await charger() }
        .task(id: modele.client.etat.estConnecte) {
            guard modele.client.etat.estConnecte else { return }
            await charger()
        }
    }

    private func charger() async {
        do {
            liste = try await modele.client.appeler("projects.list", en: ListeProjets.self)
            erreur = nil
        } catch {
            erreur = texteErreur(error)
        }
    }
}

/// Git d'un projet en plein écran (depuis l'onglet Git ou le chat).
@MainActor
struct EcranGitProjet: View {
    let cwd: String

    var body: some View {
        PanneauGit(cwd: cwd)
            .navigationTitle("Git · " + Format.base(cwd))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar(.hidden, for: .tabBar)
    }
}

/// Détail d'un commit (`git.show`) : message entier, auteur, date, diff de chaque fichier.
@MainActor
struct EcranCommit: View {
    @Environment(ModeleAppli.self) private var modele
    let cwd: String
    let id: String

    @State private var detail: DetailCommit? = nil
    @State private var erreur: String? = nil
    @State private var ouverts: Set<String> = []

    var body: some View {
        List {
            if let d = detail {
                Section {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(d.commit.subject).font(.headline)
                        if !d.commit.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            Text(d.commit.body.trimmingCharacters(in: .whitespacesAndNewlines)).font(.subheadline)
                        }
                        Text("\(d.commit.author) <\(d.commit.email)> · \(Format.ilYA(d.commit.time))")
                            .font(.caption).foregroundStyle(.secondary)
                        Text(d.commit.id).font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary)
                    }
                    .textSelection(.enabled)
                }
                Section("Fichiers (\(d.files.count))") {
                    ForEach(Array(d.files.enumerated()), id: \.offset) { _, f in
                        let fichier = GitVue.fichier(f)
                        Button {
                            if ouverts.contains(f.path) { ouverts.remove(f.path) } else { ouverts.insert(f.path) }
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(f.path).lineLimit(2).truncationMode(.head).foregroundStyle(.primary)
                                    Text(GitVue.etatFichier(f)).font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Text("+\(fichier.ajouts) −\(fichier.retraits)").font(.system(.caption, design: .monospaced))
                                    .foregroundStyle(.secondary)
                            }
                        }
                        if ouverts.contains(f.path) {
                            if let vide = GitVue.sansDiff(f) {
                                Text(vide).font(.footnote).foregroundStyle(.secondary)
                            } else {
                                CorpsDiff(lignesDiff: fichier.lignes, max: 200)
                            }
                            if f.truncated { Text("Diff tronqué.").font(.footnote) }
                        }
                    }
                }
                if d.truncated { EtatVide("Trop de fichiers : seuls les premiers sont montrés.") }
            } else if let e = erreur {
                EtatErreur(message: e) { Task { await charger() } }
            } else {
                Chargement()
            }
        }
        .navigationTitle(String(id.prefix(8)))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .task(id: modele.client.etat.estConnecte) {
            guard modele.client.etat.estConnecte, detail == nil else { return }
            await charger()
        }
    }

    private func charger() async {
        do {
            let d = try await modele.client.appeler("git.show", ["cwd": .chaine(cwd), "id": .chaine(id)], en: DetailCommit.self)
            detail = d
            if d.files.count <= 3 { ouverts = Set(d.files.map { $0.path }) }
            erreur = nil
        } catch {
            erreur = texteErreur(error)
        }
    }
}
