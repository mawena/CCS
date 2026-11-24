import Foundation

/**
 * Transport du son partagé (phase 42, `docs/audio.md` §4) : RTP/Opus (RFC 7587), sans interface,
 * partagé par l'appli (réception) et l'extension de diffusion (émission). Un paquet RTP = une
 * trame Opus, PT 96, 48 kHz, horodatage + nombre d'échantillons de la trame. On émet des trames de
 * 10 ms (+480) ; on reçoit aussi celles de 20 ms (+960) des anciens émetteurs, et toute durée
 * qu'annonce l'octet TOC d'Opus.
 */
enum Rtp {
    static let typeOpus: UInt8 = 96
    static let frequence = 48_000
    static let canaux = 2
    /// Échantillons par canal d'une trame émise : 10 ms à 48 kHz (pas de l'horodatage).
    static let echantillonsParTrame = 480
    static let dureeTrameMs = 10
    /// Trame de 20 ms des émetteurs d'avant la 1.15 (toujours acceptée en réception).
    static let echantillonsAncienneTrame = 960
    /// Plus longue durée d'un paquet Opus : 120 ms (RFC 6716).
    static let echantillonsMax = 5760
    static let portParDefaut = 4010
    static let tailleEnTete = 12

    struct EnTete: Equatable {
        var type: UInt8 = Rtp.typeOpus
        var marqueur = false
        var sequence: UInt16
        var horodatage: UInt32
        var ssrc: UInt32
    }

    /// Paquet complet : en-tête de 12 octets (V=2, P=0, X=0, CC=0) puis la trame Opus brute.
    static func paquet(_ e: EnTete, _ charge: Data) -> Data {
        var d = Data(capacity: tailleEnTete + charge.count)
        d.append(0x80)
        d.append((e.marqueur ? 0x80 : 0) | (e.type & 0x7F))
        d.append(UInt8(e.sequence >> 8)); d.append(UInt8(e.sequence & 0xFF))
        for decalage in stride(from: 24, through: 0, by: -8) { d.append(UInt8((e.horodatage >> UInt32(decalage)) & 0xFF)) }
        for decalage in stride(from: 24, through: 0, by: -8) { d.append(UInt8((e.ssrc >> UInt32(decalage)) & 0xFF)) }
        d.append(charge)
        return d
    }

    /// Lit un paquet RTP (CSRC, extension et bourrage sautés) ; nil s'il n'en est pas un.
    static func lire(_ brut: Data) -> (EnTete, Data)? {
        let o = [UInt8](brut)
        guard o.count >= tailleEnTete, o[0] >> 6 == 2 else { return nil }
        let bourrage = o[0] & 0x20 != 0
        let extension_ = o[0] & 0x10 != 0
        let csrc = Int(o[0] & 0x0F)
        var debut = tailleEnTete + 4 * csrc
        guard o.count >= debut else { return nil }
        if extension_ {
            guard o.count >= debut + 4 else { return nil }
            let mots = Int(o[debut + 2]) << 8 | Int(o[debut + 3])
            debut += 4 + 4 * mots
            guard o.count >= debut else { return nil }
        }
        var fin = o.count
        if bourrage {
            let n = Int(o[o.count - 1])
            guard n > 0, fin - n >= debut else { return nil }
            fin -= n
        }
        func mot(_ i: Int) -> UInt32 {
            return UInt32(o[i]) << 24 | UInt32(o[i + 1]) << 16 | UInt32(o[i + 2]) << 8 | UInt32(o[i + 3])
        }
        let e = EnTete(type: o[1] & 0x7F, marqueur: o[1] & 0x80 != 0,
                       sequence: UInt16(o[2]) << 8 | UInt16(o[3]), horodatage: mot(4), ssrc: mot(8))
        return (e, Data(o[debut..<fin]))
    }

    /// Écart signé de `a` à `b` en numéros de séquence 16 bits (bouclage compris) : `a - b`.
    static func ecart(_ a: UInt16, _ b: UInt16) -> Int {
        return Int(Int16(bitPattern: a &- b))
    }

