import SwiftUI

/**
 * Feuille de route d'un projet (`web/roadmap.js`) : phases avec leur progression (repliables ;
 * celles qui ont encore une case vide ouvertes), cases à cocher (le pont refuse si la ligne a changé
 * entre-temps), « Faire… » sur une tâche : dans ce chat (si on est dans un chat), dans un nouveau
 * chat, ou cette nuit (tâche de fond).
 */
@MainActor
struct PanneauFeuilleDeRoute: View {
    @Environment(ModeleAppli.self) private var modele
    let cwd: String
    var dansCeChat: ((String) -> Void)? = nil
    let nouveauChat: (String) -> Void

    @State private var feuille: FeuilleDeRoute? = nil
    @State private var erreur: String? = nil
    @State private var ouvertes: Set<Int> = []
    @State private var enCours: Set<Int> = []        // cases en cours d'envoi (par ligne)
    @State private var aFaire: AFaire? = nil
    @State private var defileFait = false

    private struct AFaire: Identifiable {
        let id = UUID()
        let phase: PhaseFeuille
        let tache: TacheFeuille
    }

    private enum Ou { case chat, nouveau, nuit }

    private var client: CcsClient { return modele.client }

    var body: some View {
        Group {
            if let f = feuille {
                if f.path == nil {
                    VStack {
                        EtatVide("Pas de ROADMAP.md dans ce projet.")
                        Spacer()
                    }
                } else {
                    liste(f)
                }
            } else if let e = erreur {
                VStack {
                    EtatErreur(message: e) { Task { await charger() } }
                    Spacer()
                }
            } else {
                VStack {
                    Chargement()
                    Spacer()
                }
            }
        }
        .task(id: client.etat.estConnecte) {
            guard client.etat.estConnecte else { return }
            await charger()
        }
        .confirmationDialog("Faire cette tâche", isPresented: Binding<Bool>(
            get: { aFaire != nil }, set: { if !$0 { aFaire = nil } }
        ), titleVisibility: .visible, presenting: aFaire) { a in
            if dansCeChat != nil { Button("Dans ce chat") { faire(a, .chat) } }
            Button("Nouveau chat") { faire(a, .nouveau) }
            Button("Cette nuit") { faire(a, .nuit) }
            Button("Annuler", role: .cancel) {}
        } message: { a in
            Text(a.tache.text)
        }
    }

    private func liste(_ f: FeuilleDeRoute) -> some View {
        ScrollViewReader { lecteur in
            List {
                if !f.title.trimmingCharacters(in: .whitespaces).isEmpty {
                    Text(f.title).font(.headline)
                }
                ForEach(Array(f.phases.enumerated()), id: \.offset) { i, p in
                    Section {
                        let prog = FeuilleRoute.progression(p)
                        Button {
                            if ouvertes.contains(i) { ouvertes.remove(i) } else { ouvertes.insert(i) }
                        } label: {
                            VStack(alignment: .leading, spacing: 6) {
                                HStack {
                                    Text(p.title).font(.subheadline.weight(.semibold)).foregroundStyle(.primary)
                                    Spacer()
                                    Text(prog.description).font(.caption).foregroundStyle(.secondary)
                                    Image(systemName: ouvertes.contains(i) ? "chevron.up" : "chevron.down").font(.caption).foregroundStyle(.secondary)
                                }
                                ProgressView(value: prog.fraction)
                            }
                        }
                        .id("p\(i)")
                        if ouvertes.contains(i) {
                            ForEach(p.tasks, id: \.line) { t in
                                ligneTache(p, t)
                            }
                        }
                    }
                }
            }
            .listStyle(.insetGrouped)
            .refreshable { await charger() }
            .onAppear {
                // la phase en cours à l'écran au premier affichage
                guard !defileFait, let n = FeuilleRoute.enCours(f.phases) else { return }
                defileFait = true
                Task { @MainActor in
                    try? await Task.sleep(nanoseconds: 150_000_000)
                    lecteur.scrollTo("p\(n)", anchor: .top)
                }
            }
        }
    }

