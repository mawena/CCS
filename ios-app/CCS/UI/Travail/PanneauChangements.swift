import SwiftUI

/**
 * Changements de la session (`web/chat-changes.js`) : fichiers changés par Claude avec leur diff,
 * « Annuler ce fichier », « Revenir ici » (état des fichiers d'avant un message). Toute écriture
 * est confirmée et gardée par les empreintes montrées (le pont refuse si le fichier a bougé).
 */
@MainActor
struct PanneauChangements: View {
    @Environment(ModeleAppli.self) private var modele
    let chatId: String?
    let cwd: String
    let ouvrirFichier: (String) -> Void

    @State private var r: Changements? = nil
    @State private var erreur: String? = nil
    @State private var occupe = false
    @State private var ouverts: Set<String> = []
    @State private var demandes = Demandes()

    private var client: CcsClient { return modele.client }

    var body: some View {
        List {
            if let c = r {
                if c.unknown {
                    EtatVide("Le format de l'historique des fichiers de Claude Code n'est pas reconnu : rien ne peut être annulé d'ici.")
                } else {
                    Section("Fichiers changés") {
                        if c.files.isEmpty { EtatVide("Aucun fichier n'a changé depuis le début de la session.") }
                        ForEach(c.files) { f in carte(f) }
                    }
                    if !c.points.isEmpty {
                        Section {
                            ForEach(c.points.reversed()) { p in
                                HStack {
                                    Text(p.text.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression))
                                        .font(.subheadline).lineLimit(2)
                                    Spacer()
                                    Button("Revenir ici") { revenir(p) }.buttonStyle(.borderless).disabled(occupe)
                                }
                            }
                        } header: {
                            Text("Revenir avant un message")
                        } footer: {
                            Text("Remet les fichiers dans l'état où ils étaient avant ce message.")
                        }
                    }
                }
            } else if let e = erreur {
                EtatErreur(message: e) { Task { await charger() } }
            } else {
                Chargement()
            }
        }
        .listStyle(.insetGrouped)
        .refreshable { await charger() }
        .task { await charger() }
        .demandes(demandes)
    }

    @ViewBuilder
    private func carte(_ f: FichierChange) -> some View {
        let lignes = (f.tropGros || f.binary) ? [] : ChangementsChat.lignes(f.diff)
        let plus = lignes.filter { $0.genre == .ajout }.count
        let moins = lignes.filter { $0.genre == .retrait }.count
        Button {
            if ouverts.contains(f.path) { ouverts.remove(f.path) } else { ouverts.insert(f.path) }
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 8) {
                        Text(Format.base(f.path)).font(.subheadline.weight(.semibold)).lineLimit(1).foregroundStyle(.primary)
                        Text(ChangementsChat.genre(f)).font(.caption2)
                            .foregroundStyle(f.kind == "created" ? Color.reussite : (f.kind == "deleted" ? Color.red : Color.avertissement))
                        if plus > 0 { Text("+\(plus)").font(.caption2).foregroundStyle(Color.reussite) }
                        if moins > 0 { Text("−\(moins)").font(.caption2).foregroundStyle(.red) }
                    }
                    Text(ChangementsChat.relatif(f.path, cwd)).font(.caption).foregroundStyle(.secondary).lineLimit(2).truncationMode(.head)
                }
                Spacer()
                Image(systemName: ouverts.contains(f.path) ? "chevron.up" : "chevron.down").foregroundStyle(.secondary)
            }
        }
        if ouverts.contains(f.path) {
            if f.tropGros {
                Text("Fichier trop gros pour être montré").font(.footnote)
            } else if f.binary {
                Text("Fichier binaire : pas de diff.").font(.footnote)
            } else {
                CorpsDiff(lignesDiff: lignes)
            }
            HStack {
                if f.kind != "deleted" {
                    Button("Ouvrir le fichier") { ouvrirFichier(f.path) }.buttonStyle(.bordered)
                }
                Button("Annuler ce fichier", role: .destructive) { annuler(f) }.buttonStyle(.bordered).disabled(occupe)
            }
        }
    }

    private func charger() async {
        guard let id = chatId else {
            erreur = "Le chat n'est pas encore ouvert."
            return
        }
        do {
            r = try await client.appeler("work.changes", ["chat_id": .chaine(id)], en: Changements.self)
            erreur = nil
        } catch {
            erreur = texteErreur(error)
        }
    }

    private func annuler(_ f: FichierChange) {
        guard let id = chatId else { return }
        Task { @MainActor in
            guard await demandes.confirmer("Annuler les changements de \(Format.base(f.path)) ?", ChangementsChat.texteAnnulation(f),
                                           "Annuler ce fichier", danger: true) else { return }
            occupe = true
            do {
                _ = try await client.appeler("work.undo_file", ["chat_id": .chaine(id), "path": .chaine(f.path), "expected": .de(f.sha256)])
                modele.avis.dire("Fichier remis comme avant la session.")
            } catch {
                modele.avis.dire(texteErreur(error))
            }
            occupe = false
            await charger()
        }
    }

    private func revenir(_ p: PointRetour) {
        guard let id = chatId else { return }
        Task { @MainActor in
            occupe = true
            let plan: PlanRetour
            do {
                plan = try await client.appeler("work.rewind_plan", ["chat_id": .chaine(id), "message_id": .chaine(p.messageId)], en: PlanRetour.self)
            } catch {
                modele.avis.dire(texteErreur(error))
                occupe = false
                return
            }
            occupe = false
            if plan.steps.isEmpty {
                modele.avis.dire("Tout est déjà comme avant ce message.")
                return
            }
            guard await demandes.confirmer(ChangementsChat.titreRetour(plan), ChangementsChat.texteRetour(plan, cwd),
                                           "Revenir en arrière", danger: true) else { return }
            occupe = true
            do {
                let attendus: [JSON] = plan.steps.map { .objet(["path": .chaine($0.path), "sha256": .de($0.sha256)]) }
                let res = try await client.appeler("work.rewind_apply", [
                    "chat_id": .chaine(id), "message_id": .chaine(p.messageId), "expected": .tableau(attendus),
                ], en: ResultatRetour.self)
                modele.avis.dire("\(res.count) fichier(s) remis comme avant ce message.")
            } catch {
                modele.avis.dire(texteErreur(error))
            }
            occupe = false
            await charger()
        }
    }
}

