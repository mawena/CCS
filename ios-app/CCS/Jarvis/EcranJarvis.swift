import SwiftUI
import UIKit

/**
 * Plus → Jarvis : parler à Jarvis, l'assistant vocal de la maison, depuis n'importe où (relais de
 * CCS, comme la page Jarvis de la version web). Appairage une fois (adresse `jarvis://pair?…` de
 * « jarvis pair », collée ou scannée par l'appareil photo, ou code + empreinte), puis un bouton :
 * maintenir pour parler (fin au relâché), ou toucher une fois (fin au silence).
 */
@MainActor
struct EcranJarvis: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.scenePhase) private var phase

    var body: some View {
        let oreille = modele.jarvis
        Group {
            if oreille.appairage == nil {
                FormulaireAppairageJarvis(oreille: oreille)
            } else {
                BoutonJarvis(oreille: oreille)
            }
        }
        .navigationTitle("Jarvis")
        .navigationBarTitleDisplayMode(.inline)
        .onDisappear { oreille.fermer() }
        .onChange(of: phase) { _, p in if p == .background { oreille.fermer() } }
    }
}

@MainActor
private struct BoutonJarvis: View {
    let oreille: OreilleJarvis
    @State private var appuye = false
    @State private var debut: Date? = nil
    @State private var confirmer = false

    private static let appuiLong: TimeInterval = 0.4

    var body: some View {
        List {
            Section {
                VStack(spacing: 14) {
                    bouton
                    Text(oreille.etat.isEmpty ? (oreille.ecoute ? "Écoute…" : "Prêt.") : oreille.etat)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .accessibilityAddTraits(.updatesFrequently)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 18)
            } footer: {
                Text("Maintiens le bouton pendant que tu parles, ou touche-le une fois : l'écoute s'arrête quand tu te tais.")
            }
            if !oreille.journal.isEmpty {
                Section("Conversation") {
                    ForEach(oreille.journal) { l in ligne(l) }
                }
            }
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button("Oublier l'appairage", systemImage: "trash", role: .destructive) { confirmer = true }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
            }
        }
        .confirmationDialog("Oublier l'appairage ?", isPresented: $confirmer, titleVisibility: .visible) {
            Button("Oublier", role: .destructive) { oreille.oublier() }
        } message: {
            Text("Ce téléphone ne pourra plus parler à Jarvis sans un nouvel appairage. Pour le retirer aussi côté Jarvis : « jarvis unpair <nom> ».")
        }
        .onChange(of: DemandeJarvis.partage.compteur, initial: true) { _, _ in
            if DemandeJarvis.partage.prendreEcoute() && !oreille.ecoute { oreille.commencer(auto: true) }
        }
    }

    private var bouton: some View {
        let actif = oreille.ecoute
        return ZStack {
            Circle()
                .fill(actif ? Color.red : Color.accentCcs)
                .frame(width: 132, height: 132)
                .shadow(color: (actif ? Color.red : Color.accentCcs).opacity(0.35), radius: actif ? 18 : 8)
                .scaleEffect(actif ? 1.06 : 1)
                .animation(.easeInOut(duration: 0.2), value: actif)
            VStack(spacing: 6) {
                Image(systemName: actif ? "waveform" : "mic.fill").font(.system(size: 40, weight: .semibold))
                Text("Parler à Jarvis").font(.caption.weight(.semibold))
            }
            .foregroundStyle(.white)
        }
        .contentShape(Circle())
        // appui long : on parle tant que le doigt est posé ; appui court : fin au silence ; second appui : fin
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    guard !appuye else { return }
                    appuye = true
                    if oreille.ecoute {
                        debut = nil
                        oreille.finir()
                    } else {
                        debut = Date()
                        oreille.commencer(auto: false)
                    }
                }
                .onEnded { _ in
                    appuye = false
                    guard let d = debut else { return }
                    debut = nil
                    guard oreille.ecoute else { return }
                    if Date().timeIntervalSince(d) >= BoutonJarvis.appuiLong { oreille.finir() } else { oreille.passerEnAuto() }
                }
        )
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Parler à Jarvis")
        .accessibilityValue(actif ? "Écoute" : "")
        .accessibilityAddTraits(.isButton)
        .accessibilityAction { if oreille.ecoute { oreille.finir() } else { oreille.commencer(auto: true) } }
    }

    @ViewBuilder
    private func ligne(_ l: OreilleJarvis.Ligne) -> some View {
        switch l.genre {
        case .erreur:
            Label(l.texte, systemImage: "exclamationmark.triangle").foregroundStyle(.red).font(.subheadline)
        case .moi, .jarvis:
            VStack(alignment: .leading, spacing: 2) {
                Text(l.qui).font(.caption.weight(.semibold)).foregroundStyle(l.genre == .moi ? Color.secondary : Color.accentCcs)
                Text(l.texte).textSelection(.enabled)
            }
        }
    }
}

