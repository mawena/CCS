import Foundation

// Réponses des RPC `files.*` (`bridge_data.py`, `bridge_files.py`).

struct RacinesFichiers: LisibleJSON {
    var home = ""
    var roots: [String] = []
    init(json j: JSON) {
        home = j.texte("home")
        roots = j.listeTextes("roots")
    }
}

/// Une entrée de `files.list` (ou de `files.search`) : chemin relatif à la racine demandée.
struct EntreeFichier: LisibleJSON, Identifiable, Equatable, Hashable {
    var name = ""
    var path = ""
    var dir = false
    var mark = ""
    var id: String { return path }

    init(json j: JSON) {
        name = j.texte("name")
        path = j.texte("path")
        dir = j.bool("dir")
        mark = j.texte("mark")
    }

    init(name: String, path: String, dir: Bool, mark: String = "") {
        self.name = name
        self.path = path
        self.dir = dir
        self.mark = mark
    }

    /// La même entrée avec un chemin absolu.
    func avec(chemin: String) -> EntreeFichier {
        return EntreeFichier(name: name, path: chemin, dir: dir, mark: mark)
    }
}

struct ListeFichiers: LisibleJSON {
    var entries: [EntreeFichier] = []
    var truncated = false
    init(json j: JSON) {
        entries = j.liste("entries").map { EntreeFichier(json: $0) }
        truncated = j.bool("truncated")
    }
}

/// `files.read` : `kind` vaut text, image, binary ou too_big ; `stamp` est renvoyé tel quel à `files.write`.
struct FichierLu: LisibleJSON {
    var kind = ""
    var stamp: JSON?
    var text: String?
    var encoding: String?
    init(json j: JSON) {
        kind = j.texte("kind")
        stamp = j["stamp"].flatMap { $0.estNul ? nil : $0 }
        text = j["text"]?.chaine
        encoding = j.texteOuNul("encoding")
    }
}

struct ImageFichier: LisibleJSON {
    var mime = ""
    var data = ""
    init(json j: JSON) {
        mime = j.texte("mime")
        data = j.texte("data")
    }
}

struct MorceauFichier: LisibleJSON {
    var size: Int64 = 0
    var data = ""
    var done = false
    init(json j: JSON) {
        size = Int64(j.entier("size"))
        data = j.texte("data")
        done = j.bool("done")
    }
}

struct InfoFichier: LisibleJSON {
    var dir = false
    var count = 0
    var size: Int64 = 0
    init(json j: JSON) {
        dir = j.bool("dir")
        count = j.entier("count")
        size = Int64(j.entier("size"))
    }
}

struct CheminRendu: LisibleJSON {
    var path = ""
    init(json j: JSON) { path = j.texte("path") }
}

struct FichierEcrit: LisibleJSON {
    var stamp: JSON?
    init(json j: JSON) { stamp = j["stamp"].flatMap { $0.estNul ? nil : $0 } }
}

struct IndexFichiers: LisibleJSON {
    var files: [String] = []
    init(json j: JSON) { files = j.listeTextes("files") }
}
