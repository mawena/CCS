import SwiftUI
import PhotosUI
import UIKit
import UniformTypeIdentifiers

/// Résumé des options du chat : « Opus · Élevé · Demander ».
func resumeOptions(_ r: ReglagesChat) -> String {
    let o = r.options
    var parts: [String] = []
    if let m = o.model, !m.isEmpty {
        parts.append(r.modeles.first(where: { $0.valeur == m })?.libelle ?? m)
    }
    if let e = o.effort, !e.isEmpty {
        parts.append(ChoixSession.efforts.first(where: { $0.valeur == e })?.libelle ?? e)
    }
    parts.append(ChoixSession.droits.first(where: { $0.valeur == o.rights })?.libelle ?? o.rights)
    return parts.joined(separator: " · ")
}

/// État de Claude au-dessus de la saisie (au travail, démarrage, réflexion, attente).
@MainActor
struct BandeauEtat: View {
    let vue: VueChat

    var body: some View {
        if let t = texte {
            HStack(spacing: 8) {
                if vue.etat != "suspended" && vue.etat != "permission" {
                    ProgressView().controlSize(.mini)
                }
                Text(t).font(.caption.weight(.medium)).foregroundStyle(Color.accentCcs)
                Spacer()
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 4)
        }
    }

    private var texte: String? {
        switch vue.etat {
        case "permission": return "Attend ta réponse"
        case "starting": return vue.pret ? "Démarrage…" : nil
        case "busy": return vue.reflechit ? "Claude réfléchit…" : "Claude travaille…"
        case "suspended": return "En veille"
        default: return nil
        }
    }
}

/// Zone de saisie : citation, images, commandes `/`, texte multi-ligne, dictée, envoi ; pied : options, contexte, coût, Arrêter.
@MainActor
struct Saisie: View {
    let mc: ModeleChat
    @State private var choix: [PhotosPickerItem] = []
    @State private var options = false
    @State private var dictee = Dictee()
    @FocusState private var focus: Bool

