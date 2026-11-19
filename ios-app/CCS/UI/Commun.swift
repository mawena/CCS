import SwiftUI
import UIKit

// MARK: couleurs

extension Color {
    /// Couleurs de CCS (manifeste web) : accent #3584e4 ; avertissement et réussite de la version web.
    static let accentCcs = Color(red: 0x35 / 255.0, green: 0x84 / 255.0, blue: 0xE4 / 255.0)
    static let avertissement = Color(red: 0xE5 / 255.0, green: 0xA5 / 255.0, blue: 0x0A / 255.0)
    static let reussite = Color(red: 0x33 / 255.0, green: 0xD1 / 255.0, blue: 0x7A / 255.0)
    static let carte = Color(UIColor.secondarySystemGroupedBackground)
    static let fondGroupe = Color(UIColor.systemGroupedBackground)
    static let fondCode = Color(UIColor { (t: UITraitCollection) -> UIColor in
        t.userInterfaceStyle == .dark ? UIColor(red: 0.10, green: 0.10, blue: 0.12, alpha: 1) : UIColor(red: 0.953, green: 0.953, blue: 0.965, alpha: 1)
    })

    /// Couleur `#rrggbb` du serveur (compte), ou nil si elle est illisible.
    init?(hex: String?) {
        guard var t = hex?.trimmingCharacters(in: .whitespaces), !t.isEmpty else { return nil }
        if t.hasPrefix("#") { t.removeFirst() }
        guard t.count == 6, let v = UInt32(t, radix: 16) else { return nil }
        self.init(red: Double((v >> 16) & 0xFF) / 255.0, green: Double((v >> 8) & 0xFF) / 255.0, blue: Double(v & 0xFF) / 255.0)
    }
}

/// Couleur d'un compte, ou l'accent si elle est illisible.
func couleurDe(_ texte: String?) -> Color {
    return Color(hex: texte) ?? .accentCcs
}

/// Message d'une erreur pour l'utilisateur.
func texteErreur(_ e: Error) -> String {
    if let r = e as? RpcErreur { return r.message }
    if let h = e as? ErreurHttp { return h.message }
    let m = e.localizedDescription
    return m.isEmpty ? "Erreur inattendue." : m
}

func copier(_ texte: String) {
    UIPasteboard.general.string = texte
}

// MARK: avis (les « toasts » de la version web)

/// Messages courts en bas de l'écran, avec action facultative (« Réessayer », « Annuler »).
@MainActor
@Observable
final class Avis {
    struct Message: Identifiable {
        let id = UUID()
        let texte: String
        let action: String?
        let faire: (() -> Void)?
    }

    private(set) var courant: Message? = nil
    @ObservationIgnored private var minuteur: Task<Void, Never>? = nil

    func dire(_ texte: String, action: String? = nil, long: Bool = false, faire: (() -> Void)? = nil) {
        let m = Message(texte: texte, action: action, faire: faire)
        courant = m
        minuteur?.cancel()
        let duree: Double = (action != nil || long) ? 7 : 3.5
        minuteur = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(duree * 1_000_000_000))
            if Task.isCancelled { return }
            if self?.courant?.id == m.id { self?.courant = nil }
        }
    }

    func fermer() {
        minuteur?.cancel()
        courant = nil
    }

    func agir() {
        let f = courant?.faire
        fermer()
        f?()
    }
}

/// Bandeau de l'avis courant, posé en bas de l'écran.
@MainActor
struct VueAvis: View {
    let avis: Avis

    var body: some View {
        VStack {
            Spacer()
            if let m = avis.courant {
                HStack(spacing: 12) {
                    Text(m.texte)
                        .font(.subheadline)
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if let a = m.action {
                        Button(a) { avis.agir() }
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Color.accentCcs)
                    } else {
                        Button {
                            avis.fermer()
                        } label: {
                            Image(systemName: "xmark").foregroundStyle(.white.opacity(0.8))
                        }
                        .accessibilityLabel("Fermer")
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(RoundedRectangle(cornerRadius: 12).fill(Color(white: 0.18)))
                .padding(.horizontal, 12)
                .padding(.bottom, 60)
                .transition(.move(edge: .bottom).combined(with: .opacity))
                .id(m.id)
            }
        }
        .animation(.easeOut(duration: 0.2), value: avis.courant?.id)
        .allowsHitTesting(avis.courant != nil)
    }
}

// MARK: petites vues communes

@MainActor
struct Chargement: View {
    var texte: String? = nil

    var body: some View {
        HStack(spacing: 12) {
            ProgressView()
            if let t = texte { Text(t).foregroundStyle(.secondary) }
        }
        .frame(maxWidth: .infinity)
        .padding()
    }
}

@MainActor
struct EtatErreur: View {
    let message: String
    var reessayer: (() -> Void)? = nil

    var body: some View {
        VStack(spacing: 8) {
            Text(message).foregroundStyle(.red).multilineTextAlignment(.center)
            if let r = reessayer {
                Button("Réessayer", action: r).buttonStyle(.bordered)
            }
        }
        .frame(maxWidth: .infinity)
        .padding()
    }
}

@MainActor
struct EtatVide<Action: View>: View {
    let message: String
    let action: Action

    init(_ message: String, @ViewBuilder action: () -> Action) {
        self.message = message
        self.action = action()
    }

    var body: some View {
        VStack(spacing: 12) {
            Text(message).foregroundStyle(.secondary).multilineTextAlignment(.center)
            action
        }
        .frame(maxWidth: .infinity)
        .padding(24)
    }
}

extension EtatVide where Action == EmptyView {
    init(_ message: String) {
        self.message = message
        self.action = EmptyView()
    }
}

@MainActor
struct Pastille: View {
    let couleur: Color
    var taille: CGFloat = 10

    var body: some View {
        Circle().fill(couleur).frame(width: taille, height: taille)
    }
}

/// Petite étiquette arrondie (« ouverte », compte, origine).
@MainActor
struct Etiquette: View {
    let texte: String
    var fond: Color = Color.accentCcs.opacity(0.15)
    var encre: Color = .primary

    var body: some View {
        Text(texte)
            .font(.caption2)
            .lineLimit(1)
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .background(Capsule().fill(fond))
            .foregroundStyle(encre)
    }
}

/// Carte arrondie sur fond groupé (les `Card` de l'appli Android).
@MainActor
struct CarteFond<Contenu: View>: View {
    let contenu: Contenu

    init(@ViewBuilder contenu: () -> Contenu) {
        self.contenu = contenu()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) { contenu }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 14).fill(Color.carte))
    }
}

/// Barre de progression d'une jauge (0…100).
@MainActor
struct BarreJauge: View {
    let pourcent: Double
    let couleur: Color

    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.secondary.opacity(0.2))
                Capsule().fill(couleur).frame(width: max(0, min(1, pourcent / 100)) * g.size.width)
            }
        }
        .frame(height: 8)
    }
}