private let portees: [(valeur: String, libelle: String)] = [("global", "Tous les projets"), ("projet", "Ce projet")]

/**
 * Messages enregistrés (`web/chat-saved.js`), communs à tous les projets ou propres au projet :
 * toucher l'un l'insère dans la saisie ; enregistrer le texte en cours ; supprimer (confirmé).
 */
@MainActor
struct FeuilleMessages: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.dismiss) private var fermer
    let cwd: String
    let texteEnCours: String
    let inserer: (String) -> Void

    @State private var liste: [MessageEnregistre]? = nil
    @State private var erreur: String? = nil
    @State private var nom = ""
    @State private var portee = "global"
    @State private var occupe = false
    @State private var demandes = Demandes()

    private var client: CcsClient { return modele.client }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    if let l = liste {
                        if l.isEmpty { EtatVide("Aucun message enregistré pour l'instant.") }
                        ForEach(l) { m in
                            Button {
                                fermer()
                                inserer(m.text)
                            } label: {
                                VStack(alignment: .leading, spacing: 2) {
                                    HStack(spacing: 0) {
                                        Text(m.name).font(.subheadline.weight(.semibold)).foregroundStyle(.primary)
                                        Text(" · " + (m.scope == "projet" ? "ce projet" : "tous")).font(.subheadline).foregroundStyle(.secondary)
                                    }
                                    Text(String(m.text.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression).prefix(120)))
                                        .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                                }
                            }
                            .swipeActions(edge: .trailing) {
                                Button("Supprimer", role: .destructive) { supprimer(m) }
                            }
                        }
                    } else if let e = erreur {
                        EtatErreur(message: e) { Task { await charger() } }
                    } else {
                        Chargement()
                    }
                }
                if !texteEnCours.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    Section("Enregistrer le texte en cours") {
                        TextField("Nom du message", text: Binding<String>(get: { nom }, set: { nom = String($0.prefix(80)) }))
                        Picker("Pour", selection: $portee) {
                            ForEach(portees, id: \.valeur) { p in Text(p.libelle).tag(p.valeur) }
                        }
                        .pickerStyle(.segmented)
                        Button("Enregistrer") { enregistrer() }
                            .disabled(nom.trimmingCharacters(in: .whitespaces).isEmpty || occupe)
                    }
                }
            }
            .navigationTitle("Messages enregistrés")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Fermer") { fermer() } }
            }
        }
        .task { await charger() }
        .demandes(demandes)
    }

    private func charger() async {
        do {
            liste = try await client.appeler("work.saved.list", ["cwd": .chaine(cwd)], en: MessagesEnregistres.self).items
            erreur = nil
        } catch {
            erreur = texteErreur(error)
        }
    }

    private func supprimer(_ m: MessageEnregistre) {
        Task { @MainActor in
            guard await demandes.confirmer("Supprimer « \(m.name) » ?", "Le message enregistré disparaît.", "Supprimer", danger: true) else { return }
            do {
                _ = try await client.appeler("work.saved.delete", ["cwd": .chaine(cwd), "scope": .chaine(m.scope), "name": .chaine(m.name)])
            } catch {
                modele.avis.dire(texteErreur(error))
            }
            await charger()
        }
    }

    private func enregistrer() {
        occupe = true
        Task { @MainActor in
            do {
                _ = try await client.appeler("work.saved.save", [
                    "cwd": .chaine(cwd), "scope": .chaine(portee), "name": .chaine(nom), "text": .chaine(texteEnCours),
                ])
                nom = ""
                modele.avis.dire("Message enregistré.")
                await charger()
            } catch {
                modele.avis.dire(texteErreur(error))
            }
            occupe = false
        }
    }
}