    /// Nombre de canaux d'une trame Opus d'après son octet TOC (bit « s ») : 2 ou 1.
    static func canauxOpus(_ trame: Data) -> Int {
        guard let toc = trame.first else { return 0 }
        return toc & 0x04 != 0 ? 2 : 1
    }

    /// Échantillons (par canal, 48 kHz) d'un paquet Opus d'après son octet TOC (RFC 6716 §3.1) :
    /// durée de chaque trame selon la configuration, fois le nombre de trames du paquet. Nil si
    /// le paquet est vide ou incohérent.
    static func echantillonsOpus(_ paquet: Data) -> Int? {
        guard let toc = paquet.first else { return nil }
        let config = Int(toc >> 3)
        let parTrame: Int
        switch config {
        case 0..<12: parTrame = [480, 960, 1920, 2880][config % 4]   // SILK : 10, 20, 40, 60 ms
        case 12..<16: parTrame = [480, 960][config % 2]              // hybride : 10, 20 ms
        default: parTrame = [120, 240, 480, 960][config % 4]         // CELT : 2,5, 5, 10, 20 ms
        }
        let nombre: Int
        switch toc & 0x03 {
        case 0: nombre = 1
        case 1, 2: nombre = 2
        default:
            guard let m = paquet.dropFirst().first else { return nil }
            nombre = Int(m & 0x3F)
        }
        let n = parTrame * nombre
        return n > 0 && n <= echantillonsMax ? n : nil
    }
}

/// Numérote les trames à émettre : séquence +1, horodatage + échantillons de la trame (480 pour
/// 10 ms), départs et SSRC aléatoires.
struct PaqueteurRtp {
    private(set) var sequence: UInt16
    private(set) var horodatage: UInt32
    let ssrc: UInt32

    init(sequence: UInt16 = .random(in: .min ... .max), horodatage: UInt32 = .random(in: .min ... .max),
         ssrc: UInt32 = .random(in: .min ... .max)) {
        self.sequence = sequence
        self.horodatage = horodatage
        self.ssrc = ssrc
    }

    mutating func paquet(_ trame: Data, echantillons: Int = Rtp.echantillonsParTrame) -> Data {
        let d = Rtp.paquet(Rtp.EnTete(sequence: sequence, horodatage: horodatage, ssrc: ssrc), trame)
        sequence &+= 1
        horodatage &+= UInt32(max(0, echantillons))
        return d
    }
}

/**
 * Tampon de gigue du récepteur, compté en trames (réglé en millisecondes par `GigueAdaptative`) : remet les trames dans l'ordre des numéros de
 * séquence, jette les paquets en retard ou en double, signale les trous (masquage ou silence) et,
 * s'il déborde, saute les plus vieilles trames pour revenir au retard de départ.
 */
struct TamponGigue {
    enum Sortie: Equatable {
        /// Trame suivante, à décoder.
        case trame(Data)
        /// Trame perdue (trou dans les numéros) : masquage du décodeur ou silence.
        case perte
        /// Rien à jouer : remplissage au départ ou après un creux (silence).
        case attente
    }

    /// Trames d'avance avant de commencer à jouer (ex. 3 × 10 ms = 30 ms).
    private(set) var depart: Int
    /// Au-delà (ex. 7 × 10 ms = 70 ms), les plus vieilles trames sont sautées.
    private(set) var maximum: Int
    private var trames: [UInt16: Data] = [:]
    private var prochain: UInt16? = nil
    private var plusRecent: UInt16 = 0
    private(set) var joue = false
    private(set) var recues = 0
    private(set) var jetees = 0
    private(set) var perdues = 0

    init(depart: Int = 3, maximum: Int = 7) {
        self.depart = max(1, depart)
        self.maximum = max(self.depart, maximum)
    }

    /// Change le retard visé (pris en compte à la prochaine trame reçue ou jouée).
    mutating func regler(depart: Int, maximum: Int) {
        self.depart = max(1, depart)
        self.maximum = max(self.depart, maximum)
    }

