import Foundation

/**
 * Oreille « bouton » de Jarvis (assistant vocal, projet voisin), sans UI ni son : adresse
 * d'appairage, messages du protocole des oreilles (crates/jarvis-protocol), trames de son,
 * rééchantillonnage vers 16 kHz, phrase en cours. Même logique que la version web
 * (`ccs_app/web/jarvis-ear.js`) ; le lien passe par le relais de CCS (`/api/jarvis/oreille`).
 */
enum Jarvis {
    static let frequence = 16_000
    /// Échantillons au plus par trame (1 s, `frame.rs`).
    static let maxEchantillonsTrame = 16_000
    /// Une trame toutes les 100 ms.
    static let echantillonsParTrame = 1_600
    /// Son d'une phrase au plus (14 s).
    static let maxPhrase = 14 * 16_000
    /// Fermeture du relais : Jarvis injoignable ou lien rompu.
    static let fermetureInjoignable = 4011
    /// Niveau (RMS, échantillons entre -1 et 1) au-dessus duquel on parle.
    static let seuilParole: Float = 0.02
    /// Mode « appui court » : fin après ce silence (ms), ou si rien n'est dit en 6 s.
    static let silenceFinMs: Double = 1_200
    static let sansParoleMax = 6 * 16_000
    /// Lien fermé après 2 min sans phrase.
    static let inactiviteS: UInt64 = 120

    static func maintenantMs() -> Double { return Date().timeIntervalSince1970 * 1000 }

    // MARK: appairage

    /// Empreinte du certificat du cerveau : base64url sans remplissage, 43 caractères.
    static func empreinteValide(_ s: String) -> Bool {
        return s.count == 43 && s.unicodeScalars.allSatisfy { c in
            (c.value < 128 && CharacterSet.alphanumerics.contains(c)) || c == "-" || c == "_"
        }
    }

    static func codeValide(_ s: String) -> Bool {
        return s.count == 6 && s.unicodeScalars.allSatisfy { $0.value >= 48 && $0.value <= 57 }
    }

    private static let prefixe = "jarvis://pair?"
    private static let guillemets: Set<Character> = ["\"", "'", "«", "»", "“", "”", "`", "<", ">"]

    /// Saisie collée : première ligne non vide, sans espaces ni guillemets autour.
    static func nettoyer(_ brut: String) -> String {
        let ligne = brut.split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .first { !$0.isEmpty } ?? ""
        var t = Substring(ligne)
        while let c = t.first, c.isWhitespace || guillemets.contains(c) { t.removeFirst() }
        while let c = t.last, c.isWhitespace || guillemets.contains(c) { t.removeLast() }
        return String(t)
    }

    /// `jarvis://pair?v=1&id=…&h=…&p=7341&fp=…&c=482913` (crates/jarvis-protocol/src/pairing_uri.rs).
    static func lireAdresse(_ texte: String) throws -> CibleAppairage {
        let s = nettoyer(texte)
        guard s.hasPrefix(prefixe) else {
            throw ErreurJarvis("Ce n'est pas une adresse d'appairage Jarvis (jarvis://pair?…).")
        }
        var params: [String: String] = [:]
        for kv in s.dropFirst(prefixe.count).split(separator: "&", omittingEmptySubsequences: false) {
            guard let i = kv.firstIndex(of: "=") else { throw ErreurJarvis("Adresse d'appairage mal formée.") }
            let cle = String(kv[kv.startIndex..<i])
            if params[cle] != nil { throw ErreurJarvis("Adresse d'appairage mal formée.") }
            params[cle] = String(kv[kv.index(after: i)...])
        }
        guard params["v"] == "1" else { throw ErreurJarvis("Version d'appairage inconnue : mets Jarvis à jour.") }
        let empreinte = params["fp"] ?? ""
        let code = params["c"] ?? ""
        guard empreinteValide(empreinte) else { throw ErreurJarvis("Empreinte du cerveau invalide dans l'adresse.") }
        guard codeValide(code) else { throw ErreurJarvis("Code d'appairage invalide dans l'adresse.") }
        return CibleAppairage(code: code, empreinte: empreinte, cerveau: params["id"] ?? "", port: Int(params["p"] ?? "") ?? 0)
    }

