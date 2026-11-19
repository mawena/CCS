import SwiftUI

/// Onglet Fichiers (`web/files-browser.js`) : dossiers permis du serveur (personnel, /var/www, /srv).
@MainActor
struct EcranFichiersOnglet: View {
    @Environment(ModeleAppli.self) private var modele
    @State private var racines: RacinesFichiers? = nil
    @State private var erreur: String? = nil
    @State private var racine: String? = nil

    var body: some View {
        Group {
            if let r = racines {
                let base = racine.flatMap { r.roots.contains($0) ? $0 : nil } ?? r.home
                PanneauFichiers(base: base, home: r.home, proteger: false, entete: r.roots.count > 1 ? AnyView(choix(r, base)) : nil)
                    .id(base)
            } else if let e = erreur {
                EtatErreur(message: e) { Task { await charger() } }
            } else {
                Chargement()
            }
        }
        .navigationTitle("Fichiers")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: modele.client.etat.estConnecte) {
            guard modele.client.etat.estConnecte, racines == nil else { return }
            await charger()
        }
    }

    private func choix(_ r: RacinesFichiers, _ base: String) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(r.roots, id: \.self) { x in
                    Button {
                        racine = x
                    } label: {
                        Etiquette(texte: x == r.home ? "Personnel" : x,
                                  fond: x == base ? Color.accentCcs.opacity(0.3) : Color.secondary.opacity(0.15))
                            .font(.subheadline)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
        }
    }

    private func charger() async {
        do {
            racines = try await modele.client.appeler("files.roots", en: RacinesFichiers.self)
            erreur = nil
        } catch {
            erreur = texteErreur(error)
        }
    }
}

/// Fichiers d'un projet (ouvert depuis le chat).
@MainActor
struct EcranFichiersProjet: View {
    let cwd: String

    var body: some View {
        PanneauFichiers(base: cwd)
            .navigationTitle(Fichiers.nom(cwd))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar(.hidden, for: .tabBar)
    }
}