@MainActor
private struct FormulaireAppairageJarvis: View {
    let oreille: OreilleJarvis
    @State private var adresse = ""
    @State private var code = ""
    @State private var empreinte = ""
    @State private var nom = OreilleJarvis.nomParDefaut()
    @State private var aLaMain = false
    @State private var erreur: String? = nil
    @State private var enCours = false

    var body: some View {
        Form {
            Section {
                HStack {
                    TextField("jarvis://pair?v=1&…", text: $adresse)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .font(.system(.body, design: .monospaced))
                    Button("Coller") {
                        if let t = UIPasteboard.general.string { adresse = Jarvis.nettoyer(t) }
                    }
                    .buttonStyle(.borderless)
                }
            } header: {
                Text("Adresse d'appairage")
            } footer: {
                Text("Sur la machine de Jarvis, lance « jarvis pair » : scanne le QR code avec l'appareil photo (il ouvre CCS), ou colle ici l'adresse affichée dessous (valable quelques minutes).")
            }
            Section {
                DisclosureGroup("Saisir le code et l'empreinte à la main", isExpanded: $aLaMain) {
                    TextField("Code à 6 chiffres", text: $code)
                        .keyboardType(.numberPad)
                    TextField("Empreinte du cerveau (43 caractères)", text: $empreinte)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .font(.system(.footnote, design: .monospaced))
                }
            }
            Section {
                TextField("Nom de ce téléphone", text: $nom)
            } header: {
                Text("Nom de cet appareil")
            } footer: {
                Text("Affiché par « jarvis ears ».")
            }
            if let e = erreur {
                Section { Text(e).foregroundStyle(.red) }
            }
            Section {
                Button {
                    appairer()
                } label: {
                    HStack {
                        Text(enCours ? "Appairage…" : "Appairer")
                        if enCours { Spacer(); ProgressView() }
                    }
                }
                .disabled(enCours)
            }
        }
        .onChange(of: DemandeJarvis.partage.compteur, initial: true) { _, _ in
            if let a = DemandeJarvis.partage.prendreAdresse() { adresse = Jarvis.nettoyer(a) }
            _ = DemandeJarvis.partage.prendreEcoute()      // rien à écouter avant l'appairage
        }
    }

    private func appairer() {
        erreur = nil
        let cible: CibleAppairage
        do {
            if !adresse.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                cible = try Jarvis.lireAdresse(adresse)
            } else {
                let c = code.trimmingCharacters(in: .whitespaces)
                let f = empreinte.trimmingCharacters(in: .whitespaces)
                guard Jarvis.codeValide(c) else { throw ErreurJarvis("Code d'appairage : 6 chiffres.") }
                guard Jarvis.empreinteValide(f) else { throw ErreurJarvis("Empreinte invalide : 43 caractères (lettres, chiffres, - et _).") }
                cible = CibleAppairage(code: c, empreinte: f)
            }
        } catch {
            erreur = error.localizedDescription
            return
        }
        let n = nom.trimmingCharacters(in: .whitespaces)
        enCours = true
        Task { @MainActor in
            defer { enCours = false }
            do {
                try await oreille.appairer(cible, nom: n.isEmpty ? OreilleJarvis.nomParDefaut() : n)
            } catch {
                erreur = error.localizedDescription
            }
        }
    }
}