    // MARK: messages de l'oreille

    static func hello(_ a: AppairageJarvis) -> String {
        return JSON.objet(["type": "hello", "version": 1, "ear_id": .chaine(a.earId), "token": .chaine(a.token)]).texteCompact
    }

    static func pair(code: String, nom: String) -> String {
        return JSON.objet([
            "type": "pair", "version": 1, "code": .chaine(code), "name": .chaine(String(nom.prefix(60))), "platform": "ios",
        ]).texteCompact
    }

    static func wake(_ phrase: UInt32) -> String {
        return JSON.objet([
            "type": "wake", "utterance": .nombre(Double(phrase)), "score": 2.0, "level_db": 0, "muted": false,
        ]).texteCompact
    }

    /// Réponse à une question de Jarvis (`await_reply`), sans mot d'éveil.
    static func listenStart(_ phrase: UInt32) -> String {
        return JSON.objet(["type": "listen_start", "utterance": .nombre(Double(phrase))]).texteCompact
    }

    static func listenEnd(_ phrase: UInt32, sansParole: Bool) -> String {
        return JSON.objet([
            "type": "listen_end", "utterance": .nombre(Double(phrase)), "muted": false,
            "no_speech": .booleen(sansParole), "cut": .nul,
        ]).texteCompact
    }

    // MARK: messages du cerveau (et du relais)

    static func lire(_ texte: String) -> MessageCerveau {
        guard let m = JSON.lire(texte) else { return .autre }
        let phrase = UInt32(clamping: m.entier("utterance"))
        switch m.texte("type") {
        case "welcome":
            return .bienvenue(nom: m.texte("brain_name"))
        case "paired":
            return .appaire(earId: m.texte("ear_id"), jeton: m.texte("token"), cerveauId: m.texte("brain_id"), nom: m.texte("brain_name"))
        case "rejected":
            let r = m["reason"] ?? .vide
            return .refus(motif: r.texte("kind"), essais: r.entierOuNul("attempts_left"))
        case "elected":
            return .elu(phrase)
        case "stop":
            return .stop(phrase)
        case "relay_error":
            return .relais(m.texte("message"))
        case "response":
            let r = m["response"] ?? .vide
            switch r.texte("type") {
            case "heard":
                var voix: VoixJarvis? = nil
                if let a = r["audio"], !a.texte("pcm").isEmpty {
                    voix = VoixJarvis(pcm: a.texte("pcm"), frequence: a.entier("sample_rate", 22_050))
                }
                return .entendu(texte: r.texte("text"), voix: r.texte("speech"), audio: voix,
                                attendReponse: r.texte("ear_action") == "await_reply")
            case "reply":
                return .reponse(r.texte("speech"))
            case "error":
                let t = r.texte("message")
                return .erreur(t.isEmpty ? "Erreur de Jarvis." : t)
            default:
                return .autre
            }
        default:
            return .autre
        }
    }

    /// Refus du cerveau (`rejected`), lisible.
    static func texteRefus(_ motif: String, essais: Int?) -> String {
        var t: String
        switch motif {
        case "unknown_ear": t = "Ce téléphone n'est plus appairé (retiré par « jarvis unpair » ?). Refais l'appairage."
        case "bad_token": t = "Jeton refusé par Jarvis : refais l'appairage."
        case "version": t = "Version du protocole refusée : mets CCS ou Jarvis à jour."
        case "pairing_closed": t = "Pas de fenêtre d'appairage ouverte : lance « jarvis pair » sur la machine de Jarvis."
        case "wrong_code": t = "Code d'appairage faux."
        default: t = "Jarvis a refusé la connexion."
        }
        if motif == "wrong_code", let n = essais { t += " Essais restants : \(n)." }
        return t
    }

