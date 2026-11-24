import SwiftUI
import UIKit

/**
 * Fichier ouvert (`FileView` de `web/files.js`) : code coloré numéroté (ligne citée en évidence),
 * Markdown rendu (« Aperçu »), images (zoom à deux doigts), édition et enregistrement avec conflit
 * signalé, enregistrer dans Fichiers, partager. Quitter avec des modifications est confirmé.
 */
@MainActor
struct EcranFichier: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.dismiss) private var fermer
    @Environment(\.appareilFichiers) private var appareilFichiers
    let chemin: String
    let ligne: Int?

    @State private var lu: FichierLu? = nil
    @State private var erreur: String? = nil
    @State private var image: UIImage? = nil
    @State private var imageErreur: String? = nil
    @State private var original = ""
    @State private var stamp: JSON? = nil
    @State private var edition = false
    @State private var champ = ""
    @State private var apercu = false
    @State private var retourLigne = Prefs.lire("fichiers:retour-ligne") == "1"
    @State private var travail: String? = nil
    @State private var progres: Double? = nil
    @State private var local: FichierLocal? = nil
    @State private var abandon = false

    /// Connexion de l'appareil ouvert dans l'onglet Fichiers, sinon celle de la machine pilotée.
    private var client: CcsClient { return modele.fichiers.clientPour(appareilFichiers) }
    private var nom: String { return Fichiers.nom(chemin) }
    private var modifie: Bool { return edition && champ != original }
    private var estTexte: Bool { return lu?.kind == "text" }

    var body: some View {
        VStack(spacing: 0) {
            if let t = travail { BandeauTravail(texte: t, progres: progres) }
            contenu
        }
        .navigationTitle(nom)
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(modifie)
        .toolbar {
            ToolbarItem(placement: .principal) {
                VStack(spacing: 0) {
                    Text(nom).font(.headline).lineLimit(1)
                    Text(Fichiers.parent(chemin)).font(.caption2).foregroundStyle(.secondary).lineLimit(1).truncationMode(.head)
                }
            }
            if modifie {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Annuler") { abandon = true }
                }
            }
            ToolbarItemGroup(placement: .topBarTrailing) {
                if estTexte && edition {
                    Button("Enregistrer") { enregistrer() }.disabled(travail != nil).fontWeight(.semibold)
                } else if estTexte {
                    if Fichiers.estMarkdown(nom) {
                        Button {
                            apercu.toggle()
                        } label: {
                            Image(systemName: apercu ? "chevron.left.forwardslash.chevron.right" : "eye")
                        }
                        .accessibilityLabel(apercu ? "Source" : "Aperçu")
                    }
                    Button {
                        champ = original
                        apercu = false
                        edition = true
                    } label: {
                        Image(systemName: "pencil")
                    }
                    .accessibilityLabel("Modifier")
                }
                Menu {
                    Button { recuperer(enregistrer: true) } label: { Label("Enregistrer dans Fichiers", systemImage: "square.and.arrow.down") }
                    Button { recuperer(enregistrer: false) } label: { Label("Partager", systemImage: "square.and.arrow.up") }
                    if estTexte {
                        Button {
                            retourLigne.toggle()
                            Prefs.ecrire("fichiers:retour-ligne", retourLigne ? "1" : "0")
                        } label: {
                            Label(retourLigne ? "Sans retour à la ligne" : "Retour à la ligne", systemImage: "text.alignleft")
                        }
                        Button {
                            copier(edition ? champ : original)
                            modele.avis.dire("Texte copié.")
                        } label: { Label("Copier tout le texte", systemImage: "doc.on.doc") }
                    }
                    if edition {
                        Button(role: .destructive) {
                            if modifie { abandon = true } else { edition = false }
                        } label: { Label("Annuler les modifications", systemImage: "arrow.uturn.backward") }
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
                .accessibilityLabel("Plus d'actions")
            }
        }
        .toolbar(.hidden, for: .tabBar)
        .task(id: client.etat.estConnecte) {
            guard client.etat.estConnecte, lu == nil else { return }
            await charger()
        }
        .confirmationDialog("Abandonner les modifications ?", isPresented: $abandon, titleVisibility: .visible) {
            Button("Abandonner", role: .destructive) {
                champ = original
                edition = false
            }
            Button("Continuer à modifier", role: .cancel) {}
        } message: {
            Text("Elles ne sont pas enregistrées.")
        }
        .presenterFichier($local)
    }

    @ViewBuilder
    private var contenu: some View {
        if let l = lu {
            switch l.kind {
            case "text":
                if edition {
                    TextEditor(text: $champ)
                        .font(.system(size: 13, design: .monospaced))
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .padding(.horizontal, 4)
                } else if Fichiers.estMarkdown(nom) && apercu {
                    ScrollView {
                        // images et médias relatifs au dossier du fichier ; blocs ccs sans envoi
                        MarkdownVue(texte: original).padding(16).frame(maxWidth: .infinity, alignment: .leading)
                            .environment(\.chatRiche, ChatRiche(cwd: (chemin as NSString).deletingLastPathComponent, envoyer: nil))
                    }
                } else {
                    VueCode(texte: original, langue: Fichiers.langue(nom), ligne: ligne, retourLigne: retourLigne)
                }
            case "image":
                if let im = image {
                    ImageZoom(image: im)
                } else {
                    EtatVide(imageErreur ?? "Chargement de l'image…")
                    Spacer()
                }
            default:
                VStack(spacing: 12) {
                    Text(l.kind == "binary" ? "Fichier binaire : il n'est pas affiché." : "Fichier trop gros pour être affiché ici.")
                        .foregroundStyle(.secondary)
                    Button("Enregistrer dans Fichiers") { recuperer(enregistrer: true) }.buttonStyle(.bordered)
                    Button("Partager") { recuperer(enregistrer: false) }.buttonStyle(.bordered)
                    Spacer()
                }
                .padding(24)
            }
        } else if let e = erreur {
            EtatErreur(message: e) { Task { await charger() } }
            Spacer()
        } else {
            Chargement()
            Spacer()
        }
    }

    private func charger() async {
        erreur = nil
        do {
            let r = try await client.appeler("files.read", ["path": .chaine(chemin)], en: FichierLu.self)
            stamp = r.stamp
            if r.kind == "text" {
                original = r.text ?? ""
                if !edition || champ.isEmpty { champ = original }
            }
            if r.kind == "image" {
                do {
                    let im = try await client.appeler("files.image", ["path": .chaine(chemin)], delai: 60, en: ImageFichier.self)
                    let d = Data(base64Encoded: im.data)
                    image = d.flatMap { UIImage(data: $0) }
                    imageErreur = image == nil ? "Cette image ne s'affiche pas ici (format non pris en charge)." : nil
                } catch {
                    imageErreur = texteErreur(error)
                }
            }
            lu = r
        } catch {
            erreur = texteErreur(error)
        }
    }

    private func agir(_ libelle: String, _ action: @escaping () async throws -> Void) {
        guard travail == nil else { return }
        travail = libelle
        progres = nil
        Task { @MainActor in
            do { try await action() } catch { modele.avis.dire(texteErreur(error), long: true) }
            travail = nil
            progres = nil
        }
    }

    private func enregistrer() {
        agir("Enregistrement…") {
            var p: [String: JSON] = ["path": .chaine(chemin), "text": .chaine(champ)]
            if let s = stamp { p["stamp"] = s }
            do {
                let r = try await client.appeler("files.write", p, en: FichierEcrit.self)
                stamp = r.stamp
                original = champ
                edition = false
                modele.avis.dire("Enregistré.")
            } catch let e as RpcErreur where e.code == "conflit" {
                modele.avis.dire(
                    "Le fichier a changé depuis son ouverture (Claude l'a peut-être modifié) : copie tes changements, puis rouvre-le.",
                    long: true
                )
            }
        }
    }

    private func recuperer(enregistrer: Bool) {
        agir("Téléchargement…") {
            let url = try await Transferts.telecharger(client, chemin) { a, b in
                progres = b > 0 ? min(1, Double(a) / Double(b)) : nil
            }
            local = FichierLocal(url: url, enregistrer: enregistrer)
        }
    }
}

