import SwiftUI

/**
 * « Nouvelle session » (`sessions-new.js`) : dossier (récents, projets connus, dépôts git du disque,
 * chemin tapé), compte (conseillé pour ce dossier ; une bascule globale si on en choisit un autre),
 * modèle et droits. Ouvre le chat (`chat.open`) et rend sa réponse.
 */
@MainActor
struct FeuilleNouvelleSession: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.dismiss) private var fermer
    let connus: [String]
    var initial: String = ""
    let ouvert: (ChatOuvert, String) -> Void

    @State private var dossier = ""
    @State private var home = ""
    @State private var depots: [String]? = nil
    @State private var echecDepots: String? = nil
    @State private var essaiDepots = 0
    @State private var compte: CompteProjet? = nil
    @State private var compteChoisi: String = ""
    @State private var compteTouche = false
    @State private var modeleIa = ""
    @State private var droits = "manual"
    @State private var message: String? = nil
    @State private var occupe = false
    @State private var recents: [String] = []
    @State private var pret = false

    private static let montres = 30

    var body: some View {
        NavigationStack {
            Form {
                Section("Dossier") {
                    TextField("~/Repo/projet", text: $dossier)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    let proposes = dossiersProposes(recents: recents, connus: connus, depots: depots ?? [], saisie: dossier, home: home)
                    ForEach(Array(proposes.prefix(FeuilleNouvelleSession.montres).enumerated()), id: \.offset) { _, p in
                        Button {
                            dossier = p.chemin
                        } label: {
                            HStack {
                                Text(Format.court(p.chemin, home: home))
                                    .lineLimit(1)
                                    .truncationMode(.head)
                                    .fontWeight(p.chemin == dossier.trimmingCharacters(in: .whitespaces) ? .semibold : .regular)
                                    .foregroundStyle(.primary)
                                Spacer()
                                Etiquette(texte: p.etiquette)
                            }
                        }
                    }
                    if proposes.count > FeuilleNouvelleSession.montres {
                        Text("\(proposes.count - FeuilleNouvelleSession.montres) autres : tape pour filtrer.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                    if let e = echecDepots {
                        EtatErreur(message: e) { essaiDepots += 1 }
                    } else if depots == nil {
                        Chargement(texte: "Recherche des dépôts git…")
                    } else if proposes.isEmpty {
                        Text("Aucun dossier connu ne correspond : le chemin tapé sera utilisé.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
                if let cp = compte, cp.profiles.count >= 2 {
                    Section {
                        Picker("Compte Claude", selection: Binding<String>(
                            get: { compteChoisi },
                            set: { compteChoisi = $0; compteTouche = true }
                        )) {
                            ForEach(cp.profiles, id: \.name) { p in
                                Text("\(p.name) — \(p.email)" + (p.active ? " (actif)" : "")).tag(p.name)
                            }
                        }
                    } footer: {
                        VStack(alignment: .leading, spacing: 4) {
                            if !cp.hint.isEmpty { Text(cp.hint) }
                            if !compteChoisi.isEmpty && compteChoisi != (cp.active ?? "") {
                                Text("La bascule s'applique à toutes les sessions ouvertes.").foregroundStyle(Color.avertissement)
                            }
                        }
                    }
                }
                Section {
                    Picker("Modèle", selection: $modeleIa) {
                        ForEach(ChoixSession.modeles, id: \.valeur) { m in Text(m.libelle).tag(m.valeur) }
                    }
                    Picker("Droits", selection: $droits) {
                        ForEach(ChoixSession.droits, id: \.valeur) { d in Text(d.libelle).tag(d.valeur) }
                    }
                } footer: {
                    if droits == "bypassPermissions" {
                        Text("Claude pourra tout faire sans rien demander : à réserver à un dossier jetable.").foregroundStyle(.red)
                    }
                }
                if let m = message {
                    Section { Text(m).foregroundStyle(.red) }
                }
            }
            .navigationTitle("Nouvelle session")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Annuler") { fermer() } }
                ToolbarItem(placement: .confirmationAction) {
                    if occupe {
                        ProgressView()
                    } else {
                        Button("Ouvrir un chat") { ouvrir() }
                    }
                }
            }
        }
        .onAppear {
            if !pret {
                pret = true
                dossier = initial
                recents = Prefs.recents()
            }
        }
        .task {
            if let e = try? await modele.client.appeler("accounts.state", en: EtatComptes.self) { home = e.home }
        }
        .task(id: essaiDepots) {
            echecDepots = nil
            depots = nil
            do {
                depots = try await modele.client.appeler("projects.folders", delai: 60, en: Depots.self).dossiers
            } catch {
                echecDepots = texteErreur(error)
            }
        }
        .task(id: dossier) {
            // compte conseillé pour ce dossier, relu quand on arrête de taper
            let chemin = dossier.trimmingCharacters(in: .whitespaces)
            if chemin.isEmpty { return }
            try? await Task.sleep(nanoseconds: 400_000_000)
            if Task.isCancelled { return }
            guard let r = try? await modele.client.appeler("projects.account", ["cwd": .chaine(chemin)], en: CompteProjet.self) else { return }
            compte = r
            if !compteTouche || !r.profiles.contains(where: { $0.name == compteChoisi }) {
                compteChoisi = r.preferred ?? r.active ?? ""
            }
        }
    }

    private func ouvrir() {
        let chemin = dossier.trimmingCharacters(in: .whitespaces)
        if chemin.isEmpty {
            message = "Choisis ou tape un dossier."
            return
        }
        Task { @MainActor in
            message = nil
            occupe = true
            defer { occupe = false }
            do {
                if let actif = compte?.active, !compteChoisi.isEmpty, compteChoisi != actif {
                    let r = try await modele.client.appeler("accounts.switch", ["name": .chaine(compteChoisi)], en: ResultatBascule.self)
                    if !r.ok {
                        message = "La bascule de compte a échoué : rien n'est ouvert."
                        return
                    }
                }
                var options: [String: JSON] = ["rights": .chaine(droits)]
                if !modeleIa.isEmpty { options["model"] = .chaine(modeleIa) }
                let r = try await modele.client.appeler("chat.open", ["cwd": .chaine(chemin), "options": .objet(options)], delai: 60, en: ChatOuvert.self)
                Prefs.retenirRecent(chemin)
                ouvert(r, chemin)
            } catch {
                message = texteErreur(error)
            }
        }
    }
}

/// « Ajouter un projet » (`addProject` de `sessions-manage.js`) : dossier existant ou nouveau.
@MainActor
struct FeuilleAjouterProjet: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.dismiss) private var fermer
    let ajoute: (String) -> Void

    @State private var nouveau = false
    @State private var cwd = ""
    @State private var parent = "~/Work"
    @State private var nom = ""
    @State private var git = true
    @State private var message: String? = nil
    @State private var occupe = false

    var body: some View {
        NavigationStack {
            Form {
                Picker("Type", selection: $nouveau) {
                    Text("Dossier existant").tag(false)
                    Text("Nouveau dossier").tag(true)
                }
                .pickerStyle(.segmented)
                if nouveau {
                    TextField("Dans le dossier", text: $parent)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField("Nom (mon-projet)", text: $nom)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    Toggle("Initialiser un dépôt git", isOn: $git)
                } else {
                    TextField("~/Work/mon-projet", text: $cwd)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                }
                if let m = message { Text(m).foregroundStyle(.red) }
            }
            .navigationTitle("Ajouter un projet")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Annuler") { fermer() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Ajouter") { valider() }.disabled(occupe)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func valider() {
        let vide = nouveau ? nom.trimmingCharacters(in: .whitespaces).isEmpty : cwd.trimmingCharacters(in: .whitespaces).isEmpty
        if vide {
            message = nouveau ? "Donne un nom au dossier." : "Choisis ou tape un dossier."
            return
        }
        let params: [String: JSON] = nouveau
            ? ["parent": .chaine(parent.trimmingCharacters(in: .whitespaces)), "name": .chaine(nom.trimmingCharacters(in: .whitespaces)), "git": .de(git)]
            : ["cwd": .chaine(cwd.trimmingCharacters(in: .whitespaces))]
        Task { @MainActor in
            occupe = true
            message = nil
            do {
                let r = try await modele.client.appeler("projects.add", params, en: ProjetAjoute.self)
                modele.avis.dire("Projet ajouté : \(Format.base(r.cwd))")
                ajoute(r.cwd)
            } catch {
                message = texteErreur(error)
            }
            occupe = false
        }
    }
}