    /// Fermeture du lien par le relais : code WebSocket, dernier `relay_error`, raison de la fermeture.
    static func texteFermeture(code: Int, relais: String?, raison: String) -> String {
        let detail = (relais?.isEmpty == false ? relais : nil) ?? (raison.trimmingCharacters(in: .whitespaces).isEmpty ? nil : raison)
        switch code {
        case fermetureInjoignable: return "Jarvis est injoignable" + (detail.map { " : \($0)" } ?? ".")
        case 4001: return "Session CCS terminée : reconnecte l'appli."
        case 1011, 1012: return detail ?? "Pont CCS injoignable."
        default: return detail ?? "Connexion au relais de Jarvis perdue."
        }
    }

    // MARK: son

    /// Trame de son du micro : `0x01` + phrase u32 LE + échantillons i16 LE (`frame.rs`).
    static func trameMicro(_ phrase: UInt32, _ echantillons: ArraySlice<Int16>) -> Data {
        var d = Data(capacity: 5 + 2 * echantillons.count)
        d.append(1)
        withUnsafeBytes(of: phrase.littleEndian) { d.append(contentsOf: $0) }
        for e in echantillons { withUnsafeBytes(of: e.littleEndian) { d.append(contentsOf: $0) } }
        return d
    }

    /// Voix de Jarvis : PCM i16 LE mono en base64 → échantillons.
    static func decoderPcm(_ b64: String) -> [Int16] {
        guard let d = Data(base64Encoded: b64) else { return [] }
        let octets = [UInt8](d)
        var out = [Int16](repeating: 0, count: octets.count / 2)
        for i in 0..<out.count {
            out[i] = Int16(bitPattern: UInt16(octets[2 * i]) | (UInt16(octets[2 * i + 1]) << 8))
        }
        return out
    }

    /// Fichier WAV (PCM 16 bits mono) en mémoire, pour `AVAudioPlayer`.
    static func wav(_ pcm: [Int16], frequence f: Int) -> Data {
        var d = Data(capacity: 44 + 2 * pcm.count)
        func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        let taille = UInt32(2 * pcm.count)
        d.append(contentsOf: Array("RIFF".utf8)); u32(36 + taille)
        d.append(contentsOf: Array("WAVE".utf8))
        d.append(contentsOf: Array("fmt ".utf8)); u32(16); u16(1); u16(1)
        u32(UInt32(f)); u32(UInt32(f * 2)); u16(2); u16(16)
        d.append(contentsOf: Array("data".utf8)); u32(taille)
        for e in pcm { withUnsafeBytes(of: e.littleEndian) { d.append(contentsOf: $0) } }
        return d
    }

    static func rms(_ morceau: [Float]) -> Float {
        guard !morceau.isEmpty else { return 0 }
        var s: Float = 0
        for x in morceau { s += x * x }
        return (s / Float(morceau.count)).squareRoot()
    }
}

/// Erreur lisible telle quelle ; `refus` : motif du refus du cerveau (`unknown_ear`, `bad_token`…).
struct ErreurJarvis: LocalizedError, Equatable {
    let message: String
    var refus: String? = nil

    init(_ message: String, refus: String? = nil) {
        self.message = message
        self.refus = refus
    }

    var errorDescription: String? { return message }
}

/// Appairage gardé dans le trousseau : identifiant d'oreille, jeton, empreinte du cerveau.
struct AppairageJarvis: Codable, Equatable {
    var earId: String
    var token: String
    var fingerprint: String
    var brainName: String
    var brainId: String
}

/// Ce que donne une adresse d'appairage (ou la saisie à la main).
struct CibleAppairage: Equatable {
    var code: String
    var empreinte: String
    var cerveau: String = ""
    var port: Int = 0
}

struct VoixJarvis: Equatable {
    var pcm: String
    var frequence: Int
}

