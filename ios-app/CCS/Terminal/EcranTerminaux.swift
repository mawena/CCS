import SwiftUI

/**
 * Terminaux : ceux ouverts dans l'appli, ceux du serveur qu'on peut reprendre (ouverts depuis la
 * version web, par exemple) et « Nouveau terminal » dans un dossier.
 */
@MainActor
struct EcranTerminaux: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.naviguer) private var naviguer
    @State private var serveur: [InfoTerminal]? = nil
    @State private var erreur: String? = nil
    @State private var nouveau = false

    var body: some View {
        let locales = modele.terminaux.sessions
        List {
            Section("Dans l'appli") {
                if locales.isEmpty {
                    Text("Aucun terminal ouvert ici.").foregroundStyle(.secondary)
                }
                ForEach(locales) { s in
                    Button { naviguer(.terminal(s.id)) } label: {
                        ligne(s.titre, TachesFond.cheminCourt(s.cwd) + (s.fin != nil ? " · terminé" : ""))
                    }
                }
            }
            let autres = (serveur ?? []).filter { i in !locales.contains { $0.id == i.termId } }
            if !autres.isEmpty {
                Section("Sur le serveur") {
                    ForEach(autres) { i in
                        Button {
                            Task {
                                let s = await modele.terminaux.reprendre(i)
                                naviguer(.terminal(s.id))
                            }
                        } label: {
                            ligne(i.name, TachesFond.cheminCourt(i.cwd) + " · toucher pour le reprendre")
                        }
                    }
                }
            }
            if let m = erreur {
                EtatErreur(message: m) { Task { await charger() } }
            }
        }
        .navigationTitle("Terminaux")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button { nouveau = true } label: { Label("Nouveau terminal", systemImage: "plus") }
            }
        }
        .refreshable { await charger() }
        .task(id: modele.client.etat.estConnecte) {
            guard modele.client.etat.estConnecte else { return }
            await charger()
        }
        .sheet(isPresented: $nouveau) {
            FeuilleNouveauTerminal { cwd in
                nouveau = false
                Task { await ouvrirTerminal(modele, cwd: cwd, naviguer: naviguer) }
            }
        }
    }

    private func ligne(_ titre: String, _ sous: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "terminal").foregroundStyle(Color.accentCcs)
            VStack(alignment: .leading, spacing: 2) {
                Text(titre).foregroundStyle(.primary).lineLimit(1)
                Text(sous).font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.head)
            }
        }
    }

    private func charger() async {
        do {
            serveur = try await modele.terminaux.lister()
            erreur = nil
        } catch {
            erreur = texteErreur(error)
        }
    }
}

/// Dossier du nouveau terminal : le dossier personnel, un projet, ou un chemin tapé (`~` permis).
@MainActor
struct FeuilleNouveauTerminal: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.dismiss) private var fermer
    var initial: String = ""
    let ouvrir: (String) -> Void
    @State private var dossier = ""
    @State private var home = ""
    @State private var projets: [String] = []

    var body: some View {
        NavigationStack {
            Form {
                Section("Dossier") {
                    TextField("~", text: $dossier)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
                if !projets.isEmpty {
                    Section("Projets") {
                        ForEach(projets, id: \.self) { p in
                            Button(Format.base(p)) { dossier = Format.court(p, home: home) }
                        }
                    }
                }
            }
            .navigationTitle("Nouveau terminal")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Annuler") { fermer() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Ouvrir") {
                        let d = TachesFond.dossier(dossier, home: home)
                        ouvrir(d.isEmpty ? "~" : d)
                    }
                }
            }
        }
        .presentationDetents([.medium, .large])
        .task {
            if dossier.isEmpty { dossier = initial.isEmpty ? "~" : initial }
            if let e = try? await modele.client.appeler("accounts.state", en: EtatComptes.self) { home = e.home }
            if let r = try? await modele.client.appeler("projects.list", en: ListeProjets.self) {
                projets = Array(r.projets.filter { $0.exists }.compactMap { $0.cwd }.prefix(8))
            }
        }
    }
}

/// Ouvre un terminal dans `cwd` (shell, ou commande permise) puis son écran.
@MainActor
func ouvrirTerminal(_ modele: ModeleAppli, cwd: String, commande: String? = nil, nom: String? = nil, naviguer: Naviguer) async {
    do {
        let s = try await modele.terminaux.ouvrir(cwd: cwd, commande: commande, nom: nom)
        naviguer(.terminal(s.id))
    } catch {
        modele.avis.dire("Terminal impossible : \(texteErreur(error))")
    }
}
