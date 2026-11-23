import SwiftUI

/**
 * Onglet Fichiers (`web/files-browser.js`) : en haut, la barre des appareils (« Serveur CCS » puis
 * chaque PC du réseau maillé, grisé s'il est injoignable) ; dessous, les dossiers permis de
 * l'appareil choisi (personnel, /var/www, /srv), lus par sa propre connexion (`ConnexionFichiers`).
 */
@MainActor
struct EcranFichiersOnglet: View {
    @Environment(ModeleAppli.self) private var modele
    @State private var racines: RacinesFichiers? = nil
    @State private var erreur: String? = nil
    @State private var racine: String? = nil

    private var fichiers: ConnexionFichiers { return modele.fichiers }
    private var client: CcsClient { return fichiers.client }
    private var appareil: String { return fichiers.appareil }
    private var nomAppareil: String { return Appareils.nom(appareil, modele.machines) }

    /// Connexion de l'appareil coupée avant d'avoir lu ses dossiers : pourquoi.
    private var coupure: String? {
        guard racines == nil else { return nil }
        if case .horsLigne(let raison, _) = client.etat, fichiers.aPart { return raison }
        return nil
    }

    var body: some View {
        VStack(spacing: 0) {
            barreAppareils
            Group {
                if let r = racines {
                    let base = racine.flatMap { r.roots.contains($0) ? $0 : nil } ?? r.home
                    PanneauFichiers(base: base, home: r.home, proteger: false, entete: r.roots.count > 1 ? AnyView(choix(r, base)) : nil)
                        .id("\(appareil)|\(base)")
                } else if let e = erreur ?? coupure {
                    EtatErreur(message: Appareils.messageInjoignable(nomAppareil, serveur: appareil.isEmpty, e)) {
                        erreur = nil
                        if client.etat.estConnecte { Task { await charger() } } else { fichiers.reessayer() }
                    }
                    .frame(maxHeight: .infinity)
                } else {
                    Chargement(texte: appareil.isEmpty ? nil : "Connexion à \(nomAppareil)…")
                        .frame(maxHeight: .infinity)
                }
            }
        }
        .navigationTitle("Fichiers")
        .navigationBarTitleDisplayMode(.inline)
        // la connexion principale arrive (identifiants, machine pilotée) : celle de l'appareil suit
        .task(id: "\(modele.client.etat.estConnecte)|\(modele.client.machine)") {
            fichiers.ouvrir()
            if modele.client.etat.estConnecte { await modele.rafraichirMachines() }
        }
        .task(id: "\(ObjectIdentifier(client).hashValue)|\(client.etat.estConnecte)") {
            guard client.etat.estConnecte, racines == nil else { return }
            await charger()
        }
    }

    // MARK: appareils

    @ViewBuilder
    private var barreAppareils: some View {
        let liste = Appareils.liste(modele.machines)
        if liste.count > 1 {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(liste) { a in puce(a) }
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 4)
            }
            Divider()
        }
    }

    private func puce(_ a: Appareils.Appareil) -> some View {
        let choisi = a.id == appareil
        return Button {
            choisir(a.id)
        } label: {
            HStack(spacing: 6) {
                Image(systemName: a.icone).font(.subheadline)
                VStack(alignment: .leading, spacing: 0) {
                    Text(a.nom).font(.subheadline.weight(choisi ? .semibold : .regular)).lineLimit(1)
                    if let r = a.raison { Text(r).font(.caption2).foregroundStyle(.secondary).lineLimit(1) }
                }
            }
            .padding(.horizontal, 12)
            .frame(minHeight: 44)
            .background(Capsule().fill(choisi ? Color.accentCcs.opacity(0.3) : Color.secondary.opacity(0.15)))
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .disabled(!a.joignable)
        .opacity(a.joignable ? 1 : 0.5)
        .accessibilityLabel(a.joignable ? "Fichiers de \(a.nom)" : "\(a.nom) : \(a.raison ?? "injoignable")")
        .accessibilityAddTraits(choisi ? .isSelected : [])
    }

    private func choisir(_ id: String) {
        guard id != appareil else { return }
        racines = nil
        racine = nil
        erreur = nil
        // un fichier copié sur un appareil ne se colle pas sur un autre
        Presse.partage.tenu = nil
        fichiers.choisir(id)
    }

    // MARK: racines

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
                            .frame(minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(x == base ? .isSelected : [])
                }
            }
            .padding(.horizontal, 12)
        }
    }

    private func charger() async {
        let c = client
        do {
            let r = try await c.appeler("files.roots", delai: 20, en: RacinesFichiers.self)
            guard c === client else { return }      // autre appareil choisi entre-temps
            racines = r
            erreur = nil
        } catch {
            guard c === client else { return }
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
