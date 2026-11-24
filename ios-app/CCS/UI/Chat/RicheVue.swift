import SwiftUI
import UIKit
import AVKit
import AVFoundation
import Combine

/**
 * Chat riche (phase 49), partie écran : images (taille limitée, agrandies au toucher), lecteurs
 * de sons et de vidéos, composants des blocs ```ccs (choix, carte, cartes, formulaire). Les
 * fichiers locaux sont lus par `files.download` du pont. Port de `web/chat-rich.js`.
 */
struct ChatRiche {
    /// Dossier de la session : les chemins relatifs y sont joints.
    var cwd: String
    /// Envoie un message comme si l'utilisateur l'avait tapé ; nil : boutons inactifs (sous-agent).
    var envoyer: ((String) -> Void)?
}

private struct CleChatRiche: EnvironmentKey {
    static let defaultValue: ChatRiche? = nil
}

extension EnvironmentValues {
    var chatRiche: ChatRiche? {
        get { return self[CleChatRiche.self] }
        set { self[CleChatRiche.self] = newValue }
    }
}

// MARK: fichiers locaux

/// Fichiers du PC téléchargés une fois par chemin, gardés le temps de l'appli ; un échec n'est pas gardé.
@MainActor
final class CacheMedias {
    static let partage = CacheMedias()
    private var taches: [String: Task<URL, Error>] = [:]

    func fichier(_ chemin: String, client: CcsClient) async throws -> URL {
        if let t = taches[chemin] { return try await t.value }
        let t = Task<URL, Error> { try await CacheMedias.telecharger(chemin, client: client) }
        taches[chemin] = t
        do {
            return try await t.value
        } catch {
            taches[chemin] = nil
            throw error
        }
    }

    private static func telecharger(_ chemin: String, client: CcsClient) async throws -> URL {
        var donnees = Data()
        var recu: Int64 = 0
        while true {
            let r = try await client.appeler("files.download", ["path": .chaine(chemin), "offset": .nombre(Double(recu))],
                                             delai: 120, en: MorceauFichier.self)
            if r.size > Riche.maxLocal { throw ErreurHttp(message: "Fichier trop gros pour être affiché ici.") }
            guard let d = Data(base64Encoded: r.data) else { throw ErreurHttp(message: "Fichier illisible.") }
            donnees.append(d)
            recu += Int64(d.count)
            if recu > Riche.maxLocal { throw ErreurHttp(message: "Fichier trop gros pour être affiché ici.") }
            if r.done || d.isEmpty { break }
        }
        // l'extension est gardée : AVPlayer en a besoin pour reconnaître le format
        let dossier = FileManager.default.temporaryDirectory
            .appendingPathComponent("medias", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: dossier, withIntermediateDirectories: true)
        let nom = (chemin as NSString).lastPathComponent
        let url = dossier.appendingPathComponent(nom.isEmpty ? "fichier" : nom)
        try donnees.write(to: url)
        return url
    }
}

/// Petit mot à la place d'un média refusé ou illisible.
private struct MediaManquant: View {
    let texte: String
    var body: some View {
        Label(texte, systemImage: "exclamationmark.triangle")
            .font(.footnote)
            .foregroundStyle(.secondary)
            .lineLimit(2)
    }
}

// MARK: images

/// Image d'une réponse : https chargée directement, chemin local lu par le pont ; touchée, elle s'ouvre en grand.
@MainActor
struct ImageRiche: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.chatRiche) private var riche
    let src: String
    let alt: String
    var hauteurMax: CGFloat = 260

    @State private var locale: UIImage? = nil
    @State private var echec: String? = nil
    @State private var enGrand = false

    var body: some View {
        let source = Riche.resoudre(src, cwd: riche?.cwd ?? "")
        Group {
            switch source {
            case .none:
                MediaManquant(texte: alt.isEmpty ? src : alt)
            case .some(.url(let u)):
                AsyncImage(url: u) { phase in
                    switch phase {
                    case .success(let img):
                        img.resizable().scaledToFit()
                            .frame(maxHeight: hauteurMax, alignment: .leading)
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                            .onTapGesture { enGrand = true }
                    case .failure:
                        MediaManquant(texte: alt.isEmpty ? src : alt)
                    default:
                        ProgressView().frame(height: 60)
                    }
                }
            case .some(.chemin(let chemin)):
                if let img = locale {
                    Image(uiImage: img).resizable().scaledToFit()
                        .frame(maxHeight: hauteurMax, alignment: .leading)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .onTapGesture { enGrand = true }
                } else if let e = echec {
                    MediaManquant(texte: alt.isEmpty ? e : "\(alt) — \(e)")
                } else {
                    ProgressView().frame(height: 60)
                        .task(id: chemin) { await charger(chemin) }
                }
            }
        }
        .accessibilityLabel(alt.isEmpty ? "Image" : alt)
        .fullScreenCover(isPresented: $enGrand) {
            ImageEnGrand(source: source, locale: locale, alt: alt)
        }
    }

    private func charger(_ chemin: String) async {
        do {
            let url = try await CacheMedias.partage.fichier(chemin, client: modele.client)
            if let img = UIImage(contentsOfFile: url.path) {
                locale = img
            } else {
                echec = "Image illisible."
            }
        } catch {
            echec = error.localizedDescription
        }
    }
}

