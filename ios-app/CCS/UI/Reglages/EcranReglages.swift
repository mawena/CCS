import SwiftUI

private let genresAcces = ["session": "Navigateur", "device": "Appareil retenu (sans code)", "app": "Application"]

/**
 * Réglages (`web/settings.js`) : ceux de l'appli (thème, notifications, serveur, déconnexion), le
 * téléphone (ntfy, `web/pages-phone.js`), tous les réglages du serveur (chacun enregistré seul,
 * validé par le pont) et les appareils connectés, révocables.
 */
@MainActor
struct EcranReglages: View {
    @Environment(ModeleAppli.self) private var modele
    @State private var reglages: JSON? = nil
    @State private var erreur: String? = nil
    @State private var serveur = false
    @State private var adresse = ""
    @State private var deconnecter = false
    @State private var demandes = Demandes()

    private var client: CcsClient { return modele.client }

    var body: some View {
        Form {
            Section {
                Picker("Thème", selection: Binding<Theme>(get: { modele.theme }, set: { modele.changerTheme($0) })) {
                    ForEach(Theme.allCases, id: \.self) { t in Text(t.libelle).tag(t) }
                }
            } header: {
                Text("Apparence")
            } footer: {
                Text("Propre à ce téléphone.")
            }
            Section("Connexion") {
                LabeledContent("Serveur", value: modele.identifiants?.serveur ?? modele.adresse)
                LabeledContent("Compte", value: (modele.identifiants?.utilisateur ?? "") + " · " + modeConnexion)
                LabeledContent("Appli", value: (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "?")
                Button("Changer de serveur") {
                    adresse = modele.identifiants?.serveur ?? modele.adresse
                    serveur = true
                }
                Button("Se déconnecter", role: .destructive) { deconnecter = true }
            }
            if let r = reglages {
                GroupeTelephone(r: r, demandes: demandes, recharger: { Task { await charger() } }) { c, v in await enregistrer(c, v) }
                ForEach(DefReglages.groupes, id: \.titre) { g in
                    Section(g.titre) {
                        ForEach(g.reglages, id: \.chemin) { d in
                            LigneReglage(d: d, valeur: DefReglages.lire(r, d.chemin)) { v in await enregistrer(d.chemin, v) }
                        }
                    }
                }
            } else if let e = erreur {
                Section { EtatErreur(message: e) { Task { await charger() } } }
            } else {
                Section { Chargement(texte: "Chargement des réglages…") }
            }
            GroupeAppareils(demandes: demandes)
        }
        .navigationTitle("Réglages")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: client.etat.estConnecte) {
            guard client.etat.estConnecte else { return }
            await charger()
        }
        .alert("Serveur", isPresented: $serveur) {
            TextField("https://ccs.exemple.fr", text: $adresse)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
            Button("Changer") { changerServeur() }
            Button("Annuler", role: .cancel) {}
        } message: {
            Text("Changer de serveur déconnecte ce téléphone.")
        }
        .confirmationDialog("Se déconnecter ?", isPresented: $deconnecter, titleVisibility: .visible) {
            Button("Se déconnecter", role: .destructive) { modele.deconnecter() }
        } message: {
            Text("Il faudra se reconnecter sur ce téléphone (le jeton reste révocable depuis la liste des appareils).")
        }
        .demandes(demandes)
    }

    private var modeConnexion: String {
        guard let i = modele.identifiants else { return "" }
        if i.portier { return "connexion Portier (cookies)" }
        if i.viaPortier { return "Portier, puis jeton d'appareil" }
        return "jeton d'appareil"
    }

    private func changerServeur() {
        let avant = modele.adresse
        if !modele.changerAdresse(adresse) {
            modele.avis.dire("Adresse invalide.")
            return
        }
        if modele.adresse != avant { modele.deconnecter() }
    }

    private func charger() async {
        do {
            reglages = try await client.appeler("settings.get", en: Reglages.self).settings
            erreur = nil
        } catch {
            erreur = texteErreur(error)
        }
    }

    /// Enregistre une valeur ; rend l'erreur à afficher sous le champ, ou nil.
    private func enregistrer(_ chemin: String, _ valeur: JSON) async -> String? {
        do {
            _ = try await client.appeler("settings.set", ["path": .chaine(chemin), "value": valeur])
            if let r = reglages { reglages = DefReglages.ecrire(r, chemin, valeur) }
            modele.avis.dire("Enregistré.")
            return nil
        } catch {
            return texteErreur(error)
        }
    }
}

