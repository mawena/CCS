import Foundation

/// Feuille de route (`web/roadmap.js`) : progression des phases, phase ouverte au départ.
enum FeuilleRoute {
    struct Progression: Equatable, CustomStringConvertible {
        let faites: Int
        let total: Int
        var fraction: Double { return total == 0 ? 0 : Double(faites) / Double(total) }
        var description: String { return "\(faites)/\(total)" }
    }

    static func progression(_ p: PhaseFeuille) -> Progression {
        return Progression(faites: p.tasks.filter { $0.done }.count, total: p.tasks.count)
    }

    /// Phases ouvertes d'emblée : celles qui ont encore une case vide (comme au bureau).
    static func ouvertes(_ phases: [PhaseFeuille]) -> Set<Int> {
        return Set(phases.indices.filter { i in phases[i].tasks.contains { !$0.done } })
    }

    /// Première phase non finie (à montrer), ou nil.
    static func enCours(_ phases: [PhaseFeuille]) -> Int? {
        return phases.firstIndex { p in p.tasks.contains { !$0.done } }
    }

    /// Indentation d'une sous-tâche (0 à 3 niveaux, comme le web).
    static func niveau(_ profondeur: Int) -> Int { return min(3, max(0, profondeur)) }
}

/// Tâches de fond (`web/pages-tasks.js`) : états, filtres, textes.
enum TachesFond {
    static let etats = [
        "queued": "En attente", "running": "En cours", "waiting": "À reprendre (limite atteinte)",
        "done": "Finie", "failed": "Échouée", "cancelled": "Annulée",
    ]
    static let actives: Set<String> = ["queued", "running", "waiting"]

    struct Filtre: Equatable {
        let cle: String
        let libelle: String
        let etats: Set<String>
    }

    static let filtres = [
        Filtre(cle: "actives", libelle: "À venir", etats: actives),
        Filtre(cle: "done", libelle: "Finies", etats: ["done"]),
        Filtre(cle: "failed", libelle: "Échouées", etats: ["failed"]),
        Filtre(cle: "cancelled", libelle: "Annulées", etats: ["cancelled"]),
    ]

    /// Droits d'une tâche : (valeur, libellé, explication).
    static let droits: [(valeur: String, libelle: String, aide: String)] = [
        ("lecture", "Lecture seule", "Claude lit et analyse ; tout ce qui demande une permission est refusé."),
        ("modifications", "Modifications des fichiers", "Claude modifie les fichiers du dossier sans demander ; le reste est refusé."),
        ("tout", "Tout (aucune vérification)", "Attention : Claude peut tout faire sans rien demander, y compris supprimer."),
    ]
    static let modeles: [(valeur: String, libelle: String)] = [
        ("", "Modèle par défaut"), ("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku"), ("fable", "Fable"),
    ]
    static let quandChoix: [(valeur: String, libelle: String)] = [
        ("quota", "Dès qu'il y a du quota"), ("nuit", "Cette nuit (meilleur créneau)"), ("heure", "À une heure précise…"),
    ]

    static func active(_ t: TacheFond) -> Bool { return actives.contains(t.state) }

    static func etat(_ t: TacheFond) -> String { return etats[t.state] ?? t.state }

    static func quand(_ t: TacheFond) -> String {
        switch t.quand {
        case "quota": return "dès qu'il y a du quota"
        case "nuit": return "cette nuit"
        default: return "à \(t.quand)"
        }
    }

    /// `~/…` à la place du dossier personnel (`shortPath` du web).
    static func cheminCourt(_ chemin: String) -> String {
        return chemin.replacingOccurrences(of: "^/home/[^/]+", with: "~", options: .regularExpression)
    }

    static func sousTitre(_ t: TacheFond, maintenant: Double = Date().timeIntervalSince1970) -> String {
        var p = [etat(t)]
        if t.state == "queued" || t.state == "waiting" {
            p.append(t.note.isEmpty ? quand(t) : t.note)
        } else if let e = t.error, !e.isEmpty {
            p.append(e)
        } else if let f = t.finished {
            p.append(Format.ilYA(f, maintenant: maintenant))
        }
        p.append(cheminCourt(t.cwd))
        return p.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    static func titre(_ t: TacheFond) -> String {
        let premiere = t.message.split(separator: "\n", omittingEmptySubsequences: false).first.map(String.init) ?? ""
        return String(premiere.prefix(120))
    }

    static func libelleDroits(_ valeur: String) -> String {
        return droits.first { $0.valeur == valeur }?.libelle ?? valeur
    }

    static func nombre(_ taches: [TacheFond], _ f: Filtre) -> Int { return taches.filter { f.etats.contains($0.state) }.count }

    /// Filtre montré à l'ouverture : le premier qui a des tâches, sinon « À venir ».
    static func filtreInitial(_ taches: [TacheFond]) -> String {
        return filtres.first { f in taches.contains { f.etats.contains($0.state) } }?.cle ?? "actives"
    }

    /// Tâches d'un filtre, les plus récentes d'abord.
    static func filtrer(_ taches: [TacheFond], _ cle: String) -> [TacheFond] {
        let f = filtres.first { $0.cle == cle } ?? filtres[0]
        return Array(taches.filter { f.etats.contains($0.state) }.reversed())
    }

    /// `~/x` → `/home/moi/x` ; vide si rien n'est saisi.
    static func dossier(_ saisi: String, home: String) -> String {
        let s = saisi.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("~") && !home.isEmpty { return home + s.dropFirst() }
        return s
    }

    static func heureValide(_ h: String) -> Bool {
        return h.range(of: "^([01]?[0-9]|2[0-3]):([0-5][0-9])$", options: .regularExpression) != nil
    }

    /// Erreur du formulaire « Nouvelle tâche », ou nil s'il peut partir.
    static func verifier(dossier: String, message: String, quand: String, heure: String) -> String? {
        if dossier.trimmingCharacters(in: .whitespaces).isEmpty { return "Indique le dossier du projet." }
        if message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Écris ce que Claude doit faire." }
        if quand == "heure" && !heureValide(heure.trimmingCharacters(in: .whitespaces)) { return "Choisis l'heure (HH:MM)." }
        return nil
    }

    /// Valeur de `when` envoyée à `tasks.add`.
    static func quandEnvoye(_ quand: String, heure: String) -> String {
        guard quand == "heure" else { return quand }
        let h = heure.trimmingCharacters(in: .whitespaces)
        return String(repeating: "0", count: max(0, 5 - h.count)) + h
    }
}

/// Travail du chat (`web/chat-changes.js`) : genres de changement, diff unifié, retour arrière.
enum ChangementsChat {
    static let genres = ["created": "créé", "deleted": "supprimé", "modified": "modifié"]