    /// Trames d'avance (du prochain à jouer au plus récent reçu), trous compris.
    var avance: Int {
        guard let p = prochain, !trames.isEmpty else { return 0 }
        return Rtp.ecart(plusRecent, p) + 1
    }

    /// Range une trame reçue ; false si elle arrive trop tard ou en double.
    @discardableResult
    mutating func ajouter(sequence s: UInt16, _ trame: Data) -> Bool {
        guard let p = prochain else {
            prochain = s
            plusRecent = s
            trames[s] = trame
            recues += 1
            return true
        }
        let d = Rtp.ecart(s, p)
        if d < 0 && d > -1000 { jetees += 1; return false }          // en retard : déjà passée
        if d < 0 || d > 1000 {                                       // saut énorme : la source a redémarré
            trames = [:]
            prochain = s
            plusRecent = s
            joue = false
        }
        if trames[s] != nil { jetees += 1; return false }
        trames[s] = trame
        recues += 1
        if trames.count == 1 || Rtp.ecart(s, plusRecent) > 0 { plusRecent = s }
        // trop d'avance : on saute les plus vieilles pour revenir au retard de départ
        if avance > maximum, let q = prochain {
            let nouveau = plusRecent &- UInt16(depart - 1)
            var k = q
            while Rtp.ecart(nouveau, k) > 0 {
                if trames.removeValue(forKey: k) != nil { jetees += 1 }
                k &+= 1
            }
            prochain = nouveau
        }
        return true
    }

    /// Ce qu'il faut jouer pour la trame suivante.
    mutating func sortir() -> Sortie {
        guard let p = prochain else { return .attente }
        if !joue {
            if avance < depart { return .attente }
            joue = true
        }
        if trames.isEmpty {
            // creux : on se remet à remplir avant de rejouer
            joue = false
            return .attente
        }
        prochain = p &+ 1
        if let t = trames.removeValue(forKey: p) { return .trame(t) }
        perdues += 1
        return .perte
    }
}

/// Réglages du tampon de gigue adaptatif (`docs/audio.md` §4), en millisecondes.
enum Gigue {
    /// Retard visé au départ d'un flux.
    static let departMs = 30
    static let minimumMs = 20
    static let maximumMs = 150
    /// Montée sur incident, descente après un moment stable.
    static let pasMs = 10
    /// Au-delà du retard visé plus cette marge, les plus vieilles trames sont sautées.
    static let margeMs = 40
    /// Joué sans perte ni creux pendant 10 s : on redescend d'un pas.
    static let stableMs = 10_000
    /// Après une montée, les incidents des 500 ms suivantes ne comptent pas (une rafale = un pas).
    static let repitMs = 500
    /// Un creux plus long que 300 ms est un silence de la source, pas un tampon trop court.
    static let creuxCourtMs = 300
}

/**
 * Tampon de gigue adaptatif : démarre bas (30 ms), monte d'un pas (10 ms) à chaque perte ou creux
 * court (sous-alimentation), redescend d'un pas après 10 s stables, entre 20 et 150 ms. Compte en
 * trames selon la durée de la dernière trame reçue (10 ou 20 ms, lue dans l'octet TOC d'Opus).
 */
struct GigueAdaptative {
    private(set) var tampon = TamponGigue()
    private(set) var cibleMs: Int
    /// Échantillons (48 kHz) de la dernière trame reçue : 480 (10 ms) ou 960 (20 ms) le plus souvent.
    private(set) var echantillons = Rtp.echantillonsParTrame
    private var stableMs = 0
    private var repitMs = 0
    /// Durée du creux en cours (nil : pas de creux).
    private var creuxMs: Int? = nil

    init(cibleMs: Int = Gigue.departMs) {
        self.cibleMs = min(Gigue.maximumMs, max(Gigue.minimumMs, cibleMs))
        appliquer()
    }

    var recues: Int { return tampon.recues }
    var perdues: Int { return tampon.perdues }
    var jetees: Int { return tampon.jetees }
    /// Durée d'une trame (ms, arrondie vers le bas : 2 pour 2,5 ms).
    var dureeTrameMs: Int { return max(1, echantillons * 1000 / Rtp.frequence) }

