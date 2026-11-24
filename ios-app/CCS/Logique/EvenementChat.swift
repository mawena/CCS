import Foundation

/// Commande `/…` offerte par Claude Code (Hello) : nom sans `/`, description, indice d'argument.
struct CommandeSlash: Equatable, Hashable {
    var nom: String
    var description = ""
    var indice = ""
}

/// Modèle proposé par Claude Code (Hello) : valeur, libellé, niveaux d'effort.
struct ModeleIa: Equatable {
    var valeur: String
    var libelle: String
    var efforts: [String] = []
}

/// Ligne de la liste de tâches de Claude (TodoWrite).
struct Tache: Equatable {
    var texte: String
    var statut: String
}

/// Étiquettes d'un message (`message_tags.py`).
struct EntreeEtiquettes: Equatable {
    var etiquettes: [String]
    var role = ""
    var extrait = ""
    var ts = 0.0
}

/// Mesure du contexte (`ContextUsage`).
struct MesureContexte: Equatable {
    var pourcentage: Int
    var total: Int
    var maximum: Int
    var auto: Bool
}

/**
 * Événement du chat poussé par le pont (`chat.event` → `event`), lu depuis le JSON de
 * `server/events.py` (nom de la classe Python dans `type`, ses champs à côté).
 */
enum EvChat: Equatable {
    case initial(sessionId: String, modele: String, droits: String)
    case hello(commandes: [CommandeSlash], modeles: [ModeleIa], droits: String)
    case statut(droits: String)
    case commandeLocale(texte: String)
    case delta(msgId: String, texte: String, parentId: String?)
    case texte(msgId: String, texte: String, parentId: String?)
    case reflexion(msgId: String)
    case outilLance(toolId: String, nom: String, entree: JSON, parentId: String?)
    case outilFini(toolId: String, texte: String, erreur: Bool, parentId: String?)
    case avisTache(toolId: String, statut: String, resume: String)
    case taches([Tache])
    case autorisation(requestId: String, outil: String, affiche: String, entree: JSON, description: String, agentId: String?)
    case envoye(texte: String, images: Int, nonce: String, uuid: String)
    case etiquettesChangees(sessionId: String, msgId: String, entree: EntreeEtiquettes?)
    case reglee(requestId: String, decision: String)
    case tour(ok: Bool, sousType: String, coutUsd: Double, texte: String, limite: Bool, interrompu: Bool, usage: UsageTour? = nil)
    /// Le cache a expiré : le prochain message relira `contexte` tokens au prix fort.
    case cacheExpire(contexte: Int, ttlS: Int, reecritureUsd: Double?, texte: String)
    case compacte
    /// `auto` : effacée par Claude en fin de sujet (`ccs chat clear`), pas par `/clear`.
    case reinitialise(declencheur: String)
    case note(texte: String, genre: String)
    case nouvelEssai(tentative: Int, delaiS: Double)
    case etat(String)
    case contexte(MesureContexte)
    case optionRefusee(quoi: String, erreur: String)
    case demandeInconnue(sousType: String)
    case fin(code: Int?, demande: Bool)
    case autre(String)

    /// Sous-agent qui a émis l'événement (outil Task/Agent), s'il y en a un.
    var parent: String? {
        switch self {
        case .delta(_, _, let p), .texte(_, _, let p), .outilLance(_, _, _, let p), .outilFini(_, _, _, let p):
            return p
        default:
            return nil
        }
    }