/// Image en plein écran (fond noir, pincer pour agrandir) ; un toucher ou « Fermer » la referme.
private struct ImageEnGrand: View {
    @Environment(\.dismiss) private var fermer
    let source: Riche.Source?
    let locale: UIImage?
    let alt: String
    @State private var echelle: CGFloat = 1

    private var adresse: URL? {
        if case .some(.url(let u)) = source { return u }
        return nil
    }

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Color.black.ignoresSafeArea()
            Group {
                if let img = locale {
                    Image(uiImage: img).resizable().scaledToFit()
                } else if let u = adresse {
                    AsyncImage(url: u) { img in img.resizable().scaledToFit() } placeholder: { ProgressView() }
                }
            }
            .scaleEffect(echelle)
            .gesture(MagnificationGesture().onChanged { echelle = max(1, min($0, 5)) })
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .onTapGesture { fermer() }
            .accessibilityLabel(alt.isEmpty ? "Image" : alt)
            Button { fermer() } label: {
                Image(systemName: "xmark.circle.fill").font(.title).foregroundStyle(.white.opacity(0.85))
            }
            .padding()
            .accessibilityLabel("Fermer")
        }
    }
}

// MARK: sons et vidéos

/// Lecteur d'un son (bouton lecture/pause) ou d'une vidéo (VideoPlayer), https ou fichier local.
@MainActor
struct LecteurRiche: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.chatRiche) private var riche
    let src: String
    let legende: String
    let video: Bool

    @State private var lecteur: AVPlayer? = nil
    @State private var echec: String? = nil
    @State private var enLecture = false

    var body: some View {
        Group {
            if let e = echec {
                MediaManquant(texte: legende.isEmpty || legende == src ? e : "\(legende) — \(e)")
            } else if let p = lecteur {
                if video {
                    VideoPlayer(player: p)
                        .frame(height: 200)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                } else {
                    HStack(spacing: 10) {
                        Button {
                            basculer(p)
                        } label: {
                            Image(systemName: enLecture ? "pause.circle.fill" : "play.circle.fill").font(.title)
                        }
                        .buttonStyle(.borderless)
                        .accessibilityLabel(enLecture ? "Pause" : "Lire")
                        Text(nomAffiche).font(.footnote).lineLimit(1).truncationMode(.middle)
                        Spacer(minLength: 0)
                    }
                    .padding(8)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.fondCode))
                    .onReceive(NotificationCenter.default.publisher(for: .AVPlayerItemDidPlayToEndTime)) { n in
                        guard let item = n.object as? AVPlayerItem, item === p.currentItem else { return }
                        enLecture = false
                        p.seek(to: .zero)
                    }
                }
            } else {
                ProgressView().frame(height: video ? 60 : 30)
            }
        }
        .task(id: src) { await preparer() }
        .onDisappear {
            lecteur?.pause()
            enLecture = false
        }
    }

    private var nomAffiche: String {
        let l = legende.trimmingCharacters(in: .whitespaces)
        if !l.isEmpty { return l }
        let base = src.split(whereSeparator: { $0 == "?" || $0 == "#" }).first.map(String.init) ?? src
        return (base as NSString).lastPathComponent
    }

    private func basculer(_ p: AVPlayer) {
        if enLecture {
            p.pause()
            enLecture = false
        } else {
            try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
            try? AVAudioSession.sharedInstance().setActive(true)
            p.play()
            enLecture = true
        }
    }

    private func preparer() async {
        guard lecteur == nil, echec == nil else { return }
        let url: URL
        switch Riche.resoudre(src, cwd: riche?.cwd ?? "") {
        case .none:
            echec = "Adresse refusée."
            return
        case .some(.url(let u)):
            url = u
        case .some(.chemin(let chemin)):
            do {
                url = try await CacheMedias.partage.fichier(chemin, client: modele.client)
            } catch {
                echec = error.localizedDescription
                return
            }
        }
        let asset = AVURLAsset(url: url)
        // WebM et Ogg ne sont pas lus par AVFoundation : on le dit plutôt qu'un lecteur muet
        if let lisible = try? await asset.load(.isPlayable), !lisible {
            echec = "Format non lu par iOS."
            return
        }
        if video {
            try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .moviePlayback)
        }
        lecteur = AVPlayer(playerItem: AVPlayerItem(asset: asset))
    }
}

/// Images et lecteurs trouvés dans un paragraphe, sous son texte.
@MainActor
struct MediasEnLigne: View {
    let medias: [Riche.MediaEnLigne]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(medias, id: \.self) { m in
                switch m.genre {
                case .image: ImageRiche(src: m.src, alt: m.legende)
                case .son: LecteurRiche(src: m.src, legende: m.legende, video: false)
                case .video: LecteurRiche(src: m.src, legende: m.legende, video: true)
                }
            }
        }
    }
}

// MARK: blocs ccs

