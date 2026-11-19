import SwiftUI

/**
 * Accueil (`home.js`) : compte actif et meilleur compte, cartes des comptes (jauges, statut,
 * détails repliables, bascule avec confirmation), actualisation, pause, bilan de santé, accès à
 * l'analyse. Relu chaque minute tant que l'écran est visible, et à chaque reconnexion.
 */
@MainActor
struct EcranAccueil: View {
    @Environment(ModeleAppli.self) private var modele

    @State private var comptes: EtatComptes? = nil
    @State private var cartes: Cartes? = nil
    @State private var erreur: String? = nil
    @State private var actualisation = false
    @State private var version: String? = nil
    @State private var ouverts: Set<String> = []
    @State private var aBasculer: Carte? = nil
    @State private var bascule: String? = nil

    private var client: CcsClient { return modele.client }

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                if let c = cartes, let e = comptes {
                    if let m = erreur {
                        Text(m).foregroundStyle(.red).frame(maxWidth: .infinity, alignment: .leading)
                    }
                    LigneEtat(etat: e, cartes: c, enCours: actualisation) { actualiser() }
                    if c.cards.isEmpty {
                        EtatVide("Aucun compte enregistré : ajoute-en un avec « ccs add » dans un terminal.")
                    }
                    ForEach(c.cards) { carte in
                        CarteCompte(
                            carte: carte,
                            ouvert: ouverts.contains(carte.name),
                            basculeEnCours: bascule == carte.name,
                            surDetails: {
                                if ouverts.contains(carte.name) { ouverts.remove(carte.name) } else { ouverts.insert(carte.name) }
                            },
                            surBasculer: { aBasculer = carte }
                        )
                    }
                    CartePause(etat: e) { Task { await charger() } }
                    SectionTaches(home: e.home)
                    CarteAjoutCompte(home: e.home)
                } else if let m = erreur {
                    EtatErreur(message: m) { Task { await charger() } }
                } else {
                    Chargement(texte: "Chargement des comptes…")
                }
                CarteBilan()
                NavigationLink(value: Destination.analyse) {
                    HStack {
                        Image(systemName: "chart.bar").foregroundStyle(Color.accentCcs)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Analyse").foregroundStyle(.primary)
                            Text("Usage par projet, modèle, compte et heure").font(.footnote).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Image(systemName: "chevron.right").foregroundStyle(.tertiary)
                    }
                    .padding(16)
                    .background(RoundedRectangle(cornerRadius: 14).fill(Color.carte))
                }
                .buttonStyle(.plain)
                Text(pied)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, 4)
            }
            .padding(16)
        }
        .background(Color.fondGroupe)
        .navigationTitle("Accueil")
        .refreshable { await charger() }
        .task(id: client.etat.estConnecte) {
            guard client.etat.estConnecte else { return }
            while !Task.isCancelled {
                await charger()
                try? await Task.sleep(nanoseconds: 60_000_000_000)
            }
        }
        .confirmationDialog(
            "Basculer sur « \(aBasculer?.name ?? "") » ?",
            isPresented: Binding<Bool>(get: { aBasculer != nil }, set: { if !$0 { aBasculer = nil } }),
            titleVisibility: .visible,
            presenting: aBasculer
        ) { carte in
            Button("Basculer") { basculer(carte) }
            Button("Annuler", role: .cancel) {}
        } message: { _ in
            Text(texteBascule)
        }
    }

    private var texteBascule: String {
        let n = cartes?.chatsEnCours ?? 0
        if n > 0 { return "\(n) chat(s) tournent en ce moment : ils risquent d'être perturbés par le changement de compte." }
        return "Les nouveaux chats et le terminal utiliseront ce compte."
    }

    private var pied: String {
        let appli = (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "?"
        let i = modele.identifiants
        return "Serveur \(version ?? "…") · appli \(appli) · \(i?.utilisateur ?? "")" + (i?.portier == true ? " (Portier)" : "")
    }

    private func charger() async {
        do {
            async let e = client.appeler("accounts.state", en: EtatComptes.self)
            async let c = client.appeler("accounts.cards", en: Cartes.self)
            let (ee, cc) = try await (e, c)
            comptes = ee
            cartes = cc
            erreur = nil
        } catch {
            erreur = "Comptes indisponibles : " + texteErreur(error)
        }
        if version == nil {
            let serveur = modele.identifiants?.serveur ?? modele.adresse
            version = try? await ApiHttp.sante(serveur).version
        }
    }

    private func basculer(_ c: Carte) {
        Task { @MainActor in
            bascule = c.name
            do {
                let r = try await client.appeler("accounts.switch", ["name": .chaine(c.name)], en: ResultatBascule.self)
                if !r.ok { throw RpcErreur("echec", "La bascule a échoué.") }
                modele.avis.dire("Compte actif : \(c.name).")
            } catch {
                modele.avis.dire(texteErreur(error), action: "Réessayer") { basculer(c) }
            }
            bascule = nil
            await charger()
        }
    }

    private func actualiser() {
        Task { @MainActor in
            actualisation = true
            do {
                _ = try await client.appeler("accounts.refresh")
            } catch {
                actualisation = false
                modele.avis.dire(texteErreur(error), action: "Réessayer") { actualiser() }
                return
            }
            modele.avis.dire("Actualisation demandée : les chiffres arrivent dans quelques secondes.")
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            await charger()
            actualisation = false
            modele.avis.dire("Comptes actualisés.")
        }
    }
}

