import Foundation

/**
 * Valeur JSON libre : trames du WebSocket, événements du pont, paramètres des appels. Les modèles
 * se lisent depuis cette valeur avec des défauts partout (champ absent, nul ou d'un autre type :
 * valeur par défaut), comme `ignoreUnknownKeys` + `coerceInputValues` du client Android.
 */
enum JSON: Equatable {
    case nul
    case booleen(Bool)
    case nombre(Double)
    case chaine(String)
    case tableau([JSON])
    case objet([String: JSON])

    static let vide: JSON = .objet([:])

    // MARK: lecture

    /// Texte JSON → valeur ; nil s'il est illisible.
    static func lire(_ texte: String) -> JSON? {
        guard let donnees = texte.data(using: .utf8) else { return nil }
        return lire(donnees)
    }

    static func lire(_ donnees: Data) -> JSON? {
        return try? JSONDecoder().decode(JSON.self, from: donnees)
    }

    subscript(cle: String) -> JSON? {
        if case .objet(let o) = self { return o[cle] }
        return nil
    }

    subscript(index: Int) -> JSON? {
        if case .tableau(let t) = self, index >= 0, index < t.count { return t[index] }
        return nil
    }

    var chaine: String? {
        if case .chaine(let s) = self { return s }
        return nil
    }

    var nombre: Double? {
        if case .nombre(let n) = self { return n }
        return nil
    }

    var booleen: Bool? {
        if case .booleen(let b) = self { return b }
        return nil
    }

    var tableau: [JSON]? {
        if case .tableau(let t) = self { return t }
        return nil
    }

    var objet: [String: JSON]? {
        if case .objet(let o) = self { return o }
        return nil
    }

    var estNul: Bool {
        if case .nul = self { return true }
        return false
    }

    /// Contenu d'une valeur simple en texte (chaîne telle quelle, nombre, booléen) ; nil sinon.
    var contenu: String? {
        switch self {
        case .chaine(let s): return s
        case .nombre(let n): return JSON.texteNombre(n)
        case .booleen(let b): return b ? "true" : "false"
        default: return nil
        }
    }

    /// Champ texte d'un objet (« » s'il manque) ; nombres et booléens donnés en texte.
    func texte(_ cle: String) -> String { return self[cle]?.contenu ?? "" }

    /// Champ texte d'un objet, ou nil s'il manque ou est nul.
    func texteOuNul(_ cle: String) -> String? { return self[cle]?.contenu }

    func bool(_ cle: String, _ defaut: Bool = false) -> Bool { return self[cle]?.booleen ?? defaut }

    func double(_ cle: String, _ defaut: Double = 0) -> Double { return self[cle]?.nombre ?? defaut }

    func doubleOuNul(_ cle: String) -> Double? { return self[cle]?.nombre }

    func entier(_ cle: String, _ defaut: Int = 0) -> Int {
        guard let n = self[cle]?.nombre, n.isFinite, abs(n) < 9e15 else { return defaut }
        return Int(n)
    }

    func entierOuNul(_ cle: String) -> Int? {
        guard let n = self[cle]?.nombre, n.isFinite, abs(n) < 9e15 else { return nil }
        return Int(n)
    }

    func liste(_ cle: String) -> [JSON] { return self[cle]?.tableau ?? [] }

    func listeTextes(_ cle: String) -> [String] { return liste(cle).compactMap { $0.contenu } }

    // MARK: écriture

    /// Texte JSON compact (clés triées : sortie stable).
    var texteCompact: String {
        var s = ""
        JSON.ecrire(self, dans: &s, retrait: nil, niveau: 0)
        return s
    }

    /// Texte JSON lisible (retrait de 2 espaces), pour les paramètres d'un outil.
    var texteJoli: String {
        var s = ""
        JSON.ecrire(self, dans: &s, retrait: "  ", niveau: 0)
        return s
    }

    static func texteNombre(_ n: Double) -> String {
        if !n.isFinite { return "null" }
        if n == n.rounded(), abs(n) < 1e15 { return String(Int64(n)) }
        return String(n)
    }