/// Composant d'un bloc ```ccs ; un envoi désactive tous les boutons du bloc.
@MainActor
struct ComposantRiche: View {
    @Environment(\.chatRiche) private var riche
    let composant: Riche.Composant
    @State private var envoye = false

    var body: some View {
        switch composant {
        case .choix(let titre, let options):
            VStack(alignment: .leading, spacing: 8) {
                if !titre.isEmpty { Text(titre).font(.system(size: tailleTexteChat, weight: .semibold)) }
                FlowBoutons(options: options, actif: actif) { envoyer($0) }
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color.carte))
        case .carte(let c):
            CarteRiche(carte: c, actif: actif) { envoyer($0) }
        case .cartes(let cs):
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(alignment: .top, spacing: 10) {
                    ForEach(Array(cs.enumerated()), id: \.offset) { _, c in
                        CarteRiche(carte: c, actif: actif) { envoyer($0) }.frame(width: 240)
                    }
                }
            }
        case .formulaire(let titre, let bouton, let champs):
            FormulaireRiche(titre: titre, bouton: bouton, champs: champs, actif: actif) { envoyer($0) }
        }
    }

    private var actif: Bool { return !envoye && riche?.envoyer != nil }

    private func envoyer(_ texte: String) {
        guard !texte.isEmpty, !envoye, let f = riche?.envoyer else { return }
        envoye = true
        f(texte)
    }
}

/// Boutons d'options, un par ligne s'ils sont longs (ViewThatFits : en rangée si ça tient).
private struct FlowBoutons: View {
    let options: [Riche.Option]
    let actif: Bool
    let action: (String) -> Void

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) { boutons }
            VStack(alignment: .leading, spacing: 6) { boutons }
        }
    }

    @ViewBuilder
    private var boutons: some View {
        ForEach(Array(options.enumerated()), id: \.offset) { _, o in
            if let l = o.lien {
                Link(o.label, destination: l).buttonStyle(.bordered).controlSize(.small)
            } else {
                Button(o.label) { action(o.message) }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .disabled(!actif)
            }
        }
    }
}

private struct CarteRiche: View {
    let carte: Riche.Carte
    let actif: Bool
    let action: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !carte.image.isEmpty {
                ImageRiche(src: carte.image, alt: carte.titre, hauteurMax: 160)
            }
            Group {
                if let l = carte.lien {
                    Link(destination: l) { Text(carte.titre).bold().underline() }.tint(Color.accentCcs)
                } else {
                    Text(carte.titre).bold()
                }
            }
            .font(.system(size: tailleTexteChat))
            if !carte.prix.isEmpty {
                Text(carte.prix).font(.system(size: tailleTexteChat, weight: .semibold)).foregroundStyle(Color.accentCcs)
            }
            if !carte.sousTitre.isEmpty {
                Text(carte.sousTitre).font(.footnote).foregroundStyle(.secondary)
            }
            if !carte.description.isEmpty {
                Text(carte.description).font(.system(size: 15)).fixedSize(horizontal: false, vertical: true)
            }
            if !carte.actions.isEmpty {
                FlowBoutons(options: carte.actions, actif: actif, action: action)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.carte))
    }
}

private struct FormulaireRiche: View {
    let titre: String
    let bouton: String
    let champs: [Riche.Champ]
    let actif: Bool
    let action: (String) -> Void
    @State private var valeurs: [String: String]

    init(titre: String, bouton: String, champs: [Riche.Champ], actif: Bool, action: @escaping (String) -> Void) {
        self.titre = titre
        self.bouton = bouton
        self.champs = champs
        self.actif = actif
        self.action = action
        var v: [String: String] = [:]
        for c in champs {
            // une liste sans valeur donnée prend sa première option, comme un <select>
            v[c.cle] = c.valeur ?? (c.type == "liste" ? (c.options.first ?? "") : "")
        }
        _valeurs = State(initialValue: v)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !titre.isEmpty { Text(titre).font(.system(size: tailleTexteChat, weight: .semibold)) }
            ForEach(Array(champs.enumerated()), id: \.offset) { _, c in
                VStack(alignment: .leading, spacing: 2) {
                    Text(c.label).font(.footnote).foregroundStyle(.secondary)
                    champ(c)
                }
            }
            Button(bouton) {
                action(Riche.messageFormulaire(titre: titre, champs: champs, valeurs: valeurs))
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
            .disabled(!actif)
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.carte))
    }

    private func lien(_ cle: String) -> Binding<String> {
        return Binding(get: { valeurs[cle] ?? "" }, set: { valeurs[cle] = $0 })
    }

    @ViewBuilder
    private func champ(_ c: Riche.Champ) -> some View {
        if c.type == "liste" {
            Picker(c.label, selection: lien(c.cle)) {
                ForEach(c.options, id: \.self) { o in Text(o).tag(o) }
            }
            .pickerStyle(.menu)
            .disabled(!actif)
        } else {
            TextField(c.aide, text: lien(c.cle))
                .textFieldStyle(.roundedBorder)
                .keyboardType(c.type == "nombre" ? .decimalPad : .default)
                .disabled(!actif)
        }
    }
}
