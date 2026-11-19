import Foundation

/// Noms et cibles des outils de Claude, comme `TOOL_LABELS` et `target()` de `web/chat.js`.
enum Outils {
    private static let libelles: [String: String] = [
        "Read": "Lecture", "Edit": "Modification", "MultiEdit": "Modification", "Write": "Écriture",
        "Bash": "Commande", "Grep": "Recherche", "Glob": "Fichiers", "WebFetch": "Page web",
        "WebSearch": "Recherche web", "Task": "Sous-agent", "Agent": "Sous-agent", "TodoWrite": "Tâches",
        "Skill": "Skill", "AskUserQuestion": "Question", "NotebookEdit": "Carnet",
    ]

    /// Outils qui lancent un sous-agent.
    static let agents: Set<String> = ["Task", "Agent"]

    static func libelle(_ nom: String) -> String { return libelles[nom] ?? nom }

    private static func premiere(_ s: String) -> String {
        return s.split(separator: "\n", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init) ?? ""
    }

    /// Ce sur quoi porte l'outil : commande, fichier, motif, adresse…
    static func cible(_ nom: String, _ e: JSON?) -> String {
        guard let i = e else { return "" }
        switch nom {
        case "Bash":
            return premiere(i.texte("command"))
        case "Read", "Write", "Edit", "MultiEdit", "NotebookEdit":
            let f = i.texte("file_path")
            return f.isEmpty ? i.texte("notebook_path") : f
        case "Grep", "Glob":
            let p = i.texte("path")
            return i.texte("pattern") + (p.isEmpty ? "" : " dans \(p)")
        case "WebFetch":
            return i.texte("url")
        case "WebSearch":
            return i.texte("query")
        case "Task", "Agent":
            let d = i.texte("description")
            return d.isEmpty ? premiere(i.texte("prompt")) : d
        case "Skill":
            return i.texte("skill")
        default:
            // première valeur texte non vide (clés dans l'ordre alphabétique : le JSON lu ne garde pas l'ordre)
            let o = i.objet ?? [:]
            for k in o.keys.sorted() {
                if let s = o[k]?.chaine, !s.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return premiere(s) }
            }
            return ""
        }
    }

    /// Paramètres de l'outil en JSON lisible (détail d'une carte repliée).
    static func details(_ e: JSON?) -> String {
        return (e ?? .vide).texteJoli
    }
}
