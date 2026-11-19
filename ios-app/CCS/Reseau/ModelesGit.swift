import Foundation

// Réponses des RPC `git.*` (`bridge_git.py`).

struct BrancheGit: LisibleJSON, Equatable {
    var name: String?
    var upstream: String?
    var ahead = 0
    var behind = 0

    init(json j: JSON) {
        name = j.texteOuNul("name")
        upstream = j.texteOuNul("upstream")
        ahead = j.entier("ahead")
        behind = j.entier("behind")
    }

    init(_ name: String?, _ upstream: String? = nil, _ ahead: Int = 0, _ behind: Int = 0) {
        self.name = name
        self.upstream = upstream
        self.ahead = ahead
        self.behind = behind
    }
}

/// Fichier de `git.status` : lettres de l'index et de la copie de travail (`.` : rien, `?` : non suivi).
struct FichierGit: LisibleJSON, Equatable, Hashable {
    var path = ""
    var staged = "."
    var unstaged = "."
    var ancien: String?

    init(json j: JSON) {
        path = j.texte("path")
        staged = j.texteOuNul("staged") ?? "."
        unstaged = j.texteOuNul("unstaged") ?? "."
        ancien = j.texteOuNul("orig_path")
    }

    init(_ path: String, _ staged: String, _ unstaged: String) {
        self.path = path
        self.staged = staged
        self.unstaged = unstaged
    }
}

struct EtatGit: LisibleJSON {
    var repo = false
    var root = ""
    var branch = BrancheGit(nil)
    var files: [FichierGit] = []
    var truncated = false
    var proposed = ""
    var dernierMessage = ""

    init(json j: JSON) {
        repo = j.bool("repo")
        root = j.texte("root")
        branch = BrancheGit(json: j["branch"] ?? .vide)
        files = j.liste("files").map { FichierGit(json: $0) }
        truncated = j.bool("truncated")
        proposed = j.texte("proposed")
        dernierMessage = j.texte("last_message")
    }
}

struct LigneGit: LisibleJSON, Equatable {
    var kind = " "
    var text = ""
    var ancien: Int?
    var nouveau: Int?

    init(json j: JSON) {
        kind = j.texteOuNul("kind") ?? " "
        text = j.texte("text")
        ancien = j.entierOuNul("old_no")
        nouveau = j.entierOuNul("new_no")
    }
}

struct MorceauGit: LisibleJSON, Equatable {
    var header = ""
    var lines: [LigneGit] = []

    init(json j: JSON) {
        header = j.texte("header")
        lines = j.liste("lines").map { LigneGit(json: $0) }
    }
}

struct DiffGit: LisibleJSON, Equatable {
    var path = ""
    var ancien: String?
    var binary = false
    var nouveau = false
    var deleted = false
    var hunks: [MorceauGit] = []
    var truncated = false
    var tropGros = false

    init(json j: JSON) {
        path = j.texte("path")
        ancien = j.texteOuNul("old_path")
        binary = j.bool("binary")
        nouveau = j.bool("new_file")
        deleted = j.bool("deleted")
        hunks = j.liste("hunks").map { MorceauGit(json: $0) }
        truncated = j.bool("truncated")
        tropGros = j.bool("too_big")
    }

    init(path: String, ancien: String? = nil) {
        self.path = path
        self.ancien = ancien
    }
}

struct ReponseDiff: LisibleJSON {
    var diff: DiffGit?
    init(json j: JSON) {
        if let d = j["diff"], case .objet = d { diff = DiffGit(json: d) }
    }
}

struct CommitGit: LisibleJSON, Identifiable, Equatable {
    var id = ""
    var short = ""
    var author = ""
    var email = ""
    var time: Double = 0
    var subject = ""
    var parents: [String] = []
    var body = ""

    init(json j: JSON) {
        id = j.texte("id")
        short = j.texte("short")
        author = j.texte("author")
        email = j.texte("email")
        time = j.double("time")
        subject = j.texte("subject")
        parents = j.listeTextes("parents")
        body = j.texte("body")
    }
}

struct JournalGit: LisibleJSON {
    var commits: [CommitGit] = []
    var more = false

    init(json j: JSON) {
        commits = j.liste("commits").map { CommitGit(json: $0) }
        more = j.bool("more")
    }

    init(commits: [CommitGit], more: Bool) {
        self.commits = commits
        self.more = more
    }
}

struct RefGit: LisibleJSON, Equatable {
    var name = ""
    var kind = ""
    var target = ""

    init(json j: JSON) {
        name = j.texte("name")
        kind = j.texte("kind")
        target = j.texte("target")
    }

    init(_ name: String, _ kind: String, _ target: String) {
        self.name = name
        self.kind = kind
        self.target = target
    }
}

struct RefsGit: LisibleJSON {
    var refs: [RefGit] = []
    init(json j: JSON) { refs = j.liste("refs").map { RefGit(json: $0) } }
}

struct DetailCommit: LisibleJSON {
    var commit = CommitGit(json: .vide)
    var files: [DiffGit] = []
    var truncated = false

    init(json j: JSON) {
        commit = CommitGit(json: j["commit"] ?? .vide)
        files = j.liste("files").map { DiffGit(json: $0) }
        truncated = j.bool("truncated")
    }
}
