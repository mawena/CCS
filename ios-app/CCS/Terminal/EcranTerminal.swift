import SwiftTerm
import SwiftUI
import UIKit

/// Vue SwiftTerm de la session, gardée d'un affichage à l'autre (elle porte l'émulateur).
struct VueTerminalSwiftTerm: UIViewRepresentable {
    let session: SessionTerminal

    func makeUIView(context: Context) -> UIView {
        let boite = UIView()
        boite.backgroundColor = session.vue.nativeBackgroundColor
        let v = session.vue
        v.removeFromSuperview()
        v.translatesAutoresizingMaskIntoConstraints = false
        boite.addSubview(v)
        NSLayoutConstraint.activate([
            v.leadingAnchor.constraint(equalTo: boite.leadingAnchor, constant: 4),
            v.trailingAnchor.constraint(equalTo: boite.trailingAnchor, constant: -4),
            v.topAnchor.constraint(equalTo: boite.topAnchor, constant: 2),
            v.bottomAnchor.constraint(equalTo: boite.bottomAnchor),
        ])
        return boite
    }

    func updateUIView(_ uiView: UIView, context: Context) {}
}

/**
 * Un terminal en plein écran (`web/terminal.js`) : l'émulateur, la barre de touches (Échap, Tab,
 * Ctrl et Alt collants, flèches, symboles difficiles à taper, Début/Fin, pages), Coller, Copier,
 * taille du texte, Fermer.
 */
@MainActor
struct EcranTerminal: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.dismiss) private var fermerEcran
    let id: String
    @State private var taille = Prefs.tailleTerminal
    @State private var ctrl = false
    @State private var alt = false
    @State private var confirmerFermeture = false

    private func sousTitre(_ s: SessionTerminal?) -> String {
        guard let s = s else { return "" }
        let chemin: String = TachesFond.cheminCourt(s.cwd)
        return s.fin != nil ? chemin + " · terminé" : chemin
    }

    var body: some View {
        let s = modele.terminaux.session(id)
        Group {
            if let s = s {
                VStack(spacing: 0) {
                    VueTerminalSwiftTerm(session: s)
                    BarreTouches(session: s, ctrl: $ctrl, alt: $alt)
                }
                .background(Color(red: 0x1E / 255.0, green: 0x1E / 255.0, blue: 0x22 / 255.0))
                .onReceive(NotificationCenter.default.publisher(for: .terminalViewControlModifierReset)) { _ in ctrl = false }
                .onReceive(NotificationCenter.default.publisher(for: .terminalViewMetaModifierReset)) { _ in alt = false }
                .task(id: s.id) {
                    // le clavier ne s'ouvre qu'une fois la vue dans la fenêtre
                    try? await Task.sleep(nanoseconds: 300_000_000)
                    if s.fin == nil { _ = s.vue.becomeFirstResponder() }
                }
            } else {
                EtatVide("Ce terminal n'est plus ouvert dans l'appli.")
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .toolbar {
            ToolbarItem(placement: .principal) {
                VStack(spacing: 0) {
                    Text(s?.titre ?? "Terminal").font(.headline).lineLimit(1)
                    Text(sousTitre(s))
                        .font(.caption2).foregroundStyle(.secondary).lineLimit(1).truncationMode(.head)
                }
            }
            if let s = s {
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button {
                        if s.vue.isFirstResponder { _ = s.vue.resignFirstResponder() } else { _ = s.vue.becomeFirstResponder() }
                    } label: { Image(systemName: "keyboard") }
                        .disabled(s.fin != nil)
                        .accessibilityLabel("Clavier")
                    Menu {
                        Button {
                            if UIPasteboard.general.hasStrings { s.coller() } else { modele.avis.dire("Le presse-papiers est vide.") }
                        } label: { Label("Coller", systemImage: "doc.on.clipboard") }
                            .disabled(s.fin != nil)
                        Button {
                            UIPasteboard.general.string = s.texte().trimmingCharacters(in: .whitespacesAndNewlines)
                            modele.avis.dire("Copié.")
                        } label: { Label("Copier tout le texte", systemImage: "doc.on.doc") }
                        Button { zoomer(1) } label: { Label("Texte plus grand", systemImage: "textformat.size.larger") }
                        Button { zoomer(-1) } label: { Label("Texte plus petit", systemImage: "textformat.size.smaller") }
                        Button(role: .destructive) {
                            if s.fin != nil {
                                modele.terminaux.retirer(s)
                                fermerEcran()
                            } else {
                                confirmerFermeture = true
                            }
                        } label: { Label(s.fin != nil ? "Retirer" : "Fermer le terminal", systemImage: "xmark") }
                    } label: { Image(systemName: "ellipsis.circle") }
                }
            }
        }
        .confirmationDialog("Fermer le terminal « \(s?.nom ?? "") » ?", isPresented: $confirmerFermeture, titleVisibility: .visible) {
            Button("Fermer", role: .destructive) {
                guard let s = s else { return }
                Task {
                    do {
                        try await modele.terminaux.fermer(s)
                        fermerEcran()
                    } catch {
                        modele.avis.dire(texteErreur(error))
                    }
                }
            }
        } message: {
            Text("Ce qui y tourne est arrêté.")
        }
    }

    private func zoomer(_ pas: Int) {
        taille = Touches.borner(taille + pas)
        Prefs.tailleTerminal = taille
        modele.terminaux.session(id)?.changerTaille(taille)
    }
}

/// Barre de touches : deux rangées défilantes, au-dessus du clavier du téléphone.
@MainActor
private struct BarreTouches: View {
    let session: SessionTerminal
    @Binding var ctrl: Bool
    @Binding var alt: Bool

    var body: some View {
        let actif = session.fin == nil
        VStack(spacing: 4) {
            rangee {
                touche("Échap") { session.taper(Touches.echap) }
                touche("Tab") { session.taper(Touches.tab) }
                collant("Ctrl", arme: ctrl) {
                    ctrl.toggle()
                    session.vue.controlModifier = ctrl
                }
                collant("Alt", arme: alt) {
                    alt.toggle()
                    session.vue.metaModifier = alt
                }
                ForEach(Touches.Fleche.allCases, id: \.self) { f in
                    touche(f.libelle) {
                        session.fleche(f)
                        ctrl = false
                        alt = false
                    }
                }
            }
            rangee {
                ForEach(Touches.symboles, id: \.self) { sym in
                    touche(sym) { session.vue.insertText(sym) }
                }
                touche("Début") { session.taper(Touches.debut) }
                touche("Fin") { session.taper(Touches.fin) }
                touche("PgPréc") { session.taper(Touches.pagePrecedente) }
                touche("PgSuiv") { session.taper(Touches.pageSuivante) }
            }
        }
        .padding(.vertical, 4)
        .background(.bar)
        .disabled(!actif)
    }

    private func rangee<C: View>(@ViewBuilder _ contenu: () -> C) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 4) { contenu() }.padding(.horizontal, 6)
        }
    }

    private func touche(_ libelle: String, _ faire: @escaping () -> Void) -> some View {
        Button(action: faire) {
            Text(libelle).font(.system(.callout, design: .monospaced)).frame(minWidth: 28)
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
    }

    @ViewBuilder
    private func collant(_ libelle: String, arme: Bool, _ faire: @escaping () -> Void) -> some View {
        if arme {
            Button(action: faire) {
                Text(libelle).font(.system(.callout, design: .monospaced)).frame(minWidth: 28)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
        } else {
            touche(libelle, faire)
        }
    }
}
