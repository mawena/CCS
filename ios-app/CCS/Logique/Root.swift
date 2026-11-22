import Foundation

/**
 * Mot de passe root demandé par la machine pilotée (phase 34) : demande en cours (`root.ask`),
 * mot de passe gardé ou non (`root.status`), suivi des événements `root.*` du pont. Partie pure
 * (sans réseau ni écran), testée dans `RootTests`. Le mot de passe lui-même n'y passe jamais.
 */

/// Demande `root.ask {id, machine, command, expires_at, tries_left, error?}`.
struct DemandeRoot: Equatable, Identifiable {
    let id: String
    let machine: String
    let commande: String
    /// Fin de la demande, en secondes depuis 1970, à l'horloge de ce téléphone.
    let expire: Double
    let essais: Int
    /// Message du pont après un mauvais mot de passe.
    let erreur: String?

    /// Durée d'une demande côté pont (`ASK_TIMEOUT_S`) : sert si l'heure du serveur est faussée.
    static let dureeMax: Double = 300

    /**
     * Lit l'événement (ou le `pending` de `root.status`) ; nil sans `id`. `expires_at` est donné à
     * l'horloge du serveur : s'il est déjà passé ou trop loin (horloges décalées), la demande dure
     * `dureeMax` à partir de maintenant.
     */
    static func lire(_ j: JSON, maintenant: Double) -> DemandeRoot? {
        let id = j.texte("id")
        if id.isEmpty { return nil }
        var fin = j.double("expires_at")
        if fin <= maintenant || fin > maintenant + dureeMax + 5 { fin = maintenant + dureeMax }
        let e = j.texte("error").trimmingCharacters(in: .whitespacesAndNewlines)
        return DemandeRoot(id: id, machine: j.texte("machine"), commande: j.texte("command"),
                           expire: fin, essais: max(0, j.entier("tries_left", 3)), erreur: e.isEmpty ? nil : e)
    }

    /// Titre de la feuille : « pc-bureau demande le mot de passe root ».
    var titre: String {
        let m = machine.trimmingCharacters(in: .whitespaces)
        return (m.isEmpty ? "La machine" : m) + " demande le mot de passe root"
    }

    var texteEssais: String {
        return essais <= 1 ? "Dernier essai." : "\(essais) essais restants."
    }

    /// Secondes restantes (0 si finie).
    func restant(maintenant: Double) -> Int {
        return max(0, Int((expire - maintenant).rounded(.up)))
    }
}

/// Réponse de `root.status {}` : `{machine, kept, expires_at, remaining, pending}`.
struct EtatRoot: LisibleJSON {
    let machine: String
    let garde: Bool
    /// Secondes restantes du mot de passe gardé.
    let restant: Int
    /// Demande en attente (`pending`), à lire avec `DemandeRoot.lire`.
    let enAttente: JSON?

    init(json: JSON) {
        machine = json.texte("machine")
        garde = json.bool("kept")
        restant = max(0, json.entier("remaining"))
        if let p = json["pending"], p.objet != nil { enAttente = p } else { enAttente = nil }
    }
}

/// Événements `root.*` reçus du pont.
enum EvRoot: Equatable {
    case demande(DemandeRoot)
    case reglee(id: String, ok: Bool)
    case utilise(machine: String, commande: String)
    case oublie(machine: String, raison: String)

    static func lire(_ nom: String, _ j: JSON, maintenant: Double) -> EvRoot? {
        switch nom {
        case "root.ask": return DemandeRoot.lire(j, maintenant: maintenant).map { EvRoot.demande($0) }
        case "root.resolved":
            let id = j.texte("id")
            return id.isEmpty ? nil : .reglee(id: id, ok: j.bool("ok"))
        case "root.used": return .utilise(machine: j.texte("machine"), commande: j.texte("command"))
        case "root.forgotten": return .oublie(machine: j.texte("machine"), raison: j.texte("reason"))
        default: return nil
        }
    }
}

