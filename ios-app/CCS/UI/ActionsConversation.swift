import SwiftUI

/// Ouvre un écran dans la pile de l'onglet courant (`@Environment(\.naviguer)`).
struct Naviguer {
    let faire: (Destination) -> Void

    func callAsFunction(_ d: Destination) { faire(d) }
}

private struct CleNaviguer: EnvironmentKey {
    static let defaultValue = Naviguer { _ in }
}

extension EnvironmentValues {
    var naviguer: Naviguer {
        get { return self[CleNaviguer.self] }
        set { self[CleNaviguer.self] = newValue }
    }
}

extension Conversation {
    /// Chat à ouvrir pour reprendre cette conversation.
    var destination: Destination {
        return .chat(DestChat(cwd: cwd, sessionId: sessionId, chemin: path, titre: titre))
    }
}

/// Ce qui est ouvert autour d'une conversation : aperçu, renommage, suppression.
@MainActor
@Observable
final class EtatActions {
    var apercu: Conversation?
    var renommer: Conversation?
    var nouveauTitre = ""
    var supprimer: Conversation?

    func demanderRenommage(_ c: Conversation) {
        nouveauTitre = c.titre
        renommer = c
    }
}

/**
 * Une conversation de l'historique (`convRow` de `sessions-conv.js`) : titre, marque « ouverte »,
 * projet, date et coût (demandé quand la ligne s'affiche, une requête à la fois), menu « ⋯ ».
 */
@MainActor
struct LigneConversation: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.naviguer) private var naviguer
    let c: Conversation
    let ouverte: Bool
    let montrerProjet: Bool
    let actions: EtatActions

    @State private var cout: String? = nil

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            Button {
                naviguer(c.destination)
            } label: {
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        Text(c.titre)
                            .lineLimit(2)
                            .foregroundStyle(c.dossierExiste ? Color.primary : Color.secondary)
                        if ouverte { Etiquette(texte: "ouverte") }
                    }
                    if !meta.isEmpty {
                        Text(meta).font(.footnote).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            Menu {
                MenuConversation(c: c, actions: actions)
            } label: {
                Image(systemName: "ellipsis.circle").foregroundStyle(.secondary).padding(.vertical, 6)
            }
            .accessibilityLabel("Actions pour \(c.titre)")
        }
        .contextMenu { MenuConversation(c: c, actions: actions) }
        .task(id: cleCout) {
            if c.path.isEmpty { return }
            cout = modele.couts[cleCout]
            if cout == nil { cout = await modele.cout(chemin: c.path, cle: cleCout) }
        }
    }

    private var cleCout: String { return "\(c.path):\(c.misAJour)" }

    private var meta: String {
        var parts: [String] = []
        if montrerProjet, !Format.base(c.cwd).isEmpty { parts.append(Format.base(c.cwd)) }
        let date = Format.ilYA(c.misAJour)
        if !date.isEmpty { parts.append(date) }
        if let k = cout, !k.isEmpty { parts.append(k) }
        return parts.joined(separator: " · ")
    }
}

/// Menu « ⋯ » d'une conversation (`convMenu` de `sessions-conv.js`).
@MainActor
struct MenuConversation: View {
    @Environment(\.naviguer) private var naviguer
    let c: Conversation
    let actions: EtatActions
    var suppression = true

    var body: some View {
        Button {
            naviguer(c.destination)
        } label: {
            Label("Reprendre", systemImage: "arrow.up.forward.app")
        }
        .disabled(!c.dossierExiste)
        Button {
            actions.apercu = c
        } label: {
            Label("Aperçu", systemImage: "eye")
        }
        Button {
            actions.demanderRenommage(c)
        } label: {
            Label("Renommer", systemImage: "pencil")
        }
        if suppression {
            Button(role: .destructive) {
                actions.supprimer = c
            } label: {
                Label("Supprimer", systemImage: "trash")
            }
        }
    }
}

/**
 * Suites du menu d'une conversation : Aperçu (12 derniers messages sans ouvrir), Renommer,
 * Supprimer (corbeille, avec « Annuler »).
 */
@MainActor
struct ModificateurActions: ViewModifier {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.naviguer) private var naviguer
    @Bindable var actions: EtatActions
    let changee: () -> Void

    func body(content: Content) -> some View {
        content
            .sheet(item: $actions.apercu) { c in
                Apercu(c: c) {
                    actions.apercu = nil
                    naviguer(c.destination)
                }
                .environment(modele)
            }
            .alert("Renommer la conversation", isPresented: Binding<Bool>(
                get: { actions.renommer != nil }, set: { if !$0 { actions.renommer = nil } }
            )) {
                TextField("Nouveau titre", text: $actions.nouveauTitre)
                Button("Renommer") { renommer() }
                Button("Annuler", role: .cancel) {}
            }
            .confirmationDialog(
                "Supprimer cette conversation ?",
                isPresented: Binding<Bool>(get: { actions.supprimer != nil }, set: { if !$0 { actions.supprimer = nil } }),
                titleVisibility: .visible,
                presenting: actions.supprimer
            ) { c in
                Button("Supprimer", role: .destructive) { supprimer(c) }
                Button("Annuler", role: .cancel) {}
            } message: { c in
                Text("« \(c.titre) » part dans la corbeille de CCS : tu peux la restaurer pendant 30 jours.")
            }
    }

    private func renommer() {
        guard let c = actions.renommer else { return }
        let titre = String(actions.nouveauTitre.prefix(200))
        actions.renommer = nil
        Task { @MainActor in
            do {
                _ = try await modele.client.appeler("conversation.rename", [
                    "session_id": .chaine(c.sessionId), "title": .chaine(titre), "path": .chaine(c.path),
                ])
                modele.avis.dire("Conversation renommée.")
                changee()
            } catch {
                modele.avis.dire(texteErreur(error), action: "Réessayer") { actions.demanderRenommage(c) }
            }
        }
    }

    private func supprimer(_ c: Conversation) {
        actions.supprimer = nil
        let m = modele
        let relire = changee
        Task { @MainActor in
            do {
                let r = try await m.client.appeler("conversation.trash", [
                    "path": .chaine(c.path), "session_id": .chaine(c.sessionId), "cwd": .chaine(c.cwd), "title": .chaine(c.titre),
                ], en: MiseCorbeille.self)
                relire()
                m.avis.dire("Conversation mise à la corbeille.", action: "Annuler") {
                    Task { @MainActor in
                        do {
                            _ = try await m.client.appeler("conversation.restore", ["tid": .chaine(r.tid)])
                            m.avis.dire("Conversation restaurée.")
                            relire()
                        } catch {
                            m.avis.dire(texteErreur(error))
                        }
                    }
                }
            } catch {
                m.avis.dire(texteErreur(error))
            }
        }
    }
}

