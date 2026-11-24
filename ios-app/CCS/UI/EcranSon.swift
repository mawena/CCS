import ReplayKit
import SwiftUI

/**
 * Écran « Son » (Plus → Son) : le son partagé sur le réseau maillé (phase 42, `docs/audio.md`).
 * Ce que fait l'iPhone (annonce, son joué, diffusion), les flux en cours avec « Arrêter »,
 * « Envoyer le son de cet iPhone vers… » (diffusion ReplayKit lancée par l'utilisateur), envoi
 * de n'importe quelle source vers n'importe quelle sortie, et les appareils annoncés.
 * `audio.list` relu toutes les 5 s tant que l'écran est ouvert.
 */
@MainActor
struct EcranSon: View {
    @Environment(ModeleAppli.self) private var modele
    @State private var diffusionActive = false
    @State private var declencheur = 0
    @State private var source = ""
    @State private var sortie = ""

    private var son: SonPartage { return modele.son }

    var body: some View {
        let l = son.liste
        let sorties = Son.sortiesPour(son.moi, l)
        List {
            Section {
                EnteteSon(son: son, diffusionActive: diffusionActive)
                    .listRowInsets(EdgeInsets()).listRowBackground(Color.clear)
            }
            if son.ecoute != nil || diffusionActive || !l.streams.isEmpty {
                Section("En ce moment") {
                    if let e = son.ecoute {
                        HStack {
                            Label("Joue le son de \(e.de)", systemImage: "hifispeaker.fill")
                            Spacer()
                            Button("Arrêter", role: .destructive) { Task { await son.arreter(flux: e.flux) } }
                                .buttonStyle(.borderless)
                        }
                    }
                    ForEach(l.streams.filter { $0.stream != son.ecoute?.flux }) { f in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("\(l.nom(f.source)) → \(l.nom(f.target))")
                                if f.source == son.moi {
                                    Text(diffusionActive ? "Diffusion en cours" : "Diffusion pas lancée")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            Spacer()
                            Button("Arrêter", role: .destructive) {
                                Task {
                                    if f.source == son.moi { await son.arreterIci() } else { await son.arreter(flux: f.stream) }
                                }
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
            }
            Section {
                if sorties.isEmpty {
                    Text("Aucune autre sortie annoncée. Ouvre CCS sur le PC (son partagé actif) ou sur le Pixel.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                ForEach(sorties) { s in
                    Button {
                        Task { await son.envoyerDepuisIci(vers: s) }
                    } label: {
                        HStack {
                            Label(s.nom, systemImage: Son.icone(s))
                            Spacer()
                            if son.cibleDiffusion == s.nom { Image(systemName: "checkmark").foregroundStyle(.secondary) }
                        }
                    }
                    .disabled(son.moi.isEmpty)
                }
                HStack {
                    Text(diffusionActive ? "Arrêter la diffusion" : "Lancer la diffusion")
                    Spacer()
                    SelecteurDiffusion(declencheur: declencheur).frame(width: 44, height: 44)
                }
            } header: {
                Text("Envoyer le son de cet iPhone vers…")
            } footer: {
                Text("iOS demande de lancer la diffusion soi-même (aussi depuis le centre de contrôle : enregistrement de l'écran, appui long, « CCS »). Les contenus protégés (Apple Music, Netflix…) restent muets.")
            }
            Section {
                Picker("Source", selection: $source) {
                    Text("Choisir").tag("")
                    ForEach(l.sources) { a in Text(a.nom).tag(a.device) }
                }
                Picker("Sortie", selection: $sortie) {
                    Text("Choisir").tag("")
                    ForEach(l.sorties.filter { $0.device != source }) { a in Text(a.nom).tag(a.device) }
                }
                Button("Envoyer") {
                    guard let cible = l.devices.first(where: { $0.device == sortie }) else { return }
                    Task { await son.envoyer(source: source, vers: cible) }
                }
                .disabled(source.isEmpty || sortie.isEmpty || source == sortie)
            } header: {
                Text("D'un appareil vers un autre")
            } footer: {
                Text("Un Pixel ou un iPhone source demande son accord sur l'appareil même (notification).")
            }
            Section("Appareils") {
                if l.devices.isEmpty {
                    Text("Aucun appareil annoncé.").font(.footnote).foregroundStyle(.secondary)
                }
                ForEach(l.devices) { a in
                    HStack {
                        Image(systemName: Son.icone(a)).frame(width: 26)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(a.nom + (a.device == son.moi ? " (cet iPhone)" : ""))
                            Text([a.ip, a.play ? "sortie" : nil, a.capture ? "source" : nil].compactMap { $0 }.joined(separator: " · "))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .navigationTitle("Son")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable {
            await son.annoncer()
            await son.rafraichir()
        }
        .task(id: modele.client.etat.estConnecte) {
            guard modele.client.etat.estConnecte else { return }
            var tour = 0
            while !Task.isCancelled {
                diffusionActive = GroupeSon.diffusionActive
                if tour % 5 == 0 {
                    if son.moi.isEmpty { await son.annoncer() }
                    await son.rafraichir()
                }
                tour += 1
                try? await Task.sleep(nanoseconds: 1_000_000_000)
            }
        }
        // envoi fait ici ou notification touchée : sélecteur de diffusion de ReplayKit
        .onChange(of: son.demandeDiffusion, initial: true) { _, _ in
            if son.prendreDemande() { declencheur += 1 }
        }
    }
}

// MARK: en-tête

@MainActor
private struct EnteteSon: View {
    let son: SonPartage
    let diffusionActive: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                Image(systemName: "hifispeaker.2")
                    .font(.system(size: 26, weight: .medium))
                    .frame(width: 52, height: 52)
                    .background(.white.opacity(0.16), in: RoundedRectangle(cornerRadius: 15))
                VStack(alignment: .leading, spacing: 2) {
                    Text("Son partagé").font(.title2.bold())
                    Text(son.moi.isEmpty ? "iPhone pas encore annoncé" : "\(son.moi) · \(son.ip ?? "")")
                        .font(.footnote).opacity(0.85)
                }
                Spacer()
                HStack(spacing: 6) {
                    Circle().fill(son.annonceLe != nil ? Color(red: 0.34, green: 0.89, blue: 0.54) : Color(red: 1, green: 0.48, blue: 0.48))
                        .frame(width: 8, height: 8)
                    Text(son.annonceLe != nil ? "Annoncé" : "Hors ligne").font(.footnote.weight(.semibold))
                }
                .padding(.horizontal, 10).padding(.vertical, 5)
                .background(.black.opacity(0.22), in: Capsule())
            }
            HStack(spacing: 8) {
                pastille("hifispeaker.fill", son.ecoute.map { "Joue \($0.de)" } ?? "Prêt à jouer")
                pastille("dot.radiowaves.left.and.right",
                         diffusionActive ? "Vers \(son.cibleDiffusion ?? "…")" : "Pas de diffusion")
            }
            if let m = son.probleme ?? GroupeSon.derniereErreur {
                Text(m).font(.footnote).padding(10).frame(maxWidth: .infinity, alignment: .leading)
                    .background(.black.opacity(0.25), in: RoundedRectangle(cornerRadius: 10))
            }
        }
        .foregroundStyle(.white)
        .padding(16)
        .background(
            LinearGradient(colors: [Color(red: 0.55, green: 0.20, blue: 0.62), Color(red: 0.11, green: 0.44, blue: 0.85)],
                           startPoint: .topLeading, endPoint: .bottomTrailing),
            in: RoundedRectangle(cornerRadius: 20))
    }

    private func pastille(_ icone: String, _ texte: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: icone).font(.footnote)
            Text(texte).font(.footnote.weight(.semibold)).lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(.white.opacity(0.13), in: RoundedRectangle(cornerRadius: 12))
    }
}

// MARK: sélecteur de diffusion

/// Bouton de diffusion de ReplayKit réglé sur l'extension de CCS ; `declencheur` qui change le
/// touche lui-même (le sélecteur de diffusion s'ouvre sans que l'utilisateur cherche le bouton).
struct SelecteurDiffusion: UIViewRepresentable {
    let declencheur: Int

    final class Coordinateur { var vu = 0 }

    func makeCoordinator() -> Coordinateur { return Coordinateur() }

    func makeUIView(context: Context) -> RPSystemBroadcastPickerView {
        let v = RPSystemBroadcastPickerView(frame: CGRect(x: 0, y: 0, width: 44, height: 44))
        v.preferredExtension = GroupeSon.bundleExtension
        v.showsMicrophoneButton = false
        return v
    }

    func updateUIView(_ v: RPSystemBroadcastPickerView, context: Context) {
        guard declencheur != context.coordinator.vu else { return }
        context.coordinator.vu = declencheur
        // laisse la vue entrer dans la fenêtre avant de toucher son bouton
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            for s in v.subviews {
                if let b = s as? UIButton { b.sendActions(for: .allTouchEvents) }
            }
        }
    }
}