    static func genre(_ f: FichierChange) -> String { return genres[f.kind] ?? f.kind }

    /// Numéros d'un en-tête `@@ -1,3 +1,4 @@`, ou nil.
    static func entete(_ l: String) -> (Int, Int)? {
        guard l.hasPrefix("@@ -") else { return nil }
        let reste = l.dropFirst(4)
        let parties = reste.split(separator: " ", maxSplits: 2)
        guard parties.count >= 2, parties[1].hasPrefix("+") else { return nil }
        let a = parties[0].split(separator: ",").first.flatMap { Int($0) }
        let b = parties[1].dropFirst().split(separator: ",").first.flatMap { Int($0) }
        guard let x = a, let y = b else { return nil }
        return (x, y)
    }

    /// Diff unifié (`--- a`, `+++ b`, `@@ -1,3 +1,4 @@`) en lignes numérotées du chat.
    static func lignes(_ diff: String) -> [Diff.Ligne] {
        var out: [Diff.Ligne] = []
        var ancien = 0
        var nouveau = 0
        var dansMorceau = false
        for l in diff.components(separatedBy: "\n") {
            if let e = entete(l) {
                ancien = e.0
                nouveau = e.1
                dansMorceau = true
                out.append(Diff.Ligne(genre: .morceau, texte: l))
            } else if !dansMorceau {
                continue                                                  // en-têtes ---/+++
            } else if l.hasPrefix("+") {
                out.append(Diff.Ligne(genre: .ajout, texte: String(l.dropFirst()), ancien: nil, nouveau: nouveau))
                nouveau += 1
            } else if l.hasPrefix("-") {
                out.append(Diff.Ligne(genre: .retrait, texte: String(l.dropFirst()), ancien: ancien, nouveau: nil))
                ancien += 1
            } else if l.hasPrefix(" ") {
                out.append(Diff.Ligne(genre: .contexte, texte: String(l.dropFirst()), ancien: ancien, nouveau: nouveau))
                ancien += 1
                nouveau += 1
            } else if l.hasPrefix("\\") || l.isEmpty {
                continue                                                  // « \ No newline at end of file »
            } else {
                out.append(Diff.Ligne(genre: .contexte, texte: l, ancien: ancien, nouveau: nouveau))
                ancien += 1
                nouveau += 1
            }
        }
        return out
    }

    /// Chemin relatif au projet quand il y est.
    static func relatif(_ chemin: String, _ cwd: String) -> String {
        return chemin.hasPrefix(cwd + "/") ? String(chemin.dropFirst(cwd.count + 1)) : chemin
    }

    /// Texte de la confirmation du retour en arrière (`rewindBody` du web).
    static func texteRetour(_ plan: PlanRetour, _ cwd: String) -> String {
        let liste = plan.steps.map { s in
            relatif(s.path, cwd) + (s.deleted ? " (supprimé)" : "") + (s.modifieParToi ? " (modifié depuis par toi ?)" : "")
        }.joined(separator: "\n")
        let reste = plan.skipped.isEmpty ? "" : "\n\nLaissés tels quels (hors des dossiers permis) :\n" + plan.skipped.joined(separator: "\n")
        return "\(liste)\(reste)\n\nC'est définitif."
    }

    static func titreRetour(_ plan: PlanRetour) -> String {
        let n = plan.steps.count
        return "Revenir avant ce message ? (\(n) fichier\(n > 1 ? "s" : ""))"
    }

    static func texteAnnulation(_ f: FichierChange) -> String {
        return (f.kind == "created" ? "Le fichier sera supprimé (Claude l'a créé)." : "Le fichier reviendra à son état d'avant la session.") +
            " C'est définitif."
    }
}
