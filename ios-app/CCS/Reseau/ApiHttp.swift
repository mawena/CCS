import Foundation

/// Erreur d'une route HTTP, avec un message pour l'utilisateur.
struct ErreurHttp: Error, LocalizedError {
    let message: String
    var errorDescription: String? { return message }
}

/// Routes HTTP de `ccs-web` (hors WebSocket).
enum ApiHttp {
    private static let session: URLSession = {
        let c = URLSessionConfiguration.default
        c.timeoutIntervalForRequest = 20
        c.httpShouldSetCookies = false
        return URLSession(configuration: c)
    }()

    private static func requete(_ base: String, _ chemin: String, _ i: Identifiants? = nil) throws -> URLRequest {
        guard let url = Adresse.api(base, chemin) else { throw ErreurHttp(message: "Adresse du serveur invalide.") }
        var r = URLRequest(url: url)
        i?.authentifier(&r)
        return r
    }

    private static func corpsJson(_ r: inout URLRequest, _ corps: [String: JSON]) {
        r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = Data(JSON.objet(corps).texteCompact.utf8)
    }

    private static func executer(_ r: URLRequest) async throws -> (Int, Data) {
        do {
            let (donnees, reponse) = try await session.data(for: r)
            let code = (reponse as? HTTPURLResponse)?.statusCode ?? 0
            return (code, donnees)
        } catch {
            throw ErreurHttp(message: "Serveur injoignable.")
        }
    }

    private static func obtenir<T: LisibleJSON>(_ base: String, _ chemin: String, _ type: T.Type) async throws -> T {
        let (code, donnees) = try await executer(try requete(base, chemin))
        guard (200..<300).contains(code) else { throw ErreurHttp(message: "Erreur \(code)") }
        return T(json: JSON.lire(donnees) ?? .vide)
    }

    static func sante(_ base: String) async throws -> Sante {
        return try await obtenir(base, "api/health", Sante.self)
    }

    static func portier(_ base: String) async throws -> InfoPortier {
        return try await obtenir(base, "api/portier", InfoPortier.self)
    }

    /// Utilisateur reconnu avec ces identifiants, ou nil si le serveur les refuse (401).
    static func session(_ i: Identifiants) async throws -> InfoSession? {
        let (code, donnees) = try await executer(try requete(i.serveur, "api/session", i))
        if code == 401 { return nil }
        guard (200..<300).contains(code) else { throw ErreurHttp(message: "Erreur \(code)") }
        return InfoSession(json: JSON.lire(donnees) ?? .vide)
    }

    /**
     * Jeton d'appareil durable pour une connexion par Portier (`POST /api/app-token`). Nil si le
     * serveur ne connaît pas encore la route (404) ou refuse : on garde alors les cookies.
     */
    static func jetonAppli(_ i: Identifiants, nom: String) async -> String? {
        guard var r = try? requete(i.serveur, "api/app-token", i) else { return nil }
        corpsJson(&r, ["name": .chaine(String(nom.prefix(60)))])
        guard let res = try? await executer(r), (200..<300).contains(res.0) else { return nil }
        let t = JSON.lire(res.1)?.texteOuNul("token")
        return (t?.isEmpty ?? true) ? nil : t
    }

    /// Accès connectés au compte (`/api/tokens`) ; nil si le serveur refuse cette connexion (401).
    static func acces(_ i: Identifiants) async throws -> ListeAcces? {
        let (code, donnees) = try await executer(try requete(i.serveur, "api/tokens", i))
        if code == 401 { return nil }
        guard (200..<300).contains(code) else { throw ErreurHttp(message: "Erreur \(code)") }
        return ListeAcces(json: JSON.lire(donnees) ?? .vide)
    }

    /// Révoque un accès (`/api/revoke`) ; rend nil si c'est fait, sinon le message à montrer.
    static func revoquer(_ i: Identifiants, id: String) async -> String? {
        guard var r = try? requete(i.serveur, "api/revoke", i) else { return "Adresse du serveur invalide." }
        corpsJson(&r, ["token_id": .chaine(id)])
        guard let res = try? await executer(r) else { return "Serveur injoignable." }
        let (code, donnees) = res
        if code == 401 { return "Le serveur ne reconnaît pas cette connexion pour gérer les accès." }
        guard (200..<300).contains(code) else { return "Erreur \(code)" }
        return JSON.lire(donnees)?.bool("revoked") == true ? nil : "Révocation impossible : cet accès n'existe plus."
    }

    /// Appairage : identifiant, mot de passe Ubuntu et code → jeton d'appareil (`status` = `ok`).
    static func appairer(_ base: String, utilisateur: String, motDePasse: String, code: String, nom: String) async -> ReponseConnexion {
        return await poster(base, "api/pair", [
            "user": .chaine(utilisateur), "password": .chaine(motDePasse), "code": .chaine(code), "name": .chaine(nom),
        ])
    }

    /// Première connexion : premier code du secret reçu → jeton d'appareil.
    static func inscrire(_ base: String, enAttente: String, code: String) async -> ReponseConnexion {
        return await poster(base, "api/enroll", ["pending": .chaine(enAttente), "code": .chaine(code)])
    }

    private static func poster(_ base: String, _ chemin: String, _ corps: [String: JSON]) async -> ReponseConnexion {
        guard var r = try? requete(base, chemin) else { return ReponseConnexion(status: "error", message: "Adresse du serveur invalide.") }
        corpsJson(&r, corps)
        do {
            let (code, donnees) = try await executer(r)
            return lireReponse(code, String(data: donnees, encoding: .utf8) ?? "")
        } catch {
            return ReponseConnexion(status: "error", message: "Serveur injoignable.")
        }
    }

    /// Réponse de `/api/pair` ou `/api/enroll` d'après le code HTTP et le corps.
    static func lireReponse(_ code: Int, _ corps: String) -> ReponseConnexion {
        switch code {
        case 200..<300:
            guard let j = JSON.lire(corps), case .objet = j else {
                return ReponseConnexion(status: "error", message: "Réponse illisible du serveur.")
            }
            return ReponseConnexion(json: j)
        case 401:
            let t = corps.trimmingCharacters(in: .whitespacesAndNewlines)
            return ReponseConnexion(status: "refused", message: t.isEmpty ? "Connexion refusée." : t)
        case 503:
            return ReponseConnexion(status: "error", message: "Service de connexion indisponible.")
        default:
            return ReponseConnexion(status: "error", message: "Erreur \(code)")
        }
    }
}