/// Un réglage : interrupteur, liste de choix ou champ (nombre, heure, texte) enregistré par « OK ».
@MainActor
struct LigneReglage: View {
    let d: DefReglages.Def
    let valeur: JSON?
    let enregistrer: (JSON) async -> String?

    @State private var erreur: String? = nil
    @State private var occupe = false
    @State private var champ: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            switch d.genre {
            case .booleen:
                Toggle(d.libelle, isOn: Binding<Bool>(get: { DefReglages.booleen(valeur) }, set: { envoyer(.booleen($0)) }))
                    .disabled(occupe)
            case .choix(let options):
                let actuel = DefReglages.texte(valeur)
                Picker(d.libelle, selection: Binding<String>(get: { actuel }, set: { v in if v != actuel { envoyer(.chaine(v)) } })) {
                    if !options.contains(where: { $0.valeur == actuel }) { Text(actuel).tag(actuel) }
                    ForEach(options, id: \.valeur) { o in Text(o.libelle).tag(o.valeur) }
                }
                .disabled(occupe)
            default:
                let initial = DefReglages.texte(valeur)
                let texte = champ ?? initial
                Text(d.libelle).font(.subheadline)
                HStack {
                    TextField(d.genre == .heure ? "HH:MM" : "", text: Binding<String>(get: { texte }, set: { champ = $0; erreur = nil }))
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(clavier)
                        .onSubmit { if texte != initial { valider(texte) } }
                        .disabled(occupe)
                    if texte != initial {
                        Button("OK") { valider(texte) }.buttonStyle(.borderless).disabled(occupe)
                    }
                }
            }
            if !d.aide.isEmpty { Text(d.aide).font(.caption).foregroundStyle(.secondary) }
            if let e = erreur { Text(e).font(.caption).foregroundStyle(.red) }
        }
    }

    private var clavier: UIKeyboardType {
        switch d.genre {
        case .nombre: return .decimalPad
        case .heure: return .numbersAndPunctuation
        default: return .URL
        }
    }

    private func envoyer(_ v: JSON) {
        occupe = true
        Task { @MainActor in
            erreur = await enregistrer(v)
            if erreur == nil { champ = nil }
            occupe = false
        }
    }

    private func valider(_ texte: String) {
        switch d.genre {
        case .nombre(let min, let max, let entier):
            let r = DefReglages.nombre(texte, min: min, max: max, entier: entier)
            if let n = r.valeur { envoyer(.nombre(n)) } else { erreur = r.erreur }
        case .heure:
            if let h = DefReglages.heure(texte) { envoyer(.chaine(h)) } else { erreur = "Heure attendue (HH:MM)." }
        default:
            envoyer(.chaine(texte.trimmingCharacters(in: .whitespaces)))
        }
    }
}