/// « Compte actif : X » ; meilleur compte, décision de la bascule automatique, date du relevé.
@MainActor
private struct LigneEtat: View {
    let etat: EtatComptes
    let cartes: Cartes
    let enCours: Bool
    let actualiser: () -> Void

    var body: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Compte actif : \(etat.active ?? "aucun")").font(.headline)
                if !sousTitre.isEmpty {
                    Text(sousTitre).font(.footnote).foregroundStyle(.secondary)
                }
            }
            Spacer()
            if enCours {
                ProgressView()
            } else {
                Button(action: actualiser) {
                    Label("Actualiser", systemImage: "arrow.clockwise")
                }
                .buttonStyle(.borderless)
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 14).fill(Color.carte))
    }

    private var sousTitre: String {
        var parts: [String] = []
        if let n = texteDans(cartes.best, "name") {
            parts.append("Meilleur compte : \(n)" + (texteDans(cartes.best, "reason").map { " (\($0))" } ?? ""))
        }
        if let d = texteDans(cartes.bascule, "decision", "reason") { parts.append("Bascule automatique : \(d)") }
        if let m = cartes.misAJour { parts.append("mis à jour \(Format.ilYA(m))") }
        return parts.joined(separator: " · ")
    }
}

@MainActor
private struct CarteCompte: View {
    let carte: Carte
    let ouvert: Bool
    let basculeEnCours: Bool
    let surDetails: () -> Void
    let surBasculer: () -> Void

