import SwiftUI

/**
 * Tâches de nuit sur l'Accueil (`web/pages-tasks.js`) : liste par état, journal d'une tâche (relu
 * toutes les 3 s tant qu'elle tourne), nouvelle tâche, reprise dans un chat, annulation et
 * suppression confirmées. Relu toutes les 15 s tant qu'une tâche est active.
 */
@MainActor
struct SectionTaches: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.naviguer) private var naviguer
    let home: String

    @State private var toutes: [TacheFond]? = nil
    @State private var erreur: String? = nil
    @State private var filtre: String? = nil
    @State private var detail: Choisie? = nil
    @State private var nouvelle = false

    private struct Choisie: Identifiable {
        let id: String
    }

    private var client: CcsClient { return modele.client }

    private func entete(_ t: TacheFond) -> String {
        var l1: String = TachesFond.sousTitre(t)
        let resume: String = j?.summary ?? ""
        if !resume.isEmpty { l1 += " · " + resume }
        var l2: String = TachesFond.libelleDroits(t.rights)
        if let m = t.model { l2 += " · " + m }
        return l1 + "\n" + l2
    }

    var body: some View {
        CarteFond {
            HStack {
                Text("Tâches de nuit").font(.headline)
                Spacer()
                Button("Nouvelle tâche") { nouvelle = true }.buttonStyle(.borderedProminent).controlSize(.small)
            }
            if let l = toutes {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(TachesFond.filtres, id: \.cle) { f in
                            Button {
                                filtre = f.cle
                            } label: {
                                Etiquette(texte: "\(f.libelle) (\(TachesFond.nombre(l, f)))",
                                          fond: (filtre ?? "actives") == f.cle ? Color.accentCcs.opacity(0.3) : Color.secondary.opacity(0.15))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                let montrees = TachesFond.filtrer(l, filtre ?? "actives")
                if montrees.isEmpty {
                    Text(l.isEmpty ? "Aucune tâche pour l'instant." : "Rien dans cette catégorie.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                ForEach(montrees) { t in
                    Button {
                        detail = Choisie(id: t.id)
                    } label: {
                        HStack(alignment: .top) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(TachesFond.titre(t)).font(.subheadline.weight(.semibold)).lineLimit(2).foregroundStyle(.primary)
                                Text(TachesFond.sousTitre(t)).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                            }
                            Spacer()
                            PastilleEtat(t: t)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    Divider()
                }
            } else if let e = erreur {
                EtatErreur(message: e) { Task { await charger() } }
            } else {
                Chargement()
            }
        }
        .task(id: client.etat.estConnecte) {
            guard client.etat.estConnecte else { return }
            await charger()
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 15_000_000_000)
                if Task.isCancelled { return }
                if (toutes ?? []).contains(where: TachesFond.active) { await charger() }
            }
        }
        .sheet(item: $detail) { c in
            FeuilleTache(id: c.id, change: { Task { await charger() } }) { d in
                detail = nil
                naviguer(.chat(d))
            }
            .environment(modele)
        }
        .sheet(isPresented: $nouvelle) {
            FeuilleNouvelleTache(home: home) {
                nouvelle = false
                filtre = "actives"
                Task { await charger() }
            }
            .environment(modele)
        }
    }

    private func charger() async {
        do {
            let l = try await client.appeler("tasks.list", en: ListeTaches.self).tasks
            toutes = l
            if filtre == nil { filtre = TachesFond.filtreInitial(l) }
            erreur = nil
        } catch {
            erreur = texteErreur(error)
        }
    }
}

@MainActor
private struct PastilleEtat: View {
    let t: TacheFond

    var body: some View {
        let c: Color
        switch t.state {
        case "running": c = .accentCcs
        case "done": c = .reussite
        case "failed": c = .red
        case "waiting": c = .avertissement
        default: c = .secondary
        }
        return Text(TachesFond.etat(t))
            .font(.caption2)
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .background(Capsule().fill(c.opacity(0.15)))
            .foregroundStyle(c)
    }
}

