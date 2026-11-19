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
    private static let service = "com.mawena.ccs"
    private static let compte = "identifiants"

    private static func requete() -> [String: Any] {
        return [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: compte,
        ]
    }

    static func lire() -> Identifiants? {
        var q = requete()
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var resultat: CFTypeRef?
        let statut = SecItemCopyMatching(q as CFDictionary, &resultat)
        guard statut == errSecSuccess, let donnees = resultat as? Data else { return nil }
        return try? JSONDecoder().decode(Identifiants.self, from: donnees)
    }

    static func ecrire(_ identifiants: Identifiants?) {
        SecItemDelete(requete() as CFDictionary)
        guard let i = identifiants, let donnees = try? JSONEncoder().encode(i) else { return }
        var q = requete()
        q[kSecValueData as String] = donnees
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(q as CFDictionary, nil)
    }
}
