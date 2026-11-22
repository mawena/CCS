import SwiftUI
import UIKit

/**
 * Mot de passe root depuis l'iPhone (phase 34) : écoute `root.*` du pont, montre la feuille de
 * saisie au premier plan, répond par `root.answer`, oublie par `root.forget`.
 *
 * Le mot de passe n'est JAMAIS gardé ici : il vit dans l'état de la feuille le temps de la frappe,
 * part dans `root.answer`, et la feuille le vide aussitôt. Ni Coffre, ni Preferences, ni
 * @AppStorage/@SceneStorage, ni journal.
 */
@MainActor
@Observable
final class GardienRoot {
    private(set) var suivi = SuiviRoot()
    /// Envoi de `root.answer` en cours (vérification par sudo : jusqu'à 30 s).
    private(set) var envoi = false
    /// Erreur de la dernière réponse (mauvais mot de passe, conflit…), pour la demande `idErreur`.
    private(set) var erreurEnvoi: String? = nil
    @ObservationIgnored private var idErreur: String? = nil

    private let client: CcsClient
    private let dire: (String) -> Void
    @ObservationIgnored private var minuteur: Task<Void, Never>? = nil

    init(client: CcsClient, dire: @escaping (String) -> Void) {
        self.client = client
        self.dire = dire
        for nom in SuiviRoot.noms {
            client.ecouter(nom, pour: self) { [weak self] d in self?.recu(nom, d) }
        }
    }

    private static var maintenant: Double { return Date().timeIntervalSince1970 }

    /// Erreur à montrer pour la demande en cours : celle de notre envoi, sinon celle du pont.
    var erreur: String? {
        guard let d = suivi.demande else { return nil }
        if let e = erreurEnvoi, idErreur == d.id { return e }
        return d.erreur
    }

    private func recu(_ nom: String, _ d: JSON) {
        guard let ev = EvRoot.lire(nom, d, maintenant: GardienRoot.maintenant) else { return }
        if case .demande(let dem) = ev, dem.erreur != nil, idErreur == dem.id {
            erreurEnvoi = nil          // le pont redit l'erreur : la sienne fait foi
        }
        if let m = suivi.recevoir(ev, maintenant: GardienRoot.maintenant) { dire(m) }
        armer()
    }

    /// `root.status` : demande en attente et mot de passe gardé (démarrage, reconnexion, premier plan).
    func lireEtat() async {
        guard client.etat.estConnecte else { return }
        guard let e = try? await client.appeler("root.status", delai: 10, en: EtatRoot.self) else { return }
        suivi.etat(e, maintenant: GardienRoot.maintenant)
        armer()
    }

    /// Envoie le mot de passe saisi (la feuille l'a déjà effacé de son champ).
    func envoyer(_ motDePasse: String) async {
        guard let d = suivi.demande, !envoi, !motDePasse.isEmpty else { return }
        envoi = true
        erreurEnvoi = nil
        defer { envoi = false }
        do {
            let r = try await client.appeler("root.answer", ["id": .chaine(d.id), "password": .chaine(motDePasse)], delai: 45)
            if r.bool("ok") {
                suivi.retirer(d.id)
                dire("Mot de passe root gardé 1 h sur \(nomMachine(d)).")
                await lireEtat()
            } else {
                let m = r.texteOuNul("error") ?? "Mot de passe refusé."
                // trois mauvais essais : `root.resolved` a déjà fermé la feuille, l'avis le dit
                if suivi.demande?.id == d.id { noterErreur(d.id, m) } else { dire(m) }
            }
        } catch let e as RpcErreur where e.code == "introuvable" {
            suivi.retirer(d.id)
            dire("Demande root déjà réglée ou expirée.")
        } catch {
            noterErreur(d.id, texteErreur(error))
        }
        armer()
    }