    @discardableResult
    mutating func ajouter(sequence s: UInt16, _ trame: Data) -> Bool {
        if let n = Rtp.echantillonsOpus(trame), n != echantillons {
            echantillons = n
            appliquer()
        }
        return tampon.ajouter(sequence: s, trame)
    }

    mutating func sortir() -> TamponGigue.Sortie {
        let jouait = tampon.joue
        let s = tampon.sortir()
        let d = dureeTrameMs
        repitMs = max(0, repitMs - d)
        switch s {
        case .trame:
            if let c = creuxMs {
                creuxMs = nil
                if c <= Gigue.creuxCourtMs { incident() }
            } else {
                stableMs += d
                if stableMs >= Gigue.stableMs {
                    stableMs = 0
                    if cibleMs > Gigue.minimumMs {
                        cibleMs = max(Gigue.minimumMs, cibleMs - Gigue.pasMs)
                        appliquer()
                    }
                }
            }
        case .perte:
            incident()
        case .attente:
            if jouait && !tampon.joue { creuxMs = d } else if let c = creuxMs { creuxMs = c + d }
        }
        return s
    }

    private mutating func incident() {
        stableMs = 0
        guard repitMs == 0 else { return }
        repitMs = Gigue.repitMs
        if cibleMs < Gigue.maximumMs {
            cibleMs = min(Gigue.maximumMs, cibleMs + Gigue.pasMs)
            appliquer()
        }
    }

    private mutating func appliquer() {
        let parMs = Rtp.frequence / 1000
        func trames(_ ms: Int) -> Int { return (ms * parMs + echantillons - 1) / echantillons }
        let depart = max(1, trames(cibleMs))
        tampon.regler(depart: depart, maximum: depart + max(1, trames(Gigue.margeMs)))
    }
}

/// Échantillons bruts de ReplayKit (`.audioApp` : souvent 44,1 kHz, entiers 16 bits, parfois gros-boutiens) → flottants stéréo.
enum Pcm {
    struct Format: Equatable {
        var canaux: Int
        /// Octets par échantillon : 2 (entier 16 bits) ou 4 (flottant ou entier 32 bits).
        var octets: Int
        var flottant: Bool
        var grandBoutien: Bool
        var entrelace: Bool
    }

    /// Canal gauche et droit (un son mono est copié des deux côtés ; au-delà de 2 canaux, les deux premiers).
    static func stereo(_ tampons: [UnsafeRawBufferPointer], _ f: Format, trames n: Int) -> (gauche: [Float], droite: [Float]) {
        guard f.canaux > 0, f.octets == 2 || f.octets == 4, !tampons.isEmpty, n > 0 else { return ([], []) }
        var g = [Float](repeating: 0, count: n)
        var d = [Float](repeating: 0, count: n)
        func valeur(_ p: UnsafeRawBufferPointer, _ i: Int) -> Float {
            let o = i * f.octets
            guard o + f.octets <= p.count else { return 0 }
            if f.octets == 2 {
                var u = UInt16(p[o]) | UInt16(p[o + 1]) << 8
                if f.grandBoutien { u = u.byteSwapped }
                return Float(Int16(bitPattern: u)) / 32768
            }
            var u = UInt32(p[o]) | UInt32(p[o + 1]) << 8 | UInt32(p[o + 2]) << 16 | UInt32(p[o + 3]) << 24
            if f.grandBoutien { u = u.byteSwapped }
            return f.flottant ? Float(bitPattern: u) : Float(Int32(bitPattern: u)) / 2_147_483_648
        }
        let droit = min(1, f.canaux - 1)
        for i in 0..<n {
            if f.entrelace {
                g[i] = valeur(tampons[0], i * f.canaux)
                d[i] = valeur(tampons[0], i * f.canaux + droit)
            } else {
                g[i] = valeur(tampons[0], i)
                d[i] = valeur(tampons[min(droit, tampons.count - 1)], i)
            }
        }
        return (g, d)
    }
}