/// Lignes colorées par paquets de 200 (la coloration est bornée en taille).
enum LignesColorees {
    static let paquet = 200

    static func couleur(_ g: Coloration.Genre, sombre: Bool) -> Color {
        switch g {
        case .motCle: return sombre ? Color(red: 0.78, green: 0.56, blue: 1.0) : Color(red: 0.55, green: 0.16, blue: 0.75)
        case .chaine: return sombre ? Color(red: 0.6, green: 0.85, blue: 0.5) : Color(red: 0.15, green: 0.5, blue: 0.1)
        case .commentaire: return .secondary
        case .nombre: return sombre ? Color(red: 0.98, green: 0.7, blue: 0.4) : Color(red: 0.7, green: 0.35, blue: 0.0)
        case .ajout: return vertDiff
        case .retrait: return rougeDiff
        case .titre: return .accentCcs
        }
    }

    static func colorer(_ lignes: [String], _ langue: String, sombre: Bool) -> [AttributedString] {
        var out: [AttributedString] = []
        out.reserveCapacity(lignes.count)
        var debut = 0
        while debut < lignes.count {
            let fin = min(lignes.count, debut + paquet)
            let bloc = Array(lignes[debut..<fin].joined(separator: "\n"))
            let genres = Coloration.genres(bloc, langue)
            var pos = 0
            for i in debut..<fin {
                let n = lignes[i].count
                out.append(ligne(bloc, genres, pos, min(bloc.count, pos + n), sombre: sombre))
                pos += n + 1
            }
            debut = fin
        }
        return out
    }