/// Téléphone (ntfy) : réglages, nouveau canal, lien d'abonnement (à ouvrir dans ntfy), essai.
@MainActor
private struct GroupeTelephone: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.openURL) private var ouvrirUrl
    let r: JSON
    let demandes: Demandes
    let recharger: () -> Void
    let enregistrer: (String, JSON) async -> String?

    @State private var resultat: String? = nil
    @State private var lien: String? = nil
    @State private var occupe = false

    private var client: CcsClient { return modele.client }

    var body: some View {
        let g = DefReglages.telephone
        Section {
            ForEach(g.reglages, id: \.chemin) { d in
                LigneReglage(d: d, valeur: DefReglages.lire(r, d.chemin)) { v in await enregistrer(d.chemin, v) }
            }
            Button("Créer un nouveau canal") { nouveauCanal() }.disabled(occupe)
            Button("Lien d'abonnement") {
                faire { lien = try await client.appeler("phone.qr", en: QrTelephone.self).url }
            }
            .disabled(occupe)
            Button("Envoyer un essai") {
                faire {
                    let e = try await client.appeler("phone.test", en: EssaiTelephone.self)
                    if e.ok { modele.avis.dire(e.message) } else { resultat = e.message }
                }
            }
            .disabled(occupe)
            if let m = resultat { Text(m).font(.caption).foregroundStyle(.red) }
            if let u = lien {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Ouvre ce lien dans l'application ntfy (ou scanne le QR code de la version web) :").font(.caption)
                    Text(u).font(.caption).foregroundStyle(Color.accentCcs).textSelection(.enabled)
                    HStack {
                        Button("Copier") {
                            copier(u)
                            modele.avis.dire("Lien copié.")
                        }
                        .buttonStyle(.bordered)
                        Button("Ouvrir dans ntfy") {
                            let ntfy = u.replacingOccurrences(of: "^https?://", with: "ntfy://", options: .regularExpression)
                            if let url = URL(string: ntfy) {
                                ouvrirUrl(url) { ok in
                                    if !ok, let web = URL(string: u) { ouvrirUrl(web) }
                                }
                            }
                        }
                        .buttonStyle(.bordered)
                    }
                }
            }
        } header: {
            Text(g.titre)
        } footer: {
            Text(g.texte)
        }
    }

    private func faire(_ bloc: @escaping () async throws -> Void) {
        occupe = true
        resultat = nil
        Task { @MainActor in
            do { try await bloc() } catch { resultat = texteErreur(error) }
            occupe = false
        }
    }

    private func nouveauCanal() {
        Task { @MainActor in
            guard await demandes.confirmer("Créer un nouveau canal ?",
                                           "L'ancien canal ne recevra plus rien : il faudra se réabonner au nouveau sur chaque téléphone.",
                                           "Créer le canal") else { return }
            faire {
                _ = try await client.appeler("phone.new_topic", en: CanalTelephone.self)
                modele.avis.dire("Nouveau canal créé.")
                lien = nil
                recharger()
            }
        }
    }
}

/// Appareils connectés (`/api/tokens`), révocables (`/api/revoke`).
@MainActor
private struct GroupeAppareils: View {
    @Environment(ModeleAppli.self) private var modele
    let demandes: Demandes

    @State private var liste: [Acces]? = nil
    @State private var erreur: String? = nil

    var body: some View {
        Section {
            if let e = erreur { Text(e).font(.caption).foregroundStyle(.secondary) }
            if let l = liste {
                ForEach(l) { t in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(t.name.isEmpty ? (genresAcces[t.kind ?? ""] ?? t.kind ?? "") : t.name).font(.subheadline.weight(.semibold))
                            Text((genresAcces[t.kind ?? ""] ?? t.kind ?? "") + (t.dernierUsage.map { " · utilisé le " + EcranReglagesDates.texte($0) } ?? ""))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Révoquer", role: .destructive) { revoquer(t) }.buttonStyle(.borderless)
                    }
                }
            } else if erreur == nil {
                Chargement()
            }
        } header: {
            Text("Appareils")
        } footer: {
            Text("Navigateurs, appareils retenus et applications connectés à ton compte.")
        }
        .task(id: modele.identifiants?.utilisateur ?? "") { await charger() }
    }

    private func charger() async {
        guard let i = modele.identifiants else { return }
        do {
            if let l = try await ApiHttp.acces(i) {
                liste = l.tokens.sorted { ($0.dernierUsage ?? 0) > ($1.dernierUsage ?? 0) }
                erreur = nil
            } else {
                erreur = "Liste indisponible avec cette connexion : le serveur ne la donne qu'à une session de navigateur ou Portier. Ouvre la version web."
            }
        } catch {
            erreur = "Liste indisponible : \(texteErreur(error))"
        }
    }

    private func revoquer(_ t: Acces) {
        Task { @MainActor in
            guard await demandes.confirmer("Révoquer cet accès ?",
                                           "L'appareil devra se reconnecter (si c'est ce téléphone : il faudra se reconnecter ici).",
                                           "Révoquer", danger: true),
                  let i = modele.identifiants else { return }
            if let m = await ApiHttp.revoquer(i, id: t.id) {
                modele.avis.dire(m)
            } else {
                modele.avis.dire("Accès révoqué.")
                await charger()
            }
        }
    }
}

enum EcranReglagesDates {
    private static let format: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "fr_FR")
        f.dateStyle = .short
        f.timeStyle = .short
        return f
    }()

    static func texte(_ s: Double) -> String { return format.string(from: Date(timeIntervalSince1970: s)) }
}
