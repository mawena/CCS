import Foundation

/**
 * Ce qu'on partage vers CCS : un texte (lien, extrait) et des fichiers reçus par « Ouvrir dans
 * CCS » ou le raccourci `ccs://partager?texte=…`. Les fichiers partent dans le dossier du projet ;
 * rien n'est envoyé à Claude : on relit et on envoie soi-même.
 */
struct Partage: Equatable, Identifiable {
    var texte: String
    var fichiers: [URL]
    let id = UUID()

    var vide: Bool { return texte.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && fichiers.isEmpty }

    /// « 2 fichiers et du texte ».
    var resume: String {
        var parts: [String] = []
        if !fichiers.isEmpty { parts.append(fichiers.count == 1 ? "1 fichier" : "\(fichiers.count) fichiers") }
        if !texte.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { parts.append("du texte") }
        let r: String
        switch parts.count {
        case 0: r = "rien"
        case 1: r = parts[0]
        default: r = parts.dropLast().joined(separator: ", ") + " et " + parts[parts.count - 1]
        }
        return r.prefix(1).uppercased() + r.dropFirst()
    }

    /// Lien `ccs://partager?texte=…` (ou `text=`, `url=`) → partage ; nil pour un autre lien.
    static func depuisLien(_ u: URL) -> Partage? {
        guard u.scheme == "ccs", u.host == "partager" || u.host == "share" else { return nil }
        let q = URLComponents(url: u, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let morceaux = ["titre", "texte", "text", "url"].compactMap { k in q.first { $0.name == k }?.value }
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        var vus: [String] = []
        for m in morceaux where !vus.contains(where: { $0.contains(m) }) { vus.append(m) }
        return Partage(texte: vus.joined(separator: "\n"), fichiers: [])
    }

    /// Nom de remplacement quand le nom existe déjà : « rapport.pdf » → « rapport (2).pdf ».
    static func nomLibre(_ nom: String, _ essai: Int) -> String {
        if essai <= 1 { return nom }
        if let p = nom.lastIndex(of: "."), p > nom.startIndex {
            return "\(nom[..<p]) (\(essai))\(nom[p...])"
        }
        return "\(nom) (\(essai))"
    }

    /// Saisie après le partage : brouillon existant, texte partagé, puis fichiers envoyés cités.
    static func composer(_ brouillon: String, _ texte: String, _ fichiers: [String]) -> String {
        let citation: String
        switch fichiers.count {
        case 0: citation = ""
        case 1: citation = "Fichier ajouté au dossier du projet : `\(fichiers[0])`"
        default: citation = "Fichiers ajoutés au dossier du projet : " + fichiers.map { "`\($0)`" }.joined(separator: ", ")
        }
        let parts = [brouillon.replacingOccurrences(of: "\\s+$", with: "", options: .regularExpression),
                     texte.trimmingCharacters(in: .whitespacesAndNewlines), citation]
        return parts.filter { !$0.isEmpty }.joined(separator: "\n\n")
    }
}