    var body: some View {
        let saisie = mc.saisie
        let propositions = Envoi.completer(saisie, mc.commandes)
        let occupe = mc.vue.etat == "busy" || mc.vue.etat == "permission"
        let peutEnvoyer = !mc.envoiEnCours && (!saisie.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !mc.images.isEmpty)
        VStack(spacing: 4) {
            if !propositions.isEmpty {
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(propositions, id: \.nom) { c in
                            Button {
                                mc.saisir("/" + c.nom + " ")
                            } label: {
                                VStack(alignment: .leading, spacing: 1) {
                                    Text("/" + c.nom + (c.indice.isEmpty ? "" : " " + c.indice))
                                        .font(.system(.subheadline, design: .monospaced))
                                        .foregroundStyle(.primary)
                                    if !c.description.isEmpty {
                                        Text(c.description).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                                    }
                                }
                                .padding(.horizontal, 12)
                                .padding(.vertical, 5)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .frame(maxHeight: 200)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color.carte))
                .padding(.horizontal, 8)
            }
            if let c = mc.citation {
                HStack(alignment: .top, spacing: 6) {
                    BlocCite(auteur: c.auteur, texte: c.texte)
                    Button {
                        mc.citer(nil)
                    } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                    }
                    .buttonStyle(.borderless)
                    .accessibilityLabel("Retirer la citation")
                }
                .padding(.horizontal, 10)
            }
            if !mc.images.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(mc.images) { p in
                            ZStack(alignment: .topTrailing) {
                                Group {
                                    if let a = p.apercu {
                                        Image(uiImage: a).resizable().scaledToFill()
                                    } else {
                                        Image(systemName: "photo").foregroundStyle(.secondary)
                                    }
                                }
                                .frame(width: 56, height: 56)
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                                Button {
                                    mc.retirerImage(p)
                                } label: {
                                    Image(systemName: "xmark.circle.fill")
                                        .foregroundStyle(Color.white, Color.black.opacity(0.6))
                                }
                                .buttonStyle(.borderless)
                                .accessibilityLabel("Retirer l'image")
                            }
                        }
                    }
                    .padding(.horizontal, 10)
                }
            }
            HStack(alignment: .bottom, spacing: 6) {
                PhotosPicker(selection: $choix, maxSelectionCount: max(1, ModeleChat.maxImages - mc.images.count), matching: .images) {
                    Image(systemName: "photo.badge.plus").font(.title3)
                }
                .disabled(mc.images.count >= ModeleChat.maxImages)
                .accessibilityLabel("Joindre une image")
                .padding(.bottom, 6)
                TextField("Message à Claude…", text: Binding<String>(get: { mc.saisie }, set: { mc.saisir($0) }), axis: .vertical)
                    .lineLimit(1...8)
                    .focused($focus)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(RoundedRectangle(cornerRadius: 18).fill(Color.carte))
                Button {
                    let m = mc
                    dictee.basculer(depuis: m.saisie, ecrire: { t in m.saisir(t) }, dire: { t in m.dire(t) })
                } label: {
                    Image(systemName: dictee.etat == .arretee ? "mic" : "mic.fill")
                        .font(.title3)
                        .foregroundStyle(dictee.etat == .ecoute ? Color.red : Color.accentCcs)
                        .symbolEffect(.pulse, isActive: dictee.etat == .ecoute)
                }
                .accessibilityLabel(dictee.etat == .arretee ? "Dicter" : "Arrêter la dictée")
                .padding(.bottom, 6)
                Button {
                    dictee.abandonner()
                    mc.envoyer()
                } label: {
                    Image(systemName: "arrow.up.circle.fill").font(.system(size: 32))
                }
                .disabled(!peutEnvoyer)
                .accessibilityLabel("Envoyer")
            }
            .padding(.horizontal, 8)
            HStack(spacing: 8) {
                Button {
                    options = true
                } label: {
                    Label(resumeOptions(mc.reglages), systemImage: "slider.horizontal.3")
                        .font(.caption)
                        .lineLimit(1)
                }
                .buttonStyle(.borderless)
                .disabled(!mc.reglages.pretes)
                Spacer(minLength: 4)
                HStack(spacing: 0) {
                    if !mc.vue.contexte.isEmpty {
                        Text(mc.vue.contexte).foregroundStyle(couleurContexte)
                    }
                    if !mc.vue.contexte.isEmpty && !mc.vue.cout.isEmpty {
                        Text(" · ").foregroundStyle(.secondary)
                    }
                    if !mc.vue.cout.isEmpty {
                        Text(mc.vue.cout).foregroundStyle(.secondary)
                    }
                }
                .font(.caption2)
                .lineLimit(1)
                if occupe {
                    Button {
                        mc.interrompre()
                    } label: {
                        Label("Arrêter", systemImage: "stop.fill").font(.caption)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.mini)
                    .tint(.red)
                }
            }
            .padding(.horizontal, 12)
            .padding(.bottom, 4)
        }
        .padding(.top, 4)
        .background(.bar)
        .onDisappear { dictee.abandonner() }
        .onChange(of: choix) { _, nouveaux in
            guard !nouveaux.isEmpty else { return }
            choix = []
            charger(nouveaux)
        }
        .confirmationDialog(
            mc.confirmationCache.map { Jetons.avertissementCache($0) } ?? "",
            isPresented: Binding<Bool>(get: { mc.confirmationCache != nil }, set: { if !$0 { mc.annulerEnvoi() } }),
            titleVisibility: .visible
        ) {
            Button("Envoyer quand même") { mc.envoyerQuandMeme() }
            Button("Compacter d'abord") { mc.compacterDabord() }
            Button("Annuler", role: .cancel) { mc.annulerEnvoi() }
        }
        .sheet(isPresented: $options) {
            FeuilleOptions(r: mc.reglages) { o in mc.changerOptions(o) }
                .presentationDetents([.medium, .large])
        }
    }

    /// Vert sous la moitié du seuil du contexte lourd, orange jusqu'au seuil, rouge au-delà.
    private var couleurContexte: Color {
        switch mc.vue.niveauContexte {
        case .vert?: return vertDiff
        case .orange?: return Color.avertissement
        case .rouge?: return rougeDiff
        case nil: return Color.secondary
        }
    }

    private func charger(_ items: [PhotosPickerItem]) {
        let m = mc
        Task { @MainActor in
            for item in items {
                if m.images.count >= ModeleChat.maxImages {
                    m.dire("\(ModeleChat.maxImages) images au plus.")
                    break
                }
                var donnees: Data? = nil
                do {
                    donnees = try await item.loadTransferable(type: Data.self)
                } catch {
                    donnees = nil
                }
                let type = item.supportedContentTypes.first?.preferredMIMEType ?? "image/jpeg"
                if let d = donnees, let p = lireImage(d, type: type, nom: "image") {
                    m.joindre(p)
                } else {
                    m.dire("Image illisible ou trop lourde (5 Mo au plus).")
                }
            }
        }
    }
}

private let maxOctets = 5 * 1024 * 1024
private let garderTelQuel = 3_500_000
private let coteMax: CGFloat = 2000