/// Ce que l'appli fait des événements : feuille ouverte ou fermée, mot de passe gardé, avis.
struct SuiviRoot: Equatable {
    /// Demande en cours (la feuille est montrée tant qu'elle n'est pas mise de côté).
    private(set) var demande: DemandeRoot? = nil
    /// « Plus tard » : la feuille est fermée, la demande reste (bandeau « Répondre »).
    var masquee = false
    /// Fin du mot de passe gardé (horloge du téléphone), nil s'il n'y en a pas.
    private(set) var gardeJusqua: Double? = nil
    /// Machine du gardien (dernier nom reçu).
    private(set) var machine = ""

    static let noms = ["root.ask", "root.resolved", "root.used", "root.forgotten"]

    /// La feuille doit-elle être au premier plan ?
    var aMontrer: Bool { return demande != nil && !masquee }

    /// Applique un événement ; rend l'avis discret à montrer (ou nil).
    mutating func recevoir(_ ev: EvRoot, maintenant: Double) -> String? {
        switch ev {
        case .demande(let d):
            if d.restant(maintenant: maintenant) <= 0 { return nil }
            // nouvelle demande : la feuille revient ; même demande (mauvais mot de passe) : mise à jour
            if demande?.id != d.id { masquee = false }
            demande = d
            nommer(d.machine)
            return nil
        case .reglee(let id, _):
            retirer(id)
            return nil
        case .utilise(let m, let c):
            nommer(m)
            let cmd = c.trimmingCharacters(in: .whitespacesAndNewlines)
            let nom = m.isEmpty ? "La machine" : m
            return cmd.isEmpty ? "\(nom) a lancé une commande root." : "\(nom) a lancé en root : \(cmd)"
        case .oublie(let m, let raison):
            nommer(m)
            let avait = gardeJusqua != nil
            gardeJusqua = nil
            guard avait else { return nil }
            switch raison {
            case "expired": return "Mot de passe root effacé (1 h passée)."
            case "revoke": return "Mot de passe root révoqué."
            case "stop": return "Mot de passe root effacé (pont arrêté)."
            default: return "Mot de passe root oublié."
            }
        }
    }

    /// Réponse de `root.status` (démarrage, reconnexion, retour au premier plan).
    mutating func etat(_ e: EtatRoot, maintenant: Double) {
        nommer(e.machine)
        gardeJusqua = e.garde && e.restant > 0 ? maintenant + Double(e.restant) : nil
        if let p = e.enAttente, let d = DemandeRoot.lire(p, maintenant: maintenant) {
            if demande?.id != d.id { masquee = false }
            demande = d
        } else {
            demande = nil
            masquee = false
        }
    }

    /// Demande réglée (réponse, refus, `root.resolved`) : la feuille se ferme.
    mutating func retirer(_ id: String) {
        guard demande?.id == id else { return }
        demande = nil
        masquee = false
    }

    /// `root.forget` fait depuis ce téléphone : plus de mot de passe ni de demande.
    mutating func oublie() {
        gardeJusqua = nil
        demande = nil
        masquee = false
    }

    /// Demande ou mot de passe arrivés à échéance.
    mutating func expirer(maintenant: Double) {
        if let d = demande, d.expire <= maintenant {
            demande = nil
            masquee = false
        }
        if let g = gardeJusqua, g <= maintenant { gardeJusqua = nil }
    }

    /// Prochaine échéance (pour réveiller le minuteur), ou nil.
    var prochaineEcheance: Double? {
        return [demande?.expire, gardeJusqua].compactMap { $0 }.min()
    }

    /// Minutes restantes du mot de passe gardé (arrondies au-dessus), nil s'il n'y en a pas.
    func minutesGarde(maintenant: Double) -> Int? {
        guard let g = gardeJusqua, g > maintenant else { return nil }
        return max(1, Int(((g - maintenant) / 60).rounded(.up)))
    }

    /// Autre machine pilotée, déconnexion : tout est oublié.
    mutating func vider() {
        self = SuiviRoot()
    }

    private mutating func nommer(_ m: String) {
        let t = m.trimmingCharacters(in: .whitespaces)
        if !t.isEmpty { machine = t }
    }
}

/// Texte d'un compte à rebours (« 4:05 »).
func texteMinutesSecondes(_ s: Int) -> String {
    let v = max(0, s)
    return "\(v / 60):" + String(format: "%02d", v % 60)
}