    var body: some View {
        let teinte = couleurDe(carte.color)
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Pastille(couleur: teinte, taille: 12)
                VStack(alignment: .leading, spacing: 1) {
                    Text(carte.name).font(.headline)
                    let sous = [carte.email, carte.org].filter { !$0.isEmpty }.joined(separator: " · ")
                    if !sous.isEmpty { Text(sous).font(.footnote).foregroundStyle(.secondary).lineLimit(1) }
                }
                Spacer()
                if !carte.plan.isEmpty { Etiquette(texte: carte.plan, fond: Color.secondary.opacity(0.18)) }
                if carte.active { Etiquette(texte: "Actif", fond: teinte, encre: .white) }
            }
            ForEach(Array(carte.main.enumerated()), id: \.offset) { _, j in VueJauge(jauge: j, teinte: teinte) }
            if !carte.donnees && carte.status == nil {
                Text("Pas encore de relevé pour ce compte.").font(.subheadline).foregroundStyle(.secondary)
            }
            if let s = carte.status {
                Text(s.text).font(.subheadline).foregroundStyle(couleurStatut(s.kind))
            }
            if !carte.others.isEmpty || !carte.details.isEmpty || carte.erreur != nil {
                Button(action: surDetails) {
                    Label("Détails", systemImage: ouvert ? "chevron.up" : "chevron.down").font(.subheadline.weight(.medium))
                }
                .buttonStyle(.borderless)
                if ouvert {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(Array(carte.others.enumerated()), id: \.offset) { _, j in VueJauge(jauge: j, teinte: teinte) }
                        ForEach(carte.details, id: \.self) { d in
                            Text(d).font(.footnote).foregroundStyle(.secondary)
                        }
                        if let e = carte.erreur {
                            Text("Message d'origine : \(e)").font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            if !carte.active {
                Button(action: surBasculer) {
                    HStack {
                        if basculeEnCours { ProgressView() } else { Image(systemName: "arrow.left.arrow.right") }
                        Text("Basculer sur ce compte")
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(basculeEnCours)
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 14).fill(Color.carte))
        .overlay {
            if carte.active { RoundedRectangle(cornerRadius: 14).stroke(teinte, lineWidth: 2) }
        }
    }

    private func couleurStatut(_ kind: String) -> Color {
        switch kind {
        case "error": return .red
        case "warning": return .avertissement
        case "success": return .reussite
        default: return .primary
        }
    }
}

@MainActor
private struct VueJauge: View {
    let jauge: Jauge
    let teinte: Color

    var body: some View {
        let pct = Format.pourcent(jauge.percent)
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(jauge.label).font(.subheadline)
                Spacer()
                Text("\(pct) %").font(.subheadline.bold())
            }
            BarreJauge(pourcent: Double(pct), couleur: pct >= 90 ? .red : (pct >= 70 ? .avertissement : teinte))
            if !jauge.reset.isEmpty {
                Text(jauge.reset).font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

/// Pause de la bascule et de l'orchestrateur (`pause.set`).
@MainActor
private struct CartePause: View {
    @Environment(ModeleAppli.self) private var modele
    let etat: EtatComptes
    let relire: () -> Void
    @State private var occupe = false
    @State private var choisi: String = ""

    var body: some View {
        CarteFond {
            if let p = etat.pause {
                Text("En pause \(p.label)").font(.subheadline.weight(.semibold))
                Button("Reprendre") { appliquer("off", "Pause levée.") }
                    .buttonStyle(.bordered)
                    .disabled(occupe)
            } else {
                Text("Bascule et orchestrateur actifs").font(.subheadline.weight(.semibold))
                if !etat.choix.isEmpty {
                    HStack {
                        Picker("Mettre en pause", selection: $choisi) {
                            ForEach(etat.choix, id: \.valeur) { c in Text(c.libelle).tag(c.valeur) }
                        }
                        .pickerStyle(.menu)
                        Spacer()
                        Button("Pause") {
                            let v = choisi.isEmpty ? (etat.choix.first?.valeur ?? "") : choisi
                            if !v.isEmpty { appliquer(v, "Bascule et orchestrateur en pause.") }
                        }
                        .buttonStyle(.bordered)
                        .disabled(occupe)
                    }
                }
            }
        }
        .onAppear {
            if choisi.isEmpty { choisi = etat.choix.first?.valeur ?? "" }
        }
    }

    private func appliquer(_ valeur: String, _ fait: String) {
        Task { @MainActor in
            occupe = true
            do {
                _ = try await modele.client.appeler("pause.set", ["choice": .chaine(valeur)])
                modele.avis.dire(fait)
            } catch {
                modele.avis.dire(texteErreur(error))
            }
            occupe = false
            relire()
        }
    }
}

/**
 * « Ajouter un compte Claude » (`home.js`) : `ccs add <nom>` dans un terminal ; on y ouvre le lien
 * de connexion puis on colle le code.
 */
@MainActor
private struct CarteAjoutCompte: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.naviguer) private var naviguer
    let home: String
    @State private var nom = ""
    @State private var erreur: String? = nil
    @State private var occupe = false

    var body: some View {
        CarteFond {
            Text("Ajouter un compte Claude").font(.subheadline.weight(.semibold))
            Text("Lance « ccs add » dans un terminal : ouvre le lien de connexion sur ton téléphone ou ton PC, puis colle le code dans le terminal.")
                .font(.caption).foregroundStyle(.secondary)
            TextField("Nom du compte (ex. perso2)", text: $nom)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)
                .onChange(of: nom) { _, _ in erreur = nil }
            if let m = erreur { Text(m).font(.caption).foregroundStyle(.red) }
            Button("Ouvrir le terminal") {
                guard nom.range(of: "^[A-Za-z0-9_-]{1,32}$", options: .regularExpression) != nil else {
                    erreur = "Nom : lettres, chiffres, - et _ seulement."
                    return
                }
                occupe = true
                let n = nom
                Task {
                    await ouvrirTerminal(modele, cwd: home.isEmpty ? "~" : home, commande: "ccs add", nom: n, naviguer: naviguer)
                    occupe = false
                }
            }
            .buttonStyle(.bordered)
            .disabled(occupe)
        }
    }
}
