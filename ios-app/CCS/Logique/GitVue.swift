import Foundation

/// Ce que l'écran Git tire des réponses de `git.*` (`web/git.js`).
enum GitVue {
    private static let marques = [
        "M": "modifié", "T": "type changé", "A": "ajouté", "D": "supprimé", "R": "renommé",
        "C": "copié", "U": "en conflit", "?": "non suivi",
    ]

    static func marque(_ lettre: String) -> String { return marques[lettre] ?? lettre }

    enum Cote: String { case index = "Index", travail = "Travail" }

    struct Groupe {
        let titre: String
        let fichiers: [FichierGit]
        let cote: Cote
        let verbe: String
        let methode: String
        let tout: String
        let lettre: (FichierGit) -> String
    }

    static func indexe(_ f: FichierGit) -> Bool { return f.staged != "." && f.staged != "?" }
    static func modifie(_ f: FichierGit) -> Bool { return f.unstaged != "." && f.unstaged != "?" }
    static func nonSuivi(_ f: FichierGit) -> Bool { return f.staged == "?" }

    /// Indexés, Modifiés, Non suivis (groupes vides omis).
    static func groupes(_ e: EtatGit) -> [Groupe] {
        return [
            Groupe(titre: "Indexés", fichiers: e.files.filter(indexe), cote: .index, verbe: "Désindexer",
                   methode: "git.unstage", tout: "Tout désindexer") { $0.staged },
            Groupe(titre: "Modifiés", fichiers: e.files.filter(modifie), cote: .travail, verbe: "Indexer",
                   methode: "git.stage", tout: "Tout indexer") { $0.unstaged },
            Groupe(titre: "Non suivis", fichiers: e.files.filter(nonSuivi), cote: .travail, verbe: "Indexer",
                   methode: "git.stage", tout: "Tout indexer") { _ in "?" },
        ].filter { !$0.fichiers.isEmpty }
    }

    static func cle(_ cote: Cote, _ chemin: String) -> String { return cote.rawValue + ":" + chemin }

    /// Clés des diffs ouverts qui existent encore après une actualisation.
    static func clesGardees(_ ouvertes: Set<String>, _ e: EtatGit) -> Set<String> {
        var existent = Set<String>()
        for f in e.files {
            if indexe(f) { existent.insert(cle(.index, f.path)) }
            if f.unstaged != "." { existent.insert(cle(.travail, f.path)) }
        }
        return ouvertes.intersection(existent)
    }

    static func peutCommit(_ e: EtatGit, amend: Bool) -> Bool { return amend || e.files.contains(where: indexe) }

    /// « origin/main · ↑1 ↓2 », « origin/main · à jour » ou « pas de suivi distant ».
    static func synchro(_ b: BrancheGit) -> String {
        var p: [String] = []
        if b.ahead > 0 { p.append("↑\(b.ahead)") }
        if b.behind > 0 { p.append("↓\(b.behind)") }
        guard let u = b.upstream else { return "pas de suivi distant" }
        return p.isEmpty ? "\(u) · à jour" : "\(u) · " + p.joined(separator: " ")
    }

    static func textePush(_ b: BrancheGit) -> String {
        guard let u = b.upstream else { return "Le premier push crée la branche sur le dépôt distant." }
        if b.ahead > 0 { return "\(b.ahead) commit(s) partiront vers \(u)." }
        return "Rien de nouveau à pousser."
    }

    static func textePull(_ b: BrancheGit) -> String {
        guard let u = b.upstream else { return "Cette branche ne suit aucune branche distante." }
        if b.behind > 0 { return "\(b.behind) commit(s) arriveront de \(u)." }
        return "Récupère et intègre les nouveautés de \(u)."
    }

    /// Un morceau s'indexe seul sauf pour un fichier non suivi, neuf ou supprimé (en entier).
    static func parMorceau(_ lettre: String, _ d: DiffGit) -> Bool { return lettre != "?" && !d.nouveau && !d.deleted }

    /// Lignes d'un morceau au format du diff du chat (avec numéros).
    static func lignes(_ m: MorceauGit) -> [Diff.Ligne] {
        return m.lines.map { l in
            let g: Diff.Genre = l.kind == "+" ? .ajout : (l.kind == "-" ? .retrait : .contexte)
            return Diff.Ligne(genre: g, texte: l.text, ancien: l.ancien, nouveau: l.nouveau)
        }
    }

    /// Diff entier d'un fichier (en-têtes `@@` en séparateurs), pour le détail d'un commit.
    static func fichier(_ d: DiffGit) -> Diff.Fichier {
        var l: [Diff.Ligne] = []
        for h in d.hunks {
            l.append(Diff.Ligne(genre: .morceau, texte: h.header))
            l.append(contentsOf: lignes(h))
        }
        return Diff.Fichier(chemin: d.path, lignes: l)
    }

    /// Texte quand un diff n'a rien à montrer, ou nil.
    static func sansDiff(_ d: DiffGit?) -> String? {
        guard let d = d else { return "Pas de différence à montrer." }
        if d.tropGros { return "Fichier trop gros pour être montré." }
        if d.binary { return "Fichier binaire : pas de diff." }
        if d.hunks.isEmpty { return "Pas de différence à montrer." }
        return nil
    }

    static func etatFichier(_ d: DiffGit) -> String {
        if d.nouveau { return "ajouté" }
        if d.deleted { return "supprimé" }
        if let a = d.ancien, a != d.path { return "renommé (\(a))" }
        return "modifié"
    }

    /// Refs par genre, dans l'ordre : branches locales, distantes, tags.
    static func refs(_ refs: [RefGit]) -> [(titre: String, refs: [RefGit])] {
        let l: [(titre: String, refs: [RefGit])] = [
            ("Branches", refs.filter { $0.kind == "branch" }.sorted { $0.name.lowercased() < $1.name.lowercased() }),
            ("Branches distantes", refs.filter { $0.kind == "remote" }.sorted { $0.name.lowercased() < $1.name.lowercased() }),
            ("Tags", refs.filter { $0.kind == "tag" }.sorted { $0.name > $1.name }),
        ]
        return l.filter { !$0.refs.isEmpty }
    }
}
