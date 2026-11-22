import SwiftUI

@main
struct CCSApp: App {
    @State private var modele = ModeleAppli()

    var body: some Scene {
        WindowGroup {
            Racine()
                .environment(modele)
                .tint(Color.accentCcs)
                .preferredColorScheme(schema(modele.theme))
                .overlay { VueAvis(avis: modele.avis) }
        }
    }

    private func schema(_ t: Theme) -> ColorScheme? {
        switch t {
        case .systeme: return nil
        case .clair: return .light
        case .sombre: return .dark
        }
    }
}

/// Connexion tant qu'il n'y a pas d'identifiants, puis l'écran principal.
struct Racine: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.scenePhase) private var phase

    var body: some View {
        Group {
            if modele.identifiants == nil {
                EcranConnexion()
            } else {
                EcranPrincipal()
            }
        }
        .onChange(of: phase) { _, nouvelle in
            // retour au premier plan : nouvel essai tout de suite, ou vérification de la connexion
            if nouvelle == .active {
                modele.client.reessayer()
                // demande root faite pendant que l'appli dormait (avis ntfy touché, puis retour ici)
                Task { await modele.root.lireEtat() }
            }
            if nouvelle != .inactive { modele.veille.premierPlan(nouvelle == .active) }
        }
        .onOpenURL { u in modele.recevoir(u) }
        // feuille du mot de passe root au premier plan, au-dessus de toute autre feuille
        .onChange(of: modele.identifiants != nil && modele.root.suivi.aMontrer, initial: true) { _, montrer in
            if montrer { PresentationRoot.montrer(modele) } else { PresentationRoot.cacher() }
        }
    }
}