    /// « Refuser » : `root.answer {id, cancel: true}` ; la feuille se ferme tout de suite.
    func refuser() async {
        guard let d = suivi.demande else { return }
        suivi.retirer(d.id)
        armer()
        _ = try? await client.appeler("root.answer", ["id": .chaine(d.id), "cancel": .booleen(true)], delai: 15)
    }

    /// « Plus tard » : la feuille se ferme, la demande reste (bandeau « Répondre »).
    func masquer() { suivi.masquee = true }

    /// Rouvre la feuille (bandeau, lien `ccs://root`) ; relit l'état si rien n'est connu.
    func afficher() {
        if suivi.demande != nil {
            suivi.masquee = false
        } else {
            Task { await self.lireEtat() }
        }
    }

    /// « Oublier » : `root.forget` efface le mot de passe gardé (et la demande en cours).
    func oublier() async {
        do {
            let r = try await client.appeler("root.forget", delai: 15)
            suivi.oublie()
            dire(r.bool("had") ? "Mot de passe root oublié." : "Aucun mot de passe root gardé.")
        } catch {
            dire(texteErreur(error))
        }
        armer()
    }

    /// Autre machine pilotée, déconnexion : rien de l'ancienne n'est gardé.
    func vider() {
        suivi.vider()
        erreurEnvoi = nil
        idErreur = nil
        minuteur?.cancel()
        minuteur = nil
    }

    private func noterErreur(_ id: String, _ m: String) {
        idErreur = id
        erreurEnvoi = m
    }

    private func nomMachine(_ d: DemandeRoot) -> String {
        let m = d.machine.isEmpty ? suivi.machine : d.machine
        return m.isEmpty ? "la machine" : m
    }

    /// Réveil à la prochaine échéance (demande expirée : la feuille se ferme ; mot de passe effacé).
    private func armer() {
        minuteur?.cancel()
        guard let fin = suivi.prochaineEcheance else { minuteur = nil; return }
        let attente = max(0.2, fin - GardienRoot.maintenant)
        minuteur = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(min(attente, 4000) * 1_000_000_000))
            if Task.isCancelled { return }
            guard let s = self else { return }
            s.suivi.expirer(maintenant: GardienRoot.maintenant)
            s.armer()
        }
    }
}

// MARK: feuille

/// Feuille « <machine> demande le mot de passe root » : commande, mot de passe, Envoyer / Refuser.
@MainActor
struct FeuilleRoot: View {
    @Environment(ModeleAppli.self) private var modele

    var body: some View {
        let g = modele.root
        NavigationStack {
            if let d = g.suivi.demande {
                FormulaireRoot(demande: d)
                    .id(d.id)                  // nouvelle demande : champ remis à neuf
            } else {
                ContentUnavailableView("Demande réglée", systemImage: "checkmark.shield")
            }
        }
        .interactiveDismissDisabled(true)
    }
}

@MainActor
private struct FormulaireRoot: View {
    @Environment(ModeleAppli.self) private var modele
    let demande: DemandeRoot
    /// Mot de passe en cours de frappe : mémoire de la vue seulement, vidé dès l'envoi.
    @State private var motDePasse = ""
    @FocusState private var focus: Bool