/// Type d'une image d'après ses premiers octets (le type annoncé peut mentir).
func typeImage(_ d: Data) -> String? {
    let o = [UInt8](d.prefix(12))
    if o.count >= 3 && o[0] == 0xFF && o[1] == 0xD8 && o[2] == 0xFF { return "image/jpeg" }
    if o.count >= 8 && o[0] == 0x89 && o[1] == 0x50 && o[2] == 0x4E && o[3] == 0x47 { return "image/png" }
    if o.count >= 4 && o[0] == 0x47 && o[1] == 0x49 && o[2] == 0x46 && o[3] == 0x38 { return "image/gif" }
    if o.count >= 12 && o[0] == 0x52 && o[1] == 0x49 && o[2] == 0x46 && o[3] == 0x46
        && o[8] == 0x57 && o[9] == 0x45 && o[10] == 0x42 && o[11] == 0x50 { return "image/webp" }
    return nil
}

/// Image choisie : gardée telle quelle si elle est légère et d'un type accepté, sinon réduite (JPEG, 2000 px de côté).
@MainActor
func lireImage(_ d: Data, type annonce: String, nom: String) -> PieceJointe? {
    guard let image = UIImage(data: d) else { return nil }
    let cote = max(image.size.width * image.scale, image.size.height * image.scale)
    guard cote > 0 else { return nil }
    var octets = d
    var type = typeImage(d) ?? annonce
    if d.count > garderTelQuel || cote > coteMax * 2 || typeImage(d) == nil {
        let k = min(1, coteMax / cote)
        let taille = CGSize(width: floor(image.size.width * image.scale * k), height: floor(image.size.height * image.scale * k))
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let reduite = UIGraphicsImageRenderer(size: taille, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: taille))
        }
        guard let j = reduite.jpegData(compressionQuality: 0.85) else { return nil }
        octets = j
        type = "image/jpeg"
    }
    if octets.count > maxOctets { return nil }
    let apercu = image.preparingThumbnail(of: CGSize(width: 160, height: 160 * image.size.height / max(1, image.size.width)))
    return PieceJointe(typeMedia: type, base64: octets.base64EncodedString(), apercu: apercu, nom: nom)
}

/// Options du chat : modèle, effort, droits (« Tout autoriser » demande confirmation).
@MainActor
struct FeuilleOptions: View {
    let r: ReglagesChat
    let changer: (OptionsChat) -> Void
    @Environment(\.dismiss) private var fermer
    @State private var confirmer = false
    @State private var o = OptionsChat()
    @State private var lu = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Modèle") {
                    ForEach(modeles, id: \.valeur) { m in
                        Rangee(texte: m.libelle, pris: (o.model ?? "") == m.valeur) {
                            o.model = m.valeur.isEmpty ? nil : m.valeur
                            changer(o)
                        }
                    }
                    if r.modeles.isEmpty {
                        Text("La liste des modèles arrive quand Claude a démarré.").font(.footnote).foregroundStyle(.secondary)
                    }
                }
                Section("Effort") {
                    ForEach(ChoixSession.efforts.indices, id: \.self) { i in
                        let e = ChoixSession.efforts[i]
                        Rangee(texte: e.libelle, pris: (o.effort ?? "") == e.valeur) {
                            o.effort = e.valeur.isEmpty ? nil : e.valeur
                            changer(o)
                        }
                    }
                }
                Section("Droits") {
                    ForEach(ChoixSession.droits.indices, id: \.self) { i in
                        let d = ChoixSession.droits[i]
                        Rangee(texte: d.libelle, pris: o.rights == d.valeur) {
                            if d.valeur == "bypassPermissions" && o.rights != d.valeur {
                                confirmer = true
                            } else {
                                o.rights = d.valeur
                                changer(o)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Options du chat")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("OK") { fermer() }
                }
            }
            .alert("Tout autoriser ?", isPresented: $confirmer) {
                Button("Annuler", role: .cancel) {}
                Button("Tout autoriser") {
                    o.rights = "bypassPermissions"
                    changer(o)
                }
            } message: {
                Text("Claude pourra lancer des commandes et modifier des fichiers sans te demander.")
            }
        }
        .onAppear {
            if !lu {
                o = r.options
                lu = true
            }
        }
    }

    /// Modèles proposés : par défaut, ceux du pont, et le modèle actuel s'il n'en fait pas partie.
    private var modeles: [ModeleIa] {
        var l: [ModeleIa] = [ModeleIa(valeur: "", libelle: "Modèle par défaut")]
        l.append(contentsOf: r.modeles)
        if let m = o.model, !m.isEmpty, !r.modeles.contains(where: { $0.valeur == m }) {
            l.append(ModeleIa(valeur: m, libelle: m))
        }
        return l
    }
}

@MainActor
private struct Rangee: View {
    let texte: String
    let pris: Bool
    let faire: () -> Void

    var body: some View {
        Button(action: faire) {
            HStack {
                Text(texte).foregroundStyle(.primary)
                Spacer()
                if pris { Image(systemName: "checkmark").foregroundStyle(Color.accentCcs) }
            }
            .contentShape(Rectangle())
        }
    }
}
