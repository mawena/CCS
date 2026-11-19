import SwiftUI

/// « Bilan de santé » (`pages-health.js`) : erreurs et avertissements d'abord, commande à copier.
@MainActor
struct CarteBilan: View {
    @Environment(ModeleAppli.self) private var modele
    @State private var bilan: Bilan?
    @State private var erreur: String?
    @State private var enCours = false
    @State private var reussiesOuvertes = false

    var body: some View {
        CarteFond {
            HStack {
                Text("Bilan de santé").font(.headline)
                Spacer()
                Button("Lancer le bilan") { lancer() }
                    .buttonStyle(.bordered)
                    .disabled(enCours)
            }
            Text("Vérifie le service, les comptes, Claude Code, le téléphone et le serveur.")
                .font(.footnote)
                .foregroundStyle(.secondary)
            if enCours {
                Chargement(texte: "Vérification en cours…")
            } else if let e = erreur {
                EtatErreur(message: e) { lancer() }
            } else if let b = bilan {
                Text(b.summary)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(b.errors > 0 ? Color.red : (b.warnings > 0 ? Color.avertissement : Color.reussite))
                ForEach(b.checks.filter { $0.statut != "ok" }) { v in LigneVerification(v: v) }
                let bonnes = b.checks.filter { $0.statut == "ok" }
                if !bonnes.isEmpty {
                    Button {
                        reussiesOuvertes.toggle()
                    } label: {
                        Label("\(bonnes.count) vérification(s) réussie(s)", systemImage: reussiesOuvertes ? "chevron.up" : "chevron.down")
                            .font(.subheadline.weight(.medium))
                    }
                    .buttonStyle(.borderless)
                    if reussiesOuvertes {
                        ForEach(bonnes) { v in LigneVerification(v: v) }
                    }
                }
            }
        }
    }

    private func lancer() {
        Task { @MainActor in
            enCours = true
            erreur = nil
            do {
                let r = try await modele.client.appeler("doctor.run", delai: 90, en: Bilan.self)
                bilan = r
                if r.errors == 0 && r.warnings == 0 { modele.avis.dire("Tout va bien.") }
            } catch {
                erreur = texteErreur(error)
            }
            enCours = false
        }
    }
}

@MainActor
private struct LigneVerification: View {
    @Environment(ModeleAppli.self) private var modele
    let v: Verification

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icone).foregroundStyle(teinte).accessibilityLabel(v.statut)
            VStack(alignment: .leading, spacing: 2) {
                Text(v.nom).font(.subheadline.weight(.semibold))
                if !v.detail.isEmpty {
                    Text(v.detail).font(.footnote).foregroundStyle(.secondary)
                }
                if let cmd = v.commande, !cmd.isEmpty {
                    HStack {
                        Text(cmd).font(.system(.footnote, design: .monospaced)).textSelection(.enabled)
                        Spacer()
                        Button {
                            copier(cmd)
                            modele.avis.dire("Commande copiée.")
                        } label: {
                            Image(systemName: "doc.on.doc")
                        }
                        .accessibilityLabel("Copier la commande : \(cmd)")
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.fondCode))
                }
            }
        }
    }

    private var icone: String {
        switch v.statut {
        case "erreur": return "xmark.octagon.fill"
        case "avertissement": return "exclamationmark.triangle.fill"
        default: return "checkmark.circle.fill"
        }
    }

    private var teinte: Color {
        switch v.statut {
        case "erreur": return .red
        case "avertissement": return .avertissement
        default: return .reussite
        }
    }
}