extension View {
    func actionsConversation(_ actions: EtatActions, changee: @escaping () -> Void) -> some View {
        return modifier(ModificateurActions(actions: actions, changee: changee))
    }
}

/// Aperçu : les 12 derniers messages, sans ouvrir la conversation.
@MainActor
private struct Apercu: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.dismiss) private var fermer
    let c: Conversation
    let reprendre: () -> Void

    @State private var messages: [MessageHistorique]? = nil
    @State private var erreur: String? = nil
    @State private var essai = 0

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let e = erreur {
                        EtatErreur(message: e) { essai += 1 }
                    } else if let m = messages {
                        let vus = Array(m.filter { Format.role($0.role) != nil && !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }.suffix(12))
                        if vus.isEmpty {
                            Text("Rien à afficher dans cette conversation.").foregroundStyle(.secondary)
                        }
                        ForEach(Array(vus.enumerated()), id: \.offset) { _, msg in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(Format.role(msg.role)?.rawValue ?? "").font(.caption.weight(.semibold)).foregroundStyle(Color.accentCcs)
                                Text(msg.text.count > 700 ? String(msg.text.prefix(700)) + "…" : msg.text).font(.subheadline)
                            }
                        }
                    } else {
                        Chargement()
                    }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .navigationTitle(c.titre)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Fermer") { fermer() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Reprendre", action: reprendre).disabled(!c.dossierExiste)
                }
            }
        }
        .presentationDetents([.medium, .large])
        .task(id: essai) {
            erreur = nil
            do {
                let r = try await modele.client.appeler("conversation.messages", ["path": .chaine(c.path), "limit": 36], en: Messages.self)
                messages = r.messages
            } catch {
                erreur = texteErreur(error)
            }
        }
    }
}

/// Corbeille (`openTrash` de `sessions-manage.js`) : conversations supprimées, à restaurer.
@MainActor
struct FeuilleCorbeille: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.dismiss) private var fermer
    let changee: () -> Void

    @State private var corbeille: Corbeille? = nil
    @State private var erreur: String? = nil
    @State private var essai = 0
    @State private var enCours: String? = nil

    var body: some View {
        NavigationStack {
            List {
                if let e = erreur {
                    EtatErreur(message: e) { essai += 1 }
                } else if let c = corbeille {
                    Section {
                        let elements = c.items.sorted { ($0.supprimeLe ?? 0) > ($1.supprimeLe ?? 0) }
                        if elements.isEmpty { Text("La corbeille est vide.").foregroundStyle(.secondary) }
                        ForEach(elements) { el in
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    let t = (el.title ?? "").trimmingCharacters(in: .whitespaces)
                                    Text(t.isEmpty ? "(sans titre)" : t).lineLimit(2)
                                    Text(sousTitre(el)).font(.footnote).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button("Restaurer") { restaurer(el) }
                                    .buttonStyle(.borderless)
                                    .disabled(enCours != nil)
                            }
                        }
                    } footer: {
                        Text("Les conversations supprimées y restent \(c.days) jours, puis sont effacées.")
                    }
                } else {
                    Chargement()
                }
            }
            .navigationTitle("Corbeille")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Fermer") { fermer() } }
            }
        }
        .task(id: essai) {
            erreur = nil
            do {
                corbeille = try await modele.client.appeler("conversation.trash_list", en: Corbeille.self)
            } catch {
                erreur = texteErreur(error)
            }
        }
    }

    private func sousTitre(_ el: ElementCorbeille) -> String {
        var parts: [String] = []
        let b = Format.base(el.cwd)
        if !b.isEmpty { parts.append(b) }
        if let t = el.supprimeLe { parts.append("supprimée \(Format.ilYA(t))") }
        return parts.joined(separator: " · ")
    }

    private func restaurer(_ el: ElementCorbeille) {
        Task { @MainActor in
            enCours = el.tid
            do {
                _ = try await modele.client.appeler("conversation.restore", ["tid": .chaine(el.tid)])
                modele.avis.dire("Conversation restaurée.")
                changee()
                essai += 1
            } catch {
                modele.avis.dire(texteErreur(error))
            }
            enCours = nil
        }
    }
}
