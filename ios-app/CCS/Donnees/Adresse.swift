import Foundation

/// Adresse du serveur CCS : `https://ccs.mawena.cloud` par défaut, modifiable dans l'appli.
enum Adresse {
    static let parDefaut = "https://ccs.mawena.cloud"

    /**
     * `ccs.exemple.fr` → `https://ccs.exemple.fr`. Rend nil si l'adresse n'est pas utilisable
     * (autre schéma que http/https, pas d'hôte, identifiants dans l'adresse). Requête et fragment
     * sont retirés, ainsi que la barre finale : `https://hote/ccs/` → `https://hote/ccs`.
     */
    static func normaliser(_ texte: String) -> String? {
        var t = texte.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty || t.contains(where: { $0.isWhitespace }) { return nil }
        if !t.contains("://") { t = "https://" + t }
        guard var c = URLComponents(string: t) else { return nil }
        guard let schema = c.scheme?.lowercased(), schema == "http" || schema == "https" else { return nil }
        guard let hote = c.host, !hote.isEmpty else { return nil }
        if c.user != nil || c.password != nil { return nil }
        c.scheme = schema
        c.host = hote.lowercased()
        c.query = nil
        c.fragment = nil
        guard var s = c.string else { return nil }
        while s.hasSuffix("/") { s.removeLast() }
        return s
    }

    /// `base` + chemin de l'API (`api/ws`, `api/health`…), en gardant un éventuel préfixe.
    static func api(_ base: String, _ chemin: String) -> URL? {
        guard let b = normaliser(base) else { return nil }
        var c = chemin
        while c.hasPrefix("/") { c.removeFirst() }
        return URL(string: b + "/" + c)
    }

    /// Version du protocole du pont que parle l'appli (`docs/interfaces.md` § 2).
    static let protocole = 1

    /// Même adresse en `ws://` ou `wss://` (WebSocket) avec `?protocol=1`, relayée vers une autre
    /// machine avec `&machine=<id>` (vide : ce serveur). Sans `protocol`, le serveur nous
    /// prendrait pour un ancien client (anciens noms).
    static func ws(_ base: String, _ chemin: String, machine: String = "") -> URL? {
        guard let u = api(base, chemin), var c = URLComponents(url: u, resolvingAgainstBaseURL: false) else { return nil }
        c.scheme = c.scheme == "http" ? "ws" : "wss"
        var q = [URLQueryItem(name: "protocol", value: String(protocole))]
        if !machine.isEmpty { q.append(URLQueryItem(name: "machine", value: machine)) }
        c.queryItems = q
        return c.url
    }

    /// WebSocket de l'oreille de Jarvis (`api/jarvis/oreille?fp=<empreinte>`), jamais relayé vers
    /// une machine pilotée : le cerveau est réglé sur le serveur.
    static func oreilleJarvis(_ base: String, empreinte: String) -> URL? {
        guard let u = api(base, "api/jarvis/oreille"), var c = URLComponents(url: u, resolvingAgainstBaseURL: false) else { return nil }
        c.scheme = c.scheme == "http" ? "ws" : "wss"
        c.queryItems = [URLQueryItem(name: "fp", value: empreinte)]
        return c.url
    }

    /// Hôte d'une adresse (`ccs.mawena.cloud`), ou nil.
    static func hote(_ adresse: String) -> String? {
        return URLComponents(string: adresse)?.host?.lowercased()
    }
}