/// Détail et journal d'une tâche.
@MainActor
private struct FeuilleTache: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.dismiss) private var fermer
    let id: String
    let change: () -> Void
    let reprendre: (DestChat) -> Void

    @State private var j: JournalTache? = nil
    @State private var erreur: String? = nil
    @State private var occupe = false
    @State private var demandes = Demandes()

    private var client: CcsClient { return modele.client }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 8) {
                if let t = j?.task {
                    Text(entete(t))
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let e = erreur { Text(e).font(.footnote).foregroundStyle(.red) }
                ScrollViewReader { lecteur in
                    ScrollView([.vertical, .horizontal]) {
                        VStack(alignment: .leading, spacing: 0) {
                            Text(texteJournal)
                                .font(.system(size: 11, design: .monospaced))
                                .textSelection(.enabled)
                                .padding(8)
                            Color.clear.frame(width: 1, height: 1).id("bas")
                        }
                    }
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.fondCode))
                    .onChange(of: j?.lines.count ?? 0) { _, _ in lecteur.scrollTo("bas") }
                }
                if let t = j?.task { boutons(t) }
            }
            .padding(16)
            .navigationTitle(j.map { TachesFond.titre($0.task) } ?? "Tâche")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Fermer") { fermer() } }
            }
        }
        .task {
            while !Task.isCancelled {
                let encore = await relire()
                if !encore { return }
                try? await Task.sleep(nanoseconds: 3_000_000_000)
            }
        }
        .demandes(demandes)
    }

    private var texteJournal: String {
        guard let r = j else { return "Chargement…" }
        if r.lines.isEmpty { return "Pas encore de journal." }
        return (r.truncated ? "… (début du journal omis)\n" : "") + r.lines.joined(separator: "\n")
    }

    private func boutons(_ t: TacheFond) -> some View {
        let active = TachesFond.active(t)
        return HStack(spacing: 8) {
            if let sid = t.sessionId {
                Button("Reprendre") { reprise(t, sid) }.buttonStyle(.borderedProminent).disabled(occupe)
            }
            Button(active ? "Annuler la tâche" : "Supprimer", role: .destructive) { annulerOuSupprimer(t, active) }
                .buttonStyle(.bordered).disabled(occupe)
        }
    }

    /// Rend vrai tant que la tâche tourne (relire encore).
    private func relire() async -> Bool {
        do {
            j = try await client.appeler("tasks.log", ["id": .chaine(id)], en: JournalTache.self)
            erreur = nil
        } catch let e as RpcErreur {
            erreur = e.message
            if e.code == "introuvable" { change() }
            return false
        } catch {
            erreur = texteErreur(error)
        }
        return j.map { TachesFond.active($0.task) } ?? false
    }

    private func reprise(_ t: TacheFond, _ sid: String) {
        occupe = true
        Task { @MainActor in
            do {
                let o = try await client.appeler("chat.open", ["cwd": .chaine(t.cwd), "session_id": .chaine(sid)], en: ChatOuvert.self)
                let dossier = o.cwd.isEmpty ? t.cwd : o.cwd
                reprendre(DestChat(cwd: dossier, sessionId: o.sessionId ?? sid, chemin: o.path, titre: Format.base(t.cwd), chatId: o.chatId))
            } catch {
                modele.avis.dire(texteErreur(error))
            }
            occupe = false
        }
    }

    private func annulerOuSupprimer(_ t: TacheFond, _ active: Bool) {
        Task { @MainActor in
            let ok: Bool
            if active {
                ok = await demandes.confirmer("Annuler cette tâche ?",
                                              t.state == "running" ? "Claude est en train de la faire : il sera arrêté." : "Elle ne sera pas lancée.",
                                              "Annuler la tâche", danger: true)
            } else {
                ok = await demandes.confirmer("Supprimer cette tâche ?", "Son journal sera supprimé aussi.", "Supprimer", danger: true)
            }
            guard ok else { return }
            occupe = true
            do {
                _ = try await client.appeler(active ? "tasks.cancel" : "tasks.remove", ["id": .chaine(t.id)])
                modele.avis.dire(active ? "Tâche annulée." : "Tâche supprimée.")
                change()
                fermer()
            } catch {
                modele.avis.dire(texteErreur(error))
            }
            occupe = false
        }
    }
}

