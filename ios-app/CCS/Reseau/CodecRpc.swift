import Foundation

/**
 * Messages du WebSocket `/api/ws` (voir `ccs_app/server/web.py`), une trame texte JSON chacun :
 * - appel :     `{"id": 7, "method": "accounts.cards", "params": {…}}`
 * - réponse :   `{"id": 7, "result": {…}}` ou `{"id": 7, "error": {"code": "…", "message": "…"}}`
 * - événement : `{"event": "chat.tags", "data": {…}}` (poussé par le pont, sans id)
 */
enum MessageRpc: Equatable {
    case resultat(id: Int, resultat: JSON)
    case echec(id: Int?, code: String, message: String)
    case evenement(nom: String, donnees: JSON)
}

/// Erreur d'un appel : code du serveur (`introuvable`, `refuse`…) ou du client (`hors_ligne`, `delai`).
struct RpcErreur: Error, LocalizedError, Equatable {
    let code: String
    let message: String

    init(_ code: String, _ message: String) {
        self.code = code
        self.message = message
    }

    var errorDescription: String? { return message }
}

enum CodecRpc {
    static func requete(id: Int, methode: String, params: [String: JSON] = [:]) -> String {
        let o: JSON = .objet(["id": .nombre(Double(id)), "method": .chaine(methode), "params": .objet(params)])
        return o.texteCompact
    }

    /// Trame reçue → message ; nil si elle n'est pas comprise (ignorée, comme le fait le web).
    static func decoder(_ texte: String) -> MessageRpc? {
        guard let j = JSON.lire(texte), case .objet(let obj) = j else { return nil }
        if let ev = obj["event"]?.chaine {
            let donnees: JSON
            if let d = obj["data"], case .objet = d { donnees = d } else { donnees = .vide }
            return .evenement(nom: ev, donnees: donnees)
        }
        var id: Int? = nil
        if let n = obj["id"]?.nombre, n.isFinite, n == n.rounded() { id = Int(n) }
        if let erreur = obj["error"], !erreur.estNul {
            let code = erreur["code"]?.contenu ?? "erreur"
            let message = erreur["message"]?.contenu ?? "Erreur du serveur."
            return .echec(id: id, code: code, message: message)
        }
        guard let ident = id else { return nil }
        let r = obj["result"] ?? .nul
        return .resultat(id: ident, resultat: r.estNul ? .vide : r)
    }
}
