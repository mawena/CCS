import SwiftUI

/// Couleur de la pastille d'un état de chat (« En cours »).
func couleurEtat(_ t: EtatChat.Ton) -> Color {
    switch t {
    case .occupe: return .accentCcs
    case .attente: return .avertissement
    case .pret: return .reussite
    case .arret: return .secondary
    }
}

/**
 * Sessions (`sessions.js`, version téléphone : une colonne) : « En cours » (chats ouverts dans le
 * pont, état en direct), projets, conversations récentes, recherche, corbeille, nouvelle session.
 */
@MainActor
struct EcranSessions: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.naviguer) private var naviguer

    @State private var recherche = ""
    @State private var liste: ListeProjets? = nil
    @State private var chats: [ChatOuvert] = []
    @State private var etats: [String: String] = [:]          // chat_id → état poussé en direct
    @State private var erreur: String? = nil
    @State private var montresProjets = 40
    @State private var montresConvs = 60
    @State private var nouvelle = false
    @State private var nouvelleDans = ""
    @State private var ajouter = false
    @State private var corbeille = false
    @State private var aRetirer: Projet? = nil
    @State private var aFermer: ChatOuvert? = nil
    @State private var actions = EtatActions()

    private var client: CcsClient { return modele.client }

    var body: some View {
        List {
            if !chats.isEmpty {
                Section("En cours") {
                    ForEach(chats) { ch in ligneChat(ch) }
                }
            }
            contenu
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Sessions")
        .searchable(text: $recherche, prompt: "Rechercher une conversation")
        .refreshable {
            await chargerChats()
            await charger()
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    nouvelleDans = ""
                    nouvelle = true
                } label: {
                    Label("Nouvelle session", systemImage: "square.and.pencil")
                }
            }
        }
        .task(id: client.etat.estConnecte) {
            guard client.etat.estConnecte else { return }
            await chargerChats()
            await charger()
        }
        .task(id: recherche) {
            if liste == nil { return }
            try? await Task.sleep(nanoseconds: 300_000_000)
            if Task.isCancelled { return }
            montresProjets = 40
            montresConvs = 60
            await charger()
        }
        .task {
            // état des chats en direct (StateChanged) ; un chat inconnu : la liste est relue
            for await d in client.flux("chat.event") {
                let id = d.texte("chat_id")
                guard !id.isEmpty, let ev = d["event"], ev.texte("type") == "StateChanged" else { continue }
                let s = ev.texte("state")
                if s.isEmpty { continue }
                if chats.contains(where: { $0.chatId == id }) { etats[id] = s } else { await chargerChats() }
            }
        }
        .actionsConversation(actions) { Task { await charger() } }
        .sheet(isPresented: $nouvelle) {
            FeuilleNouvelleSession(connus: (liste?.projets ?? []).filter { $0.exists }.compactMap { $0.cwd }, initial: nouvelleDans) { r, chemin in
                nouvelle = false
                Task { await chargerChats() }
                let cwd = r.cwd.isEmpty ? chemin : r.cwd
                naviguer(.chat(DestChat(cwd: cwd, sessionId: r.sessionId, chemin: r.path, titre: Format.base(cwd), chatId: r.chatId)))
            }
        }
        .sheet(isPresented: $ajouter) {
            FeuilleAjouterProjet { _ in
                ajouter = false
                Task { await charger() }
            }
        }
        .sheet(isPresented: $corbeille) {
            FeuilleCorbeille { Task { await charger() } }
        }
        .confirmationDialog(
            "Retirer « \(aRetirer?.name ?? "") » de la liste ?",
            isPresented: Binding<Bool>(get: { aRetirer != nil }, set: { if !$0 { aRetirer = nil } }),
            titleVisibility: .visible,
            presenting: aRetirer
        ) { p in
            Button("Retirer", role: .destructive) { retirer(p) }
        } message: { _ in
            Text("Le dossier et ses conversations ne sont pas effacés ; le projet revient dans la liste si une nouvelle conversation y démarre.")
        }
        .confirmationDialog(
            "Fermer le chat « \(Format.base(aFermer?.cwd)) » ?",
            isPresented: Binding<Bool>(get: { aFermer != nil }, set: { if !$0 { aFermer = nil } }),
            titleVisibility: .visible,
            presenting: aFermer
        ) { ch in
            Button("Fermer", role: .destructive) { fermerChat(ch) }
        } message: { _ in
            Text("Claude s'arrête ; la conversation reste dans l'historique.")
        }
    }

    @ViewBuilder
    private var contenu: some View {
        if let l = liste {
            if l.projets.isEmpty && l.conversations.isEmpty {
                Section {
                    if !recherche.trimmingCharacters(in: .whitespaces).isEmpty {
                        EtatVide("Rien trouvé pour « \(recherche.trimmingCharacters(in: .whitespaces)) ».") {
                            Button("Effacer la recherche") { recherche = "" }.buttonStyle(.bordered)
                        }
                    } else {
                        EtatVide("Aucun projet ni conversation pour l'instant.")
                    }
                }
            } else {
                if let m = erreur {
                    Section { Text(m).foregroundStyle(.red) }
                }
                sectionProjets(l)
                sectionConversations(l)
                Section {
                    Button {
                        corbeille = true
                    } label: {
                        Label("Corbeille", systemImage: "trash")
                    }
                }
            }
        } else if let m = erreur {
            Section { EtatErreur(message: m) { Task { await charger() } } }
        } else {
            Section { Chargement() }
        }
    }

    private func ligneChat(_ ch: ChatOuvert) -> some View {
        let e = EtatChat.de(etats[ch.chatId] ?? ch.state)
        return Button {
            naviguer(.chat(DestChat(cwd: ch.cwd, sessionId: ch.sessionId, chemin: ch.path, titre: Format.base(ch.cwd), chatId: ch.chatId)))
        } label: {
            HStack(spacing: 12) {
                Pastille(couleur: couleurEtat(e.ton), taille: 12)
                VStack(alignment: .leading, spacing: 2) {
                    Text(Format.base(ch.cwd)).foregroundStyle(.primary).lineLimit(1)
                    Text("\(e.libelle) · \(Format.base(ch.cwd))").font(.footnote).foregroundStyle(.secondary)
                }
                Spacer()
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .swipeActions(edge: .trailing) {
            Button("Fermer") { aFermer = ch }.tint(.red)
        }
    }

    private func sectionProjets(_ l: ListeProjets) -> some View {
        let projets = l.projets
        return Section {
            if projets.isEmpty {
                Text("Aucun projet ne correspond.").foregroundStyle(.secondary)
            }
            ForEach(projets.prefix(montresProjets)) { p in
                LigneProjet(p: p, surNouveauChat: {
                    nouvelleDans = p.cwd ?? ""
                    nouvelle = true
                }, surRetirer: { aRetirer = p })
            }
            if projets.count > montresProjets {
                Button("Voir plus de projets (\(projets.count - montresProjets))") { montresProjets += 40 }
            }
        } header: {
            HStack {
                Text("Projets")
                Spacer()
                Button {
                    ajouter = true
                } label: {
                    Label("Ajouter", systemImage: "plus")
                }
                .font(.footnote)
                .textCase(nil)
            }
        }
    }

    private func sectionConversations(_ l: ListeProjets) -> some View {
        let convs = l.conversations
        let ouvertes = Set(chats.compactMap { $0.sessionId })
        return Section("Conversations récentes") {
            if convs.isEmpty {
                Text(recherche.isEmpty ? "Aucune conversation." : "Aucune conversation ne correspond.").foregroundStyle(.secondary)
            }
            ForEach(convs.prefix(montresConvs)) { c in
                LigneConversation(c: c, ouverte: ouvertes.contains(c.sessionId), montrerProjet: true, actions: actions)
                    .swipeActions(edge: .trailing) {
                        Button("Supprimer") { actions.supprimer = c }.tint(.red)
                    }
            }
            if convs.count > montresConvs {
                Button("Voir plus de conversations (\(convs.count - montresConvs))") { montresConvs += 60 }
            }
        }
    }

    private func chargerChats() async {
        if let r = try? await client.appeler("chat.list", en: ListeChats.self) {
            chats = r.chats
            etats = [:]
        }
    }

    private func charger() async {
        do {
            liste = try await client.appeler("projects.list", ["query": .chaine(recherche)], en: ListeProjets.self)
            erreur = nil
        } catch {
            erreur = texteErreur(error)
        }
    }

    private func retirer(_ p: Projet) {
        Task { @MainActor in
            do {
                _ = try await client.appeler("projects.remove", ["cwd": .de(p.cwd)])
                modele.avis.dire("« \(p.name) » retiré de la liste.")
                await charger()
            } catch {
                modele.avis.dire(texteErreur(error))
            }
        }
    }

    private func fermerChat(_ ch: ChatOuvert) {
        Task { @MainActor in
            _ = try? await client.appeler("chat.close", ["chat_id": .chaine(ch.chatId)])
            await chargerChats()
        }
    }
}

@MainActor
private struct LigneProjet: View {
    @Environment(\.naviguer) private var naviguer
    let p: Projet
    let surNouveauChat: () -> Void
    let surRetirer: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button {
                naviguer(.projet(p.cwd ?? ""))
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: p.exists ? "folder" : "folder.badge.questionmark").foregroundStyle(Color.accentCcs)
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 6) {
                            Text(p.name).foregroundStyle(.primary).lineLimit(1)
                            if let prof = p.profile { Etiquette(texte: prof) }
                        }
                        Text(sousTitre).font(.footnote).foregroundStyle(.secondary)
                    }
                    Spacer()
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if p.exists {
                Button(action: surNouveauChat) {
                    Image(systemName: "plus.bubble")
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("Nouveau chat dans \(p.name)")
            }
        }
        .contextMenu {
            Button(role: .destructive, action: surRetirer) {
                Label("Retirer de la liste", systemImage: "minus.circle")
            }
        }
        .swipeActions(edge: .trailing) {
            Button("Retirer", action: surRetirer).tint(.red)
        }
    }

    private var sousTitre: String {
        var t = "\(p.total) conversation(s)"
        if p.open > 0 { t += " · \(p.open) ouverte(s)" }
        if !p.exists { t += " · dossier absent" }
        return t
    }
}
