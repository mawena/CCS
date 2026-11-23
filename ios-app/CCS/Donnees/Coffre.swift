import Foundation
import Security

/**
 * Ce qui ouvre le WebSocket. Mode normal : `jeton` d'appareil (appairage par `/api/pair`), envoyé en
 * `Authorization: Bearer`. Mode Portier : `cookies` de Portier récupérés après la connexion dans la
 * vue web, envoyés tels quels en en-tête `Cookie`.
 */
struct Identifiants: Codable, Equatable {
    var serveur: String
    var utilisateur: String
    var jeton: String?
    var cookies: String?

    init(serveur: String, utilisateur: String, jeton: String? = nil, cookies: String? = nil) {
        self.serveur = serveur
        self.utilisateur = utilisateur
        self.jeton = jeton
        self.cookies = cookies
    }

    /// Connecté par Portier sans jeton d'appareil (cookies seuls).
    var portier: Bool { return jeton == nil && cookies != nil }

    /// Connecté par Portier (avec ou sans jeton d'appareil obtenu ensuite).
    var viaPortier: Bool { return cookies != nil }

    /// Ajoute l'authentification à une requête : jeton en Bearer, cookies de Portier, ou les deux.
    func authentifier(_ r: inout URLRequest) {
        if let j = jeton { r.setValue("Bearer " + j, forHTTPHeaderField: "Authorization") }
        if let c = cookies {
            r.httpShouldHandleCookies = false
            r.setValue(c, forHTTPHeaderField: "Cookie")
        }
    }
}

/// Identifiants gardés dans le trousseau d'iOS (élément « mot de passe générique »). Illisibles = absents.
enum Coffre {
    static func lire() -> Identifiants? { return Trousseau.lire("identifiants") }

    static func ecrire(_ identifiants: Identifiants?) { Trousseau.ecrire("identifiants", identifiants) }
}

/// Appairage de l'oreille de Jarvis (identifiant d'oreille, jeton, empreinte du cerveau), à part.
enum CoffreJarvis {
    static func lire() -> AppairageJarvis? { return Trousseau.lire("jarvis") }

    static func ecrire(_ appairage: AppairageJarvis?) { Trousseau.ecrire("jarvis", appairage) }
}

/// Valeurs JSON dans le trousseau, une par compte, propres à ce téléphone (non synchronisées).
enum Trousseau {
    private static let service = "com.mawena.ccs"

    private static func requete(_ compte: String) -> [String: Any] {
        return [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: compte,
        ]
    }

    static func lire<T: Decodable>(_ compte: String) -> T? {
        var q = requete(compte)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var resultat: CFTypeRef?
        let statut = SecItemCopyMatching(q as CFDictionary, &resultat)
        guard statut == errSecSuccess, let donnees = resultat as? Data else { return nil }
        return try? JSONDecoder().decode(T.self, from: donnees)
    }

    static func ecrire<T: Encodable>(_ compte: String, _ valeur: T?) {
        SecItemDelete(requete(compte) as CFDictionary)
        guard let v = valeur, let donnees = try? JSONEncoder().encode(v) else { return }
        var q = requete(compte)
        q[kSecValueData as String] = donnees
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(q as CFDictionary, nil)
    }
}