enum MessageCerveau: Equatable {
    case bienvenue(nom: String)
    case appaire(earId: String, jeton: String, cerveauId: String, nom: String)
    case refus(motif: String, essais: Int?)
    case elu(UInt32)
    case stop(UInt32)
    case entendu(texte: String, voix: String, audio: VoixJarvis?, attendReponse: Bool)
    case reponse(String)
    case erreur(String)
    /// Message du relais de CCS avant sa fermeture (Jarvis injoignable…).
    case relais(String)
    case autre
}

/**
 * Rééchantillonnage vers 16 kHz par moyenne glissante (filtre suffisant pour la voix), en i16 ;
 * l'état est gardé d'un morceau à l'autre. Utilisé sur le fil du micro seulement.
 */
final class Reechantillonneur {
    private let pas: Double
    private var pos: Double
    private var somme: Float = 0
    private var n = 0

    init(frequence: Double) {
        pas = frequence / Double(Jarvis.frequence)
        pos = 0
    }

    func pousser(_ entree: [Float]) -> [Int16] {
        var out: [Int16] = []
        out.reserveCapacity(Int(Double(entree.count) / pas) + 1)
        for i in 0..<entree.count {
            somme += entree[i]
            n += 1
            if Double(i + 1) >= pos + pas {
                let v = max(-1, min(1, somme / Float(n)))
                out.append(Int16(v < 0 ? (v * 32768).rounded() : (v * 32767).rounded()))
                somme = 0
                n = 0
                pos += pas
            }
        }
        pos -= Double(entree.count)
        return out
    }
}

/**
 * Une phrase : son du micro en attente du lien, décisions d'arrêt (14 s, silence en mode « appui
 * court », rien dit en 6 s), découpage en trames.
 */
struct PhraseJarvis {
    let numero: UInt32
    /// Fin au silence (appui court, réponse attendue) ; sinon au relâché.
    var auto: Bool
    /// Réponse à une question de Jarvis : `listen_start` au lieu de `wake`.
    let suite: Bool
    /// Lien ouvert et `wake` envoyé : le son peut partir.
    var prete = false
    /// Micro coupé : il ne reste qu'à envoyer `listen_end`.
    var finie = false
    private(set) var tampon: [Int16] = []
    private(set) var total = 0
    private(set) var parle = false
    private var dernierSon: Double

    init(numero: UInt32, auto: Bool, suite: Bool = false, maintenant: Double) {
        self.numero = numero
        self.auto = auto
        self.suite = suite
        dernierSon = maintenant
    }

    /// Ajoute un morceau du micro (déjà en 16 kHz) ; rend true s'il faut arrêter la phrase.
    mutating func ajouter(_ e: [Int16], fort: Bool, maintenant: Double) -> Bool {
        if fort {
            parle = true
            dernierSon = maintenant
        }
        let pris = e.prefix(max(0, Jarvis.maxPhrase - total))
        total += pris.count
        tampon.append(contentsOf: pris)
        if total >= Jarvis.maxPhrase { return true }
        if auto && parle && maintenant - dernierSon > Jarvis.silenceFinMs { return true }
        if auto && !parle && total > Jarvis.sansParoleMax { return true }
        return false
    }

    /// Trames prêtes à partir (`toutes` : vide le tampon) ; rien tant que le lien n'est pas prêt.
    mutating func trames(toutes: Bool) -> [Data] {
        guard prete else { return [] }
        var out: [Data] = []
        while tampon.count >= Jarvis.echantillonsParTrame || (toutes && !tampon.isEmpty) {
            let n = min(Jarvis.maxEchantillonsTrame, toutes ? tampon.count : Jarvis.echantillonsParTrame)
            out.append(Jarvis.trameMicro(numero, tampon[0..<n]))
            tampon.removeFirst(n)
        }
        return out
    }

    /// Rien d'utile : pas de voix, ou moins de 0,3 s.
    var sansParole: Bool { return !parle || total < Jarvis.frequence * 3 / 10 }
}