    var body: some View {
        let g = modele.root
        Form {
            Section {
                Text(demande.commande.isEmpty ? "(commande inconnue)" : demande.commande)
                    .font(.system(.callout, design: .monospaced))
                    .textSelection(.enabled)
            } header: {
                Text("Commande")
            } footer: {
                TimelineView(.periodic(from: .now, by: 1)) { ctx in
                    let reste = demande.restant(maintenant: ctx.date.timeIntervalSince1970)
                    Text("\(demande.texteEssais) Demande abandonnée dans \(texteMinutesSecondes(reste)).")
                }
            }
            Section {
                SecureField("Mot de passe", text: $motDePasse)
                    // `.password` sans domaine associé : iOS ne propose pas de l'enregistrer
                    .textContentType(.password)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .privacySensitive()
                    .focused($focus)
                    .submitLabel(.send)
                    .onSubmit { envoyer() }
                    .disabled(g.envoi)
                if let e = g.erreur {
                    Text(e).font(.footnote).foregroundStyle(.red)
                }
            } footer: {
                Text("Vérifié par sudo puis gardé en mémoire 1 h sur \(demande.machine.isEmpty ? "la machine" : demande.machine), jamais sur ce téléphone.")
            }
            Section {
                Button {
                    envoyer()
                } label: {
                    HStack {
                        Text("Envoyer")
                        if g.envoi {
                            Spacer()
                            ProgressView().controlSize(.small)
                        }
                    }
                }
                .disabled(g.envoi || motDePasse.isEmpty)
                Button("Refuser", role: .destructive) {
                    motDePasse = ""
                    Task { await g.refuser() }
                }
                .disabled(g.envoi)
            }
        }
        .navigationTitle(demande.titre)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Plus tard") {
                    motDePasse = ""
                    g.masquer()
                }
            }
        }
        .onAppear { focus = true }
        .onDisappear { motDePasse = "" }
    }

    private func envoyer() {
        let g = modele.root
        guard !motDePasse.isEmpty, !g.envoi else { return }
        let m = motDePasse
        motDePasse = ""
        Task { await g.envoyer(m) }
    }
}

// MARK: présentation au premier plan

/**
 * Montre la feuille root au-dessus de tout (même d'une autre feuille ouverte) : elle est présentée
 * par le contrôleur le plus haut de la fenêtre, pas par la hiérarchie SwiftUI.
 */
@MainActor
enum PresentationRoot {
    private static weak var hote: UIViewController?

    static func montrer(_ modele: ModeleAppli) {
        if let h = hote, h.presentingViewController != nil, !h.isBeingDismissed { return }
        guard let haut = plusHaut() else { return }
        let v = UIHostingController(rootView: AnyView(
            FeuilleRoot()
                .environment(modele)
                .tint(Color.accentCcs)
        ))
        v.isModalInPresentation = true
        haut.present(v, animated: true)
        hote = v
    }

    static func cacher() {
        guard let h = hote else { return }
        hote = nil
        if h.presentingViewController != nil { h.dismiss(animated: true) }
    }

    private static func plusHaut() -> UIViewController? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let fenetres = scenes.flatMap { $0.windows }
        let fenetre = fenetres.first(where: { $0.isKeyWindow }) ?? fenetres.first
        var haut = fenetre?.rootViewController
        while let p = haut?.presentedViewController, !p.isBeingDismissed { haut = p }
        return haut
    }
}

// MARK: bandeau

/// Bandeau sous celui de la machine : « root gardé, X min » avec « Oublier », ou demande mise de côté.
@MainActor
struct BandeauRoot: View {
    @Environment(ModeleAppli.self) private var modele

    var body: some View {
        let g = modele.root
        if let d = g.suivi.demande, g.suivi.masquee {
            ligne(icone: "key.fill", texte: d.titre, bouton: "Répondre") { g.afficher() }
        } else if g.suivi.gardeJusqua != nil {
            TimelineView(.periodic(from: .now, by: 30)) { ctx in
                if let n = g.suivi.minutesGarde(maintenant: ctx.date.timeIntervalSince1970) {
                    let m = g.suivi.machine
                    ligne(icone: "lock.open.fill", texte: "Root gardé\(m.isEmpty ? "" : " sur \(m)"), \(n) min",
                          bouton: "Oublier") { Task { await g.oublier() } }
                }
            }
        }
    }

    private func ligne(icone: String, texte: String, bouton: String, faire: @escaping () -> Void) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icone).font(.subheadline)
            Text(texte)
                .font(.subheadline)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button(bouton, action: faire).font(.subheadline)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 6)
        .background(Color.orange.opacity(0.18))
    }
}