    private func ligneTache(_ p: PhaseFeuille, _ t: TacheFeuille) -> some View {
        let envoi = enCours.contains(t.line)
        return HStack(alignment: .top, spacing: 10) {
            Button {
                cocher(t, !t.done)
            } label: {
                Image(systemName: t.done ? "checkmark.square.fill" : "square")
                    .foregroundStyle(t.done ? Color.accentCcs : .secondary)
                    .font(.title3)
            }
            .buttonStyle(.borderless)
            .disabled(envoi)
            .accessibilityLabel(t.done ? "Décocher" : "Cocher")
            Text(t.text)
                .font(.subheadline)
                .strikethrough(t.done)
                .foregroundStyle(t.done ? .secondary : .primary)
                .frame(maxWidth: .infinity, alignment: .leading)
            if !t.done {
                Button("Faire…") { aFaire = AFaire(phase: p, tache: t) }
                    .buttonStyle(.borderless)
                    .font(.subheadline)
            }
        }
        .padding(.leading, CGFloat(20 * FeuilleRoute.niveau(t.depth)))
    }

    private func charger() async {
        do {
            let f = try await client.appeler("roadmap.read", ["cwd": .chaine(cwd)], en: FeuilleDeRoute.self)
            if feuille == nil { ouvertes = FeuilleRoute.ouvertes(f.phases) }
            feuille = f
            erreur = nil
        } catch {
            erreur = texteErreur(error)
            if feuille != nil { modele.avis.dire(texteErreur(error)) }
        }
    }

    /// Remplace la case dans la feuille gardée (sans tout relire : le défilement reste).
    private func poser(_ t: TacheFeuille, _ fait: Bool) {
        guard var f = feuille else { return }
        for i in f.phases.indices {
            for k in f.phases[i].tasks.indices where f.phases[i].tasks[k].line == t.line {
                f.phases[i].tasks[k].done = fait
            }
        }
        feuille = f
    }

    private func cocher(_ t: TacheFeuille, _ fait: Bool) {
        guard let chemin = feuille?.path, !enCours.contains(t.line) else { return }
        enCours.insert(t.line)
        poser(t, fait)
        Task { @MainActor in
            do {
                let r = try await client.appeler("roadmap.toggle", [
                    "path": .chaine(chemin), "line": .de(t.line), "text": .chaine(t.text), "done": .booleen(fait),
                ], en: ResultatCase.self)
                if !r.changed {
                    modele.avis.dire("La feuille de route avait déjà changé : elle est rechargée.")
                    await charger()
                }
            } catch {
                poser(t, !fait)
                modele.avis.dire(texteErreur(error), action: "Recharger") { Task { await charger() } }
            }
            enCours.remove(t.line)
        }
    }

    private func faire(_ a: AFaire, _ ou: Ou) {
        guard let chemin = feuille?.path else { return }
        Task { @MainActor in
            let invitation: String
            do {
                invitation = try await client.appeler("roadmap.prompt", [
                    "path": .chaine(chemin), "text": .chaine(a.tache.text), "phase": .chaine(a.phase.title),
                ], en: InvitationTache.self).prompt
            } catch {
                modele.avis.dire(texteErreur(error))
                return
            }
            switch ou {
            case .chat: dansCeChat?(invitation)
            case .nouveau: nouveauChat(invitation)
            case .nuit:
                do {
                    _ = try await client.appeler("tasks.add", [
                        "message": .chaine(invitation), "cwd": .chaine(cwd), "when": "nuit",
                        "roadmap": .objet(["path": .chaine(chemin), "text": .chaine(a.tache.text), "phase": .chaine(a.phase.title)]),
                    ])
                    modele.avis.dire("Tâche ajoutée pour cette nuit.")
                } catch {
                    modele.avis.dire(texteErreur(error))
                }
            }
        }
    }
}

extension DestChat {
    /// Nouveau chat dans `cwd` qui envoie `texte` dès qu'il est ouvert.
    static func nouveauAvec(_ cwd: String, _ texte: String) -> DestChat {
        return DestChat(cwd: cwd, titre: Format.base(cwd), aEnvoyer: texte, jeton: UUID().uuidString)
    }
}
