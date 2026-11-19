import SwiftUI

/// Volets de l'écran Projet.
enum OngletProjet: String, CaseIterable, Hashable {
    case conversations = "Conversations"
    case fichiers = "Fichiers"
    case git = "Git"
}

/**
 * Écran Projet (`project.js`) : nom et chemin, compte associé au dossier, « Nouveau chat » et les
 * conversations du projet ; volets Feuille de route, Fichiers et Git.
 */
@MainActor
struct EcranProjet: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.naviguer) private var naviguer
    let cwd: String

    @State private var liste: ListeProjets? = nil
    @State private var compte: CompteProjet? = nil
    @State private var ouvertes: Set<String> = []
    @State private var erreur: String? = nil
    @State private var montres = 30
    @State private var nouvelle = false
    @State private var actions = EtatActions()
    @State private var onglet: OngletProjet = .conversations

    private var client: CcsClient { return modele.client }
    private var entree: Projet? { return liste?.projets.first { $0.cwd == cwd } }

    var body: some View {
        VStack(spacing: 0) {
            Picker("Volet", selection: $onglet) {
                ForEach(OngletProjet.allCases, id: \.self) { o in Text(o.rawValue).tag(o) }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            switch onglet {
            case .conversations: conversations
            case .fichiers: PanneauFichiers(base: cwd)
            case .git: PanneauGit(cwd: cwd)
            }
        }
        .navigationTitle(entree?.name ?? Format.base(cwd))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .principal) {
                VStack(spacing: 0) {
                    Text(entree?.name ?? Format.base(cwd)).font(.headline).lineLimit(1)
                    Text(cwd).font(.caption2).foregroundStyle(.secondary).lineLimit(1).truncationMode(.head)
                }
            }
        }
        .task(id: client.etat.estConnecte) {
            guard client.etat.estConnecte else { return }
            await charger()
        }
        .actionsConversation(actions) { Task { await charger() } }
        .sheet(isPresented: $nouvelle) {
            FeuilleNouvelleSession(connus: [cwd], initial: cwd) { r, chemin in
                nouvelle = false
                let dossier = r.cwd.isEmpty ? chemin : r.cwd
                naviguer(.chat(DestChat(cwd: dossier, sessionId: r.sessionId, chemin: r.path, titre: Format.base(dossier), chatId: r.chatId)))
            }
        }
    }

    private var conversations: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: "person.crop.circle").foregroundStyle(Color.accentCcs)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(texteCompte).font(.subheadline.weight(.semibold))
                            if let h = compte?.hint, !h.isEmpty {
                                Text(h).font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                    }
                    if let p = entree {
                        Text(resume(p)).font(.footnote).foregroundStyle(.secondary)
                    }
                    Button {
                        nouvelle = true
                    } label: {
                        Label("Nouveau chat", systemImage: "plus.bubble").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(entree?.exists == false)
                }
                .padding(.vertical, 4)
            }
            Section("Conversations") {
                if let l = liste {
                    if l.conversations.isEmpty {
                        EtatVide("Pas encore de conversation dans ce projet.")
                    }
                    ForEach(l.conversations.prefix(montres)) { c in
                        LigneConversation(c: c, ouverte: ouvertes.contains(c.sessionId), montrerProjet: false, actions: actions)
                            .swipeActions(edge: .trailing) {
                                Button("Supprimer") { actions.supprimer = c }.tint(.red)
                            }
                    }
                    if l.conversations.count > montres {
                        Button("Voir plus (\(l.conversations.count - montres))") { montres += 30 }
                    }
                } else if let e = erreur {
                    EtatErreur(message: e) { Task { await charger() } }
                } else {
                    Chargement()
                }
            }
        }
        .listStyle(.insetGrouped)
        .refreshable { await charger() }
    }

    private var texteCompte: String {
        if let nom = compte?.preferred ?? entree?.profile { return "Compte : \(nom)" }
        return "Compte : \(compte?.active ?? "…") (actif)"
    }

    private func resume(_ p: Projet) -> String {
        var t = "\(p.total) conversation(s)"
        if p.open > 0 { t += " · \(p.open) ouverte(s)" }
        if !p.exists {
            t += " · dossier absent"
            if let d = p.deplaceVers { t += " (déplacé vers \(d) ?)" }
        }
        return t
    }

    private func charger() async {
        do {
            liste = try await client.appeler("projects.list", ["cwd": .chaine(cwd)], en: ListeProjets.self)
            erreur = nil
        } catch {
            erreur = texteErreur(error)
        }
        if let c = try? await client.appeler("projects.account", ["cwd": .chaine(cwd)], en: CompteProjet.self) { compte = c }
        if let r = try? await client.appeler("chat.list", en: ListeChats.self) {
            ouvertes = Set(r.chats.compactMap { $0.sessionId })
        }
    }
}