    static func lire(_ o: JSON) -> EvChat {
        let type = o.texte("type")
        let entree: JSON = (o["input"]?.objet != nil) ? (o["input"] ?? .vide) : .vide
        switch type {
        case "Init":
            return .initial(sessionId: o.texte("session_id"), modele: o.texte("model"), droits: o.texte("permission_mode"))
        case "Hello":
            return .hello(commandes: commandes(o["commands"]), modeles: modeles(o["models"]), droits: o.texte("permission_mode"))
        case "Status":
            return .statut(droits: o.texte("permission_mode"))
        case "LocalCommand":
            return .commandeLocale(texte: o.texte("text"))
        case "TextDelta":
            return .delta(msgId: o.texte("msg_id"), texte: o.texte("text"), parentId: o.texteOuNul("parent_id"))
        case "AssistantText":
            return .texte(msgId: o.texte("msg_id"), texte: o.texte("text"), parentId: o.texteOuNul("parent_id"))
        case "Thinking":
            return .reflexion(msgId: o.texte("msg_id"))
        case "ToolUse":
            return .outilLance(toolId: o.texte("tool_id"), nom: o.texte("name"), entree: entree, parentId: o.texteOuNul("parent_id"))
        case "ToolResult":
            return .outilFini(toolId: o.texte("tool_id"), texte: o.texte("text"), erreur: o.bool("is_error"), parentId: o.texteOuNul("parent_id"))
        case "TaskNotice":
            return .avisTache(toolId: o.texte("tool_id"), statut: o.texte("status"), resume: o.texte("summary"))
        case "Todos":
            return .taches(taches(o["items"]))
        case "PermissionRequest":
            return .autorisation(
                requestId: o.texte("request_id"), outil: o.texte("tool_name"), affiche: o.texte("display_name"),
                entree: entree, description: o.texte("description"), agentId: o.texteOuNul("agent_id")
            )
        case "UserSent":
            return .envoye(texte: o.texte("text"), images: o.entier("images"), nonce: o.texte("nonce"), uuid: o.texte("uuid"))
        case "TagsChanged":
            return .etiquettesChangees(sessionId: o.texte("session_id"), msgId: o.texte("msg_id"), entree: etiquettes(o["entry"]))
        case "PermissionSettled":
            return .reglee(requestId: o.texte("request_id"), decision: o.texte("decision"))
        case "TurnResult":
            return .tour(
                ok: o.bool("ok"), sousType: o.texte("subtype"), coutUsd: o.double("cost_usd"),
                texte: o.texte("text"), limite: o.bool("is_limit"), interrompu: o.bool("interrupted"),
                usage: UsageTour.lire(o["usage"])
            )
        case "CacheExpired":
            return .cacheExpire(
                contexte: o.entier("context"), ttlS: o.entier("ttl_s"), reecritureUsd: o.doubleOuNul("rewrite_usd"), texte: o.texte("text")
            )
        case "Compacted":
            return .compacte
        case "ConversationReset":
            return .reinitialise(declencheur: o.texte("trigger"))
        case "Notice":
            let g = o.texte("kind")
            return .note(texte: o.texte("text"), genre: g.isEmpty ? "info" : g)
        case "Retrying":
            return .nouvelEssai(tentative: o.entier("attempt"), delaiS: o.double("delay_s"))
        case "StateChanged":
            return .etat(o.texte("state"))
        case "ContextUsage":
            return .contexte(MesureContexte(
                pourcentage: o.entier("percentage"), total: o.entier("total"), maximum: o.entier("maximum"), auto: o.bool("auto_compact")
            ))
        case "OptionRefused":
            return .optionRefusee(quoi: o.texte("what"), erreur: o.texte("error"))
        case "UnhandledRequest":
            return .demandeInconnue(sousType: o.texte("subtype"))
        case "ProcessExited":
            return .fin(code: o.entierOuNul("code"), demande: o.bool("requested"))
        default:
            return .autre(type)
        }
    }

    private static func chaine(_ e: JSON?) -> String { return e?.contenu ?? "" }

    private static func commandes(_ e: JSON?) -> [CommandeSlash] {
        return (e?.tableau ?? []).compactMap { c in
            if let t = c.tableau {
                var n = chaine(t.first)
                if n.isEmpty { return nil }
                if n.hasPrefix("/") { n.removeFirst() }
                return CommandeSlash(nom: n, description: chaine(c[1]), indice: chaine(c[2]))
            }
            if case .chaine(var n) = c, !n.isEmpty {
                if n.hasPrefix("/") { n.removeFirst() }
                return CommandeSlash(nom: n)
            }
            return nil
        }
    }

    static func modeles(_ e: JSON?) -> [ModeleIa] {
        return (e?.tableau ?? []).compactMap { m in
            if let t = m.tableau {
                let v = chaine(t.first)
                if v.isEmpty { return nil }
                let l = chaine(m[1])
                let efforts = (m[3]?.tableau ?? []).map { chaine($0) }.filter { !$0.isEmpty }
                return ModeleIa(valeur: v, libelle: l.isEmpty ? v : l, efforts: efforts)
            }
            if case .chaine(let v) = m, !v.isEmpty { return ModeleIa(valeur: v, libelle: v) }
            return nil
        }
    }

    /// Tâches : `[contenu, statut]` (pont) ou `{content, status, activeForm}`.
    private static func taches(_ e: JSON?) -> [Tache] {
        return (e?.tableau ?? []).compactMap { t in
            if let a = t.tableau {
                let s = chaine(a.count > 1 ? a[1] : nil)
                return Tache(texte: chaine(a.first), statut: s.isEmpty ? "pending" : s)
            }
            if case .objet = t {
                let s0 = t.texte("status")
                let statut = s0.isEmpty ? "pending" : s0
                let forme = t.texte("activeForm")
                return Tache(texte: (statut == "in_progress" && !forme.isEmpty) ? forme : t.texte("content"), statut: statut)
            }
            return nil
        }
    }

    static func etiquettes(_ e: JSON?) -> EntreeEtiquettes? {
        guard let o = e, case .objet = o else { return nil }
        let tags = o.liste("tags").map { chaine($0) }.filter { !$0.isEmpty }
        if tags.isEmpty { return nil }
        return EntreeEtiquettes(etiquettes: tags, role: o.texte("role"), extrait: o.texte("excerpt"), ts: o.double("ts"))
    }
}

extension EvChat {
    /// `ConversationReset` déclenché par Claude lui-même (`ccs chat clear`).
    static func estAuto(_ declencheur: String) -> Bool { return declencheur == "ccs_auto" }
}
