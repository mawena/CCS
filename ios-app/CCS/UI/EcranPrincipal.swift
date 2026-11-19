import SwiftUI

/// Onglets de l'appli, comme l'appli Android.
enum Onglet: String, CaseIterable, Hashable {
    case accueil, sessions, fichiers, git, plus

    var titre: String {
        switch self {
        case .accueil: return "Accueil"
        case .sessions: return "Sessions"
        case .fichiers: return "Fichiers"
        case .git: return "Git"
        case .plus: return "Plus"
        }
    }

    var icone: String {
        switch self {
        case .accueil: return "house"
        case .sessions: return "bubble.left.and.bubble.right"
        case .fichiers: return "folder"
        case .git: return "arrow.triangle.branch"
        case .plus: return "ellipsis"
        }
    }
}

/// Ce qu'ouvre l'écran Chat : une conversation de l'historique, ou un chat ouvert dans le pont.
struct DestChat: Hashable {
    var cwd: String
    var sessionId: String?
    var chemin: String?
    var titre: String?
    var chatId: String?
    /// Texte à envoyer une fois le chat ouvert (nouveau chat pour une tâche de la feuille de route).
    var aEnvoyer: String?
    /// Identifie cet envoi prévu (il ne part qu'une fois).
    var jeton: String?

    init(cwd: String, sessionId: String? = nil, chemin: String? = nil, titre: String? = nil, chatId: String? = nil,
         aEnvoyer: String? = nil, jeton: String? = nil) {
        self.cwd = cwd
        self.sessionId = sessionId
        self.chemin = chemin
        self.titre = titre
        self.chatId = chatId
        self.aEnvoyer = aEnvoyer
        self.jeton = jeton
    }

    /// Clé stable du chat (brouillon, citation) : dossier et session, ou chat du pont.
    var cle: String { return cwd + "|" + (sessionId ?? chatId ?? "") }
}

/// Écrans poussés dans la pile d'un onglet.
enum Destination: Hashable {
    case analyse
    case projet(String)
    case chat(DestChat)
    case fichier(chemin: String, ligne: Int?)
    case fichiersProjet(String)
    case gitProjet(String)
    case commit(cwd: String, id: String)
    case reglages
}

/// Écran principal : bandeau de connexion, onglets, une pile de navigation par onglet.
@MainActor
struct EcranPrincipal: View {
    @Environment(ModeleAppli.self) private var modele
    @State private var onglet: Onglet = .accueil
    @State private var piles: [Onglet: [Destination]] = [:]

    var body: some View {
        VStack(spacing: 0) {
            BandeauConnexion()
            TabView(selection: $onglet) {
                ForEach(Onglet.allCases, id: \.self) { o in
                    NavigationStack(path: pile(o)) {
                        racine(o)
                            .navigationDestination(for: Destination.self) { d in destination(d) }
                    }
                    .environment(\.naviguer, Naviguer { d in ajouter(d, dans: o) })
                    .tabItem { Label(o.titre, systemImage: o.icone) }
                    .tag(o)
                }
            }
        }
    }

    private func pile(_ o: Onglet) -> Binding<[Destination]> {
        return Binding<[Destination]>(
            get: { piles[o] ?? [] },
            set: { piles[o] = $0 }
        )
    }

    private func ajouter(_ d: Destination, dans o: Onglet) {
        var p = piles[o] ?? []
        p.append(d)
        piles[o] = p
    }

    @ViewBuilder
    private func racine(_ o: Onglet) -> some View {
        switch o {
        case .accueil: EcranAccueil()
        case .sessions: EcranSessions()
        case .fichiers: EcranFichiersOnglet()
        case .git: EcranGitOnglet()
        case .plus: EcranPlus()
        }
    }

    @ViewBuilder
    private func destination(_ d: Destination) -> some View {
        switch d {
        case .analyse: EcranAnalyse()
        case .projet(let cwd): EcranProjet(cwd: cwd)
        case .chat(let dest): EcranChat(dest: dest)
        case .fichier(let chemin, let ligne): EcranFichier(chemin: chemin, ligne: ligne)
        case .fichiersProjet(let cwd): EcranFichiersProjet(cwd: cwd)
        case .gitProjet(let cwd): EcranGitProjet(cwd: cwd)
        case .commit(let cwd, let id): EcranCommit(cwd: cwd, id: id)
        case .reglages: EcranReglages()
        }
    }
}

/// Bandeau discret tant que le WebSocket n'est pas ouvert.
@MainActor
struct BandeauConnexion: View {
    @Environment(ModeleAppli.self) private var modele

    var body: some View {
        let etat = modele.client.etat
        switch etat {
        case .connecte, .arrete, .refuse:
            EmptyView()
        case .connexion:
            ligne(texte: "Connexion au serveur…", attente: true, reessai: false)
        case .horsLigne(let raison, let attente):
            ligne(texte: "\(raison) Nouvel essai dans \(max(1, Int(attente))) s.", attente: false, reessai: true)
        }
    }

    private func ligne(texte: String, attente: Bool, reessai: Bool) -> some View {
        HStack(spacing: 12) {
            if attente { ProgressView().controlSize(.small) }
            Text(texte).font(.subheadline).frame(maxWidth: .infinity, alignment: .leading)
            if reessai {
                Button("Réessayer") { modele.client.reessayer() }.font(.subheadline)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 6)
        .background(Color.accentCcs.opacity(0.15))
    }
}

/// Écran d'un onglet pas encore porté.
@MainActor
struct EcranProvisoire: View {
    let titre: String
    let texte: String

    var body: some View {
        ContentUnavailableView(titre, systemImage: "hammer", description: Text("À venir. \(texte)"))
            .navigationTitle(titre)
    }
}

/// Onglet « Plus » : réglages, terminaux, analyse, thème, compte connecté, version web, déconnexion.
@MainActor
struct EcranPlus: View {
    @Environment(ModeleAppli.self) private var modele
    @State private var confirmer = false

    var body: some View {
        List {
            Section("Apparence") {
                Picker("Thème", selection: Binding<Theme>(get: { modele.theme }, set: { modele.changerTheme($0) })) {
                    ForEach(Theme.allCases, id: \.self) { t in Text(t.libelle).tag(t) }
                }
            }
            Section {
                NavigationLink(value: Destination.reglages) {
                    Label("Réglages", systemImage: "gearshape")
                }
                NavigationLink(value: Destination.analyse) {
                    Label("Analyse", systemImage: "chart.bar")
                }
                if let u = URL(string: modele.adresse + "/") {
                    Link(destination: u) {
                        Label("Ouvrir la version web", systemImage: "safari")
                    }
                }
            } footer: {
                Text("Réglages : notifications, serveur, téléphone (ntfy), appareils. Analyse : usage par projet, modèle, compte et heure.")
            }
            Section("Connexion") {
                LabeledContent("Serveur", value: modele.adresse.replacingOccurrences(of: "https://", with: ""))
                LabeledContent("Compte", value: (modele.identifiants?.utilisateur ?? "") + (modele.identifiants?.portier == true ? " (Portier)" : ""))
                Button("Se déconnecter", role: .destructive) { confirmer = true }
            }
        }
        .navigationTitle("Plus")
        .confirmationDialog("Se déconnecter ?", isPresented: $confirmer, titleVisibility: .visible) {
            Button("Se déconnecter", role: .destructive) { modele.deconnecter() }
        } message: {
            Text("Le jeton d'appareil est oublié sur ce téléphone ; révoque-le depuis la version web si besoin.")
        }
    }
}