    private static func ecrire(_ v: JSON, dans s: inout String, retrait: String?, niveau: Int) {
        switch v {
        case .nul: s += "null"
        case .booleen(let b): s += b ? "true" : "false"
        case .nombre(let n): s += texteNombre(n)
        case .chaine(let t): echapper(t, dans: &s)
        case .tableau(let t):
            if t.isEmpty { s += "[]"; return }
            s += "["
            for (i, e) in t.enumerated() {
                if i > 0 { s += "," }
                if let r = retrait { s += "\n" + String(repeating: r, count: niveau + 1) }
                ecrire(e, dans: &s, retrait: retrait, niveau: niveau + 1)
            }
            if let r = retrait { s += "\n" + String(repeating: r, count: niveau) }
            s += "]"
        case .objet(let o):
            if o.isEmpty { s += "{}"; return }
            s += "{"
            for (i, cle) in o.keys.sorted().enumerated() {
                if i > 0 { s += "," }
                if let r = retrait { s += "\n" + String(repeating: r, count: niveau + 1) }
                echapper(cle, dans: &s)
                s += retrait == nil ? ":" : ": "
                ecrire(o[cle] ?? .nul, dans: &s, retrait: retrait, niveau: niveau + 1)
            }
            if let r = retrait { s += "\n" + String(repeating: r, count: niveau) }
            s += "}"
        }
    }

    private static func echapper(_ t: String, dans s: inout String) {
        s += "\""
        for u in t.unicodeScalars {
            switch u {
            case "\"": s += "\\\""
            case "\\": s += "\\\\"
            case "\n": s += "\\n"
            case "\r": s += "\\r"
            case "\t": s += "\\t"
            default:
                if u.value < 0x20 {
                    s += String(format: "\\u%04x", u.value)
                } else {
                    s.unicodeScalars.append(u)
                }
            }
        }
        s += "\""
    }
}

extension JSON: Decodable {
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() {
            self = .nul
        } else if let b = try? c.decode(Bool.self) {
            self = .booleen(b)
        } else if let n = try? c.decode(Double.self) {
            self = .nombre(n)
        } else if let s = try? c.decode(String.self) {
            self = .chaine(s)
        } else if let t = try? c.decode([JSON].self) {
            self = .tableau(t)
        } else if let o = try? c.decode([String: JSON].self) {
            self = .objet(o)
        } else {
            throw DecodingError.dataCorruptedError(in: c, debugDescription: "valeur JSON inconnue")
        }
    }
}

// Écriture commode des paramètres : ["path": "x", "limit": 20, "git": true]
extension JSON: ExpressibleByStringLiteral, ExpressibleByIntegerLiteral, ExpressibleByFloatLiteral,
    ExpressibleByBooleanLiteral, ExpressibleByArrayLiteral, ExpressibleByDictionaryLiteral {
    init(stringLiteral value: String) { self = .chaine(value) }
    init(integerLiteral value: Int) { self = .nombre(Double(value)) }
    init(floatLiteral value: Double) { self = .nombre(value) }
    init(booleanLiteral value: Bool) { self = .booleen(value) }
    init(arrayLiteral elements: JSON...) { self = .tableau(elements) }
    init(dictionaryLiteral elements: (String, JSON)...) {
        var o: [String: JSON] = [:]
        for (k, v) in elements { o[k] = v }
        self = .objet(o)
    }
}

extension JSON {
    /// Chaîne facultative : `.nul` si elle manque.
    static func de(_ s: String?) -> JSON { return s.map { JSON.chaine($0) } ?? .nul }
    static func de(_ n: Int) -> JSON { return .nombre(Double(n)) }
    static func de(_ n: Double?) -> JSON { return n.map { JSON.nombre($0) } ?? .nul }
    static func de(_ b: Bool) -> JSON { return .booleen(b) }
    static func de(_ t: [String]) -> JSON { return .tableau(t.map { JSON.chaine($0) }) }
}