    private static func ligne(_ t: [Character], _ g: [Coloration.Genre?], _ a: Int, _ b: Int, sombre: Bool) -> AttributedString {
        var r = AttributedString()
        var i = a
        while i < b {
            var k = i + 1
            while k < b && g[k] == g[i] { k += 1 }
            var morceau = AttributedString(String(t[i..<k]))
            if let genre = g[i] { morceau.foregroundColor = couleur(genre, sombre: sombre) }
            r.append(morceau)
            i = k
        }
        return r
    }
}

/// Code numéroté et coloré ; défilement horizontal si les lignes ne sont pas repliées.
@MainActor
struct VueCode: View {
    @Environment(\.colorScheme) private var schema
    let texte: String
    let langue: String
    let ligne: Int?
    let retourLigne: Bool

    @State private var colorees: [AttributedString]? = nil

    var body: some View {
        let lignes = Fichiers.lignes(texte)
        let chiffres = String(lignes.count).count
        ScrollViewReader { lecteur in
            ScrollView(retourLigne ? Axis.Set.vertical : [Axis.Set.vertical, Axis.Set.horizontal]) {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(0..<lignes.count, id: \.self) { i in
                        HStack(alignment: .top, spacing: 8) {
                            Text(String(i + 1))
                                .foregroundStyle(.secondary)
                                .frame(width: CGFloat(chiffres) * 8 + 4, alignment: .trailing)
                            Text(colorees.flatMap { i < $0.count ? $0[i] : nil } ?? AttributedString(lignes[i]))
                                .fixedSize(horizontal: !retourLigne, vertical: true)
                                .frame(maxWidth: retourLigne ? .infinity : nil, alignment: .leading)
                        }
                        .font(.system(size: 12.5, design: .monospaced))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 1)
                        .background(ligne == i + 1 ? Color.avertissement.opacity(0.22) : Color.clear)
                        .id(i)
                    }
                }
                .padding(.vertical, 8)
                .textSelection(.enabled)
            }
            .background(Color.fondCode)
            .task(id: "\(texte.count)|\(langue)|\(schema == .dark)") {
                let sombre = schema == .dark
                let l = lignes
                let lg = langue
                let r = await Task.detached(priority: .userInitiated) { LignesColorees.colorer(l, lg, sombre: sombre) }.value
                colorees = r
                if let n = ligne, n > 0 {
                    lecteur.scrollTo(max(0, min(l.count - 1, n - 1 - 5)), anchor: .top)
                }
            }
        }
    }
}

/// Image avec zoom à deux doigts et déplacement une fois zoomée ; double toucher : taille normale.
@MainActor
struct ImageZoom: View {
    let image: UIImage
    @State private var echelle: CGFloat = 1
    @State private var base: CGFloat = 1
    @State private var decalage: CGSize = .zero
    @State private var decalageBase: CGSize = .zero

    var body: some View {
        GeometryReader { g in
            Image(uiImage: image)
                .resizable()
                .scaledToFit()
                .frame(width: g.size.width, height: g.size.height)
                .scaleEffect(echelle)
                .offset(decalage)
                .gesture(
                    MagnificationGesture()
                        .onChanged { v in echelle = min(8, max(1, base * v)) }
                        .onEnded { _ in
                            base = echelle
                            if echelle == 1 { decalage = .zero; decalageBase = .zero }
                        }
                        .simultaneously(with: DragGesture()
                            .onChanged { v in
                                guard echelle > 1 else { return }
                                decalage = CGSize(width: decalageBase.width + v.translation.width, height: decalageBase.height + v.translation.height)
                            }
                            .onEnded { _ in decalageBase = decalage })
                )
                .onTapGesture(count: 2) {
                    echelle = 1
                    base = 1
                    decalage = .zero
                    decalageBase = .zero
                }
        }
        .clipped()
    }
}
