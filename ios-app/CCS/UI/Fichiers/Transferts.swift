import SwiftUI
import UIKit

/**
 * Transferts par le RPC, morceau par morceau (`files.download`, `files.upload`), comme
 * `web/files-manage.js` : un message RPC est borné. Les fichiers téléchargés vont dans un
 * dossier temporaire, puis dans la feuille de partage d'iOS ou « Enregistrer dans Fichiers ».
 */
@MainActor
enum Transferts {
    private static var dossierPartage: URL {
        return FileManager.default.temporaryDirectory.appendingPathComponent("partage", isDirectory: true)
    }

    /// Nom de fichier sans caractère gênant pour le système.
    static func nettoyer(_ nom: String) -> String {
        let t = nom.replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: ":", with: "_")
        return t.isEmpty || t == "." || t == ".." ? "fichier" : t
    }

    /// Télécharge `chemin` dans un dossier temporaire neuf ; `progres(reçu, total)`.
    static func telecharger(_ client: CcsClient, _ chemin: String, progres: @escaping (Int64, Int64) -> Void = { _, _ in }) async throws -> URL {
        let fm = FileManager.default
        // les partages précédents ne servent plus
        try? fm.removeItem(at: dossierPartage)
        let dossier = dossierPartage.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try fm.createDirectory(at: dossier, withIntermediateDirectories: true)
        let url = dossier.appendingPathComponent(nettoyer(Fichiers.nom(chemin)))
        guard fm.createFile(atPath: url.path, contents: nil) else { throw ErreurHttp(message: "Écriture impossible sur le téléphone.") }
        let h = try FileHandle(forWritingTo: url)
        defer { try? h.close() }
        var recu: Int64 = 0
        while true {
            let r = try await client.appeler("files.download", ["path": .chaine(chemin), "offset": .nombre(Double(recu))],
                                             delai: 120, en: MorceauFichier.self)
            let octets = Data(base64Encoded: r.data) ?? Data()
            try h.write(contentsOf: octets)
            recu += Int64(octets.count)
            progres(recu, r.size)
            if r.done || octets.isEmpty { break }
        }
        return url
    }

    /// Taille d'un fichier choisi (-1 si inconnue).
    static func taille(_ url: URL) -> Int64 {
        let v = try? url.resourceValues(forKeys: [.fileSizeKey])
        return Int64(v?.fileSize ?? -1)
    }

    /**
     * Envoie le fichier local `url` dans le dossier `dossier` du serveur sous le nom `nom`
     * (`remplacer` : écrase). L'erreur `existe` du pont remonte telle quelle.
     */
    static func envoyer(_ client: CcsClient, dossier: String, url: URL, nom: String, remplacer: Bool,
                        progres: @escaping (Int64, Int64) -> Void = { _, _ in }) async throws {
        let total = taille(url)
        if total > Fichiers.maxTransfert { throw ErreurHttp(message: "Fichier trop gros pour être envoyé (200 Mo au plus).") }
        let acces = url.startAccessingSecurityScopedResource()
        defer { if acces { url.stopAccessingSecurityScopedResource() } }
        guard let h = try? FileHandle(forReadingFrom: url) else { throw ErreurHttp(message: "Impossible de lire « \(nom) ».") }
        defer { try? h.close() }
        var envoye: Int64 = 0
        var suivant = try h.read(upToCount: Fichiers.morceau) ?? Data()
        while true {
            let donnees = suivant
            suivant = donnees.count == Fichiers.morceau ? (try h.read(upToCount: Fichiers.morceau) ?? Data()) : Data()
            let dernier = suivant.isEmpty
            if envoye + Int64(donnees.count) > Fichiers.maxTransfert {
                throw ErreurHttp(message: "Fichier trop gros pour être envoyé (200 Mo au plus).")
            }
            _ = try await client.appeler("files.upload", [
                "dir": .chaine(dossier), "name": .chaine(nom), "offset": .nombre(Double(envoye)),
                "data": .chaine(donnees.base64EncodedString()), "last": .booleen(dernier), "replace": .booleen(remplacer),
            ], delai: 120)
            envoye += Int64(donnees.count)
            progres(envoye, total)
            if dernier { break }
        }
    }
}

/// Ce qui attend d'être collé (copié ou coupé) : commun à tous les volets, comme au web.
@MainActor
@Observable
final class Presse {
    struct Tenu: Equatable {
        let chemin: String
        let nom: String
        let deplacer: Bool
    }

    static let partage = Presse()
    var tenu: Tenu? = nil
}

/// Fichier local prêt à partager ou enregistrer.
struct FichierLocal: Identifiable {
    let id = UUID()
    let url: URL
    /// Vrai : « Enregistrer dans Fichiers » ; faux : feuille de partage d'iOS.
    let enregistrer: Bool
}

/// Feuille de partage d'iOS (AirDrop, Messages, « Enregistrer dans Fichiers »…).
struct FeuillePartageIOS: UIViewControllerRepresentable {
    let elements: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        return UIActivityViewController(activityItems: elements, applicationActivities: nil)
    }

    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}

/// Choix d'un dossier de l'appli Fichiers où copier le fichier.
struct ExportFichiers: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        return UIDocumentPickerViewController(forExporting: [url], asCopy: true)
    }

    func updateUIViewController(_ vc: UIDocumentPickerViewController, context: Context) {}
}

extension View {
    /// Présente le fichier téléchargé : partage ou enregistrement.
    func presenterFichier(_ f: Binding<FichierLocal?>) -> some View {
        return sheet(item: f) { l in
            if l.enregistrer {
                ExportFichiers(url: l.url).ignoresSafeArea()
            } else {
                FeuillePartageIOS(elements: [l.url]).presentationDetents([.medium, .large]).ignoresSafeArea()
            }
        }
    }
}

// MARK: icônes et couleurs des fichiers

extension Fichiers.Genre {
    var icone: String {
        switch self {
        case .dossier: return "folder.fill"
        case .texte: return "doc.text"
        case .code: return "chevron.left.forwardslash.chevron.right"
        case .config: return "gearshape"
        case .image: return "photo"
        case .archive: return "archivebox"
        case .media: return "film"
        case .document: return "doc.richtext"
        case .fichier: return "doc"
        }
    }

    /// Couleur de l'icône d'une famille (celles de la version web).
    var teinte: Color {
        switch self {
        case .dossier: return Color(hex: "#E5A50A") ?? .yellow
        case .code: return Color(hex: "#3584E4") ?? .blue
        case .config: return Color(hex: "#9141AC") ?? .purple
        case .image: return Color(hex: "#2EC27E") ?? .green
        case .archive: return Color(hex: "#C64600") ?? .orange
        case .media: return Color(hex: "#E01B24") ?? .red
        case .document: return Color(hex: "#C01C28") ?? .red
        case .texte, .fichier: return Color(hex: "#77767B") ?? .gray
        }
    }
}

/// Couleur d'une marque git (M, A, ?, D).
func couleurMarque(_ m: String) -> Color {
    switch m {
    case "M": return .avertissement
    case "A", "?": return .reussite
    case "D": return Color(hex: "#E01B24") ?? .red
    default: return .secondary
    }
}

/// Bandeau « travail en cours » avec barre de progression facultative.
@MainActor
struct BandeauTravail: View {
    let texte: String
    var progres: Double? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                if progres == nil { ProgressView().controlSize(.small) }
                Text(texte).font(.footnote).foregroundStyle(.secondary)
            }
            if let p = progres { ProgressView(value: p) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 16)
        .padding(.vertical, 6)
    }
}
