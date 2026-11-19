import Foundation

/**
 * Chemins et textes du gestionnaire de fichiers (`web/files*.js`) : chemins relatifs, fil
 * d'Ariane, famille d'un fichier (icône, coloration), tailles, confirmations.
 */
enum Fichiers {
    static let morceau = 1024 * 1024                 // octets par morceau, comme le pont (CHUNK)
    static let maxTransfert: Int64 = 200 * 1024 * 1024  // 200 Mo, comme le pont

    private static func sansBarreFinale(_ c: String) -> String {
        var t = Substring(c)
        while t.hasSuffix("/") { t = t.dropLast() }
        return String(t)
    }

    static func nom(_ chemin: String) -> String {
        let c = sansBarreFinale(chemin)
        let n = c.split(separator: "/", omittingEmptySubsequences: false).last.map(String.init) ?? ""
        return n.isEmpty ? "/" : n
    }

    static func parent(_ chemin: String) -> String {
        let c = sansBarreFinale(chemin)
        guard let i = c.lastIndex(of: "/"), i > c.startIndex else { return "/" }
        return String(c[c.startIndex..<i])
    }

    static func joindre(_ base: String, _ rel: String) -> String {
        if rel.isEmpty { return base }
        var r = Substring(rel)
        while r.hasPrefix("/") { r = r.dropFirst() }
        return sansBarreFinale(base) + "/" + r
    }

    static func sous(_ chemin: String, _ racine: String) -> Bool {
        let r = sansBarreFinale(racine)
        return chemin == racine || chemin == r || chemin.hasPrefix(r + "/") || r.isEmpty
    }

    /// Chemin relatif à `base` (vide si c'est `base`), ou nil s'il n'est pas dedans.
    static func relatif(_ chemin: String, _ base: String) -> String? {
        let b = sansBarreFinale(base)
        var c = sansBarreFinale(chemin)
        if c.isEmpty { c = "/" }
        if c == b || (b.isEmpty && c == "/") { return "" }
        if c.hasPrefix(b + "/") { return String(c.dropFirst(b.count + 1)) }
        return nil
    }

    /// Racine (la plus longue) qui contient `chemin`, sinon `defaut`.
    static func racineDe(_ chemin: String, _ racines: [String], _ defaut: String) -> String {
        return racines.filter { sous(chemin, $0) }.max { $0.count < $1.count } ?? defaut
    }

    /// Fil d'Ariane : (libellé, chemin absolu) depuis `base` (« Personnel » si c'est `home`).
    static func ariane(_ chemin: String, _ base: String, _ home: String) -> [(nom: String, chemin: String)] {
        var out: [(nom: String, chemin: String)] = [(base == home ? "Personnel" : base, base)]
        guard let rel = relatif(chemin, base) else { return out }
        var at = base
        for p in rel.split(separator: "/") {
            at = joindre(at, String(p))
            out.append((String(p), at))
        }
        return out
    }

    enum Genre { case dossier, fichier, texte, code, config, image, archive, media, document }

    private static let parExtension: [String: Genre] = {
        var m: [String: Genre] = [:]
        func mettre(_ g: Genre, _ t: String) { for e in t.split(separator: " ") { m[String(e)] = g } }
        mettre(.image, "png jpg jpeg gif webp svg bmp ico avif heic tif tiff")
        mettre(.code, "js mjs cjs ts tsx jsx py rb go rs c h cc cpp hpp java kt kts swift php sh bash zsh fish lua pl r sql css scss less html htm vue svelte dart cs gradle")
        mettre(.config, "json yaml yml toml ini cfg conf env xml lock service desktop gitignore editorconfig properties")
        mettre(.texte, "txt md markdown rst log csv tsv tex org adoc")
        mettre(.archive, "zip tar gz tgz bz2 xz zst 7z rar deb rpm jar war iso apk")
        mettre(.media, "mp3 wav ogg flac m4a opus mp4 mkv webm avi mov")
        mettre(.document, "pdf odt ods odp doc docx xls xlsx ppt pptx epub")
        return m
    }()