/// Nouvelle tâche : dossier, message, quand, droits, modèle.
@MainActor
private struct FeuilleNouvelleTache: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.dismiss) private var fermer
    let home: String
    let ajoutee: () -> Void

    @State private var dossier = ""
    @State private var message = ""
    @State private var quand = "quota"
    @State private var heure = ""
    @State private var droits = "modifications"
    @State private var modeleIa = ""
    @State private var erreur: String? = nil
    @State private var occupe = false
    @State private var projets: [String] = []
    @State private var abandon = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Dossier du projet") {
                    TextField("~/Work/mon-projet", text: $dossier)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    if !projets.isEmpty {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 6) {
                                ForEach(projets, id: \.self) { p in
                                    Button { dossier = p } label: { Etiquette(texte: Format.base(p)) }.buttonStyle(.plain)
                                }
                            }
                        }
                    }
                }
                Section("Message") {
                    TextField("Ce que Claude doit faire…", text: $message, axis: .vertical).lineLimit(4...12)
                }
                Section("Quand") {
                    Picker("Quand", selection: $quand) {
                        ForEach(TachesFond.quandChoix, id: \.valeur) { q in Text(q.libelle).tag(q.valeur) }
                    }
                    .pickerStyle(.inline)
                    .labelsHidden()
                    if quand == "heure" {
                        TextField("Heure (HH:MM)", text: $heure).keyboardType(.numbersAndPunctuation)
                    }
                }
                Section {
                    Picker("Droits", selection: $droits) {
                        ForEach(TachesFond.droits, id: \.valeur) { d in Text(d.libelle).tag(d.valeur) }
                    }
                    .pickerStyle(.inline)
                    .labelsHidden()
                } header: {
                    Text("Droits")
                } footer: {
                    Text(TachesFond.droits.first { $0.valeur == droits }?.aide ?? "")
                        .foregroundStyle(droits == "tout" ? Color.red : Color.secondary)
                }
                Section("Modèle") {
                    Picker("Modèle", selection: $modeleIa) {
                        ForEach(TachesFond.modeles, id: \.valeur) { m in Text(m.libelle).tag(m.valeur) }
                    }
                }
                if let e = erreur {
                    Section { Text(e).foregroundStyle(.red) }
                }
            }
            .navigationTitle("Nouvelle tâche")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") {
                        if message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { fermer() } else { abandon = true }
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Ajouter") { ajouter() }.disabled(occupe)
                }
            }
            .confirmationDialog("Abandonner cette tâche ?", isPresented: $abandon, titleVisibility: .visible) {
                Button("Abandonner", role: .destructive) { fermer() }
                Button("Continuer", role: .cancel) {}
            } message: {
                Text("Le message tapé sera perdu.")
            }
        }
        .interactiveDismissDisabled(!message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        .task {
            if dossier.isEmpty && !home.isEmpty { dossier = home }
            if let r = try? await modele.client.appeler("projects.list", en: ListeProjets.self) {
                projets = Array(r.projets.filter { $0.exists }.compactMap { $0.cwd }.prefix(10))
            }
        }
    }

    private func ajouter() {
        let cwd = TachesFond.dossier(dossier, home: home)
        erreur = TachesFond.verifier(dossier: cwd, message: message, quand: quand, heure: heure)
        if erreur != nil { return }
        occupe = true
        Task { @MainActor in
            do {
                _ = try await modele.client.appeler("tasks.add", [
                    "cwd": .chaine(cwd), "message": .chaine(message), "rights": .chaine(droits),
                    "model": modeleIa.isEmpty ? .nul : .chaine(modeleIa),
                    "when": .chaine(TachesFond.quandEnvoye(quand, heure: heure)),
                ])
                modele.avis.dire("Tâche ajoutée.")
                ajoutee()
            } catch {
                erreur = texteErreur(error)
            }
            occupe = false
        }
    }
}