    private static let parNom: [String: Genre] = [
        "makefile": .code, "dockerfile": .code, "license": .texte, "readme": .texte, "changelog": .texte,
    ]

    static func extensionDe(_ nom: String) -> String {
        let n = nom.lowercased()
        guard let i = n.lastIndex(of: ".") else { return "" }
        return String(n[n.index(after: i)...])
    }

    static func genre(_ nom: String, dossier: Bool = false) -> Genre {
        if dossier { return .dossier }
        let n = nom.lowercased()
        if let g = parExtension[extensionDe(n)] { return g }
        if let g = parNom[n] { return g }
        return n.hasPrefix(".") ? .config : .fichier
    }

    /// Langue de coloration d'après le nom du fichier.
    static func langue(_ nom: String) -> String {
        let n = nom.lowercased()
        if n == "makefile" || n == "gnumakefile" { return "make" }
        if n == "dockerfile" || n.hasPrefix("dockerfile.") { return "dockerfile" }
        if n == ".env" || n.hasPrefix(".env.") { return "env" }
        let e = extensionDe(n)
        switch e {
        case "service", "desktop", "cfg", "editorconfig", "gitconfig": return "ini"
        case "markdown": return "md"
        case "zsh", "bash", "fish": return "sh"
        default: return e
        }
    }

    static func estMarkdown(_ nom: String) -> Bool { return ["md", "markdown"].contains(extensionDe(nom)) }

    /// Taille lisible, comme la version web : « 512 o », « 12 Ko », « 3,4 Mo ».
    static func taille(_ n: Int64) -> String {
        if n < 1024 { return "\(n) o" }
        if n < 1024 * 1024 { return "\(Int((Double(n) / 1024).rounded())) Ko" }
        return String(format: "%.1f", Double(n) / 1024 / 1024).replacingOccurrences(of: ".", with: ",") + " Mo"
    }

    /// Texte de la confirmation de suppression (d'après `files.info`).
    static func texteSuppression(dossier: Bool, nombre: Int, octets: Int64) -> String {
        if dossier && nombre > 0 { return "Ce dossier et les \(nombre) éléments qu'il contient seront supprimés pour de bon." }
        if dossier { return "Ce dossier vide sera supprimé." }
        return "Ce fichier (\(taille(octets))) sera supprimé pour de bon."
    }

    /// Message d'erreur d'un nom refusé, ou nil s'il convient (le pont vérifie aussi).
    static func nomRefuse(_ nom: String) -> String? {
        if nom.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Le nom est vide." }
        if nom == "." || nom == ".." || nom.contains("/") || nom.contains("\u{0}") {
            return "Nom refusé : pas de « / », ni « . » ou « .. »."
        }
        if nom.utf8.count > 255 { return "Nom trop long (255 octets au plus)." }
        return nil
    }

    private static let marques = ["M": "modifié", "A": "ajouté", "?": "nouveau", "D": "supprimé"]
    static func marque(_ m: String) -> String { return marques[m] ?? "" }

    /// Positions (début, longueur) des morceaux d'un envoi de `total` octets (au moins un, même vide).
    static func morceaux(_ total: Int64, morceau: Int = Fichiers.morceau) -> [(debut: Int64, longueur: Int)] {
        if total <= 0 { return [(0, 0)] }
        var out: [(debut: Int64, longueur: Int)] = []
        var o: Int64 = 0
        while o < total {
            let n = Int(min(Int64(morceau), total - o))
            out.append((o, n))
            o += Int64(n)
        }
        return out
    }

    /// Découpe un texte en lignes pour l'affichage numéroté (sans ligne vide finale de trop).
    static func lignes(_ texte: String) -> [String] {
        var l = texte.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n")
        if l.count > 1 && l.last == "" { l.removeLast() }
        return l
    }
}
