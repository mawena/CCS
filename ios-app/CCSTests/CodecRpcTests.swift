import XCTest
@testable import CCS

final class CodecRpcTests: XCTestCase {
    func testRequeteAuFormatDuServeur() {
        let texte = CodecRpc.requete(id: 7, methode: "files.list", params: ["path": "~/Work"])
        let obj = JSON.lire(texte)
        XCTAssertEqual(obj?["id"]?.nombre, 7)
        XCTAssertEqual(obj?["method"]?.chaine, "files.list")
        XCTAssertEqual(obj?["params"]?["path"]?.chaine, "~/Work")
        XCTAssertTrue(texte.contains("\"id\":7"))          // entier, pas 7.0
    }

    func testRequeteSansParametresEnvoieUnObjetVide() {
        let obj = JSON.lire(CodecRpc.requete(id: 1, methode: "accounts.cards"))
        XCTAssertEqual(obj?["params"], JSON.vide)
    }

    func testResultat() {
        guard case .resultat(let id, let r)? = CodecRpc.decoder(#"{"id": 3, "result": {"n": 2}}"#) else { return XCTFail() }
        XCTAssertEqual(id, 3)
        XCTAssertEqual(r.entier("n"), 2)
    }

    func testResultatNulDevientObjetVide() {
        XCTAssertEqual(CodecRpc.decoder(#"{"id": 4, "result": null}"#), .resultat(id: 4, resultat: .vide))
    }

    func testErreur() {
        let m = CodecRpc.decoder(#"{"id": 5, "error": {"code": "refuse", "message": "Requête refusée."}}"#)
        XCTAssertEqual(m, .echec(id: 5, code: "refuse", message: "Requête refusée."))
    }

    func testErreurIncompleteGardeDesValeursParDefaut() {
        guard case .echec(_, let code, let message)? = CodecRpc.decoder(#"{"id": 6, "error": "boum"}"#) else { return XCTFail() }
        XCTAssertEqual(code, "erreur")
        XCTAssertFalse(message.isEmpty)
    }

    func testEvenement() {
        guard case .evenement(let nom, let d)? = CodecRpc.decoder(#"{"event": "chat.tags", "data": {"id": "s1"}}"#) else { return XCTFail() }
        XCTAssertEqual(nom, "chat.tags")
        XCTAssertEqual(d.texte("id"), "s1")
        XCTAssertEqual(CodecRpc.decoder(#"{"event": "notice"}"#), .evenement(nom: "notice", donnees: .vide))
    }

    func testTramesIncomprisesIgnorees() {
        XCTAssertNil(CodecRpc.decoder("pas du json"))
        XCTAssertNil(CodecRpc.decoder("[1, 2]"))
        XCTAssertNil(CodecRpc.decoder(#"{"result": {}}"#))
        XCTAssertNil(CodecRpc.decoder(#"{"id": "x", "result": {}}"#))
    }

    func testJsonBooleensEtNombresDistincts() {
        let j = JSON.lire(#"{"a": true, "b": 1, "c": 1.5, "d": null, "e": "é\n\"x\""}"#)
        XCTAssertEqual(j?["a"], .booleen(true))
        XCTAssertEqual(j?["b"], .nombre(1))
        XCTAssertEqual(j?["d"], .nul)
        XCTAssertEqual(j?.texte("c"), "1.5")
        let aller = JSON.lire(j?.texteCompact ?? "")
        XCTAssertEqual(aller, j)                            // écriture puis relecture : identique
    }

    func testReponsesDeConnexion() {
        XCTAssertEqual(ApiHttp.lireReponse(200, #"{"status": "ok", "user": "c", "token": "tok"}"#).token, "tok")
        let inscription = ApiHttp.lireReponse(200, #"{"status": "enroll", "pending": "p", "secret": "S", "qr_svg": "<svg/>"}"#)
        XCTAssertEqual(inscription.pending, "p")
        XCTAssertEqual(ApiHttp.lireReponse(200, #"{"status": "blocked", "retry_after": 30}"#).retryAfter, 30)
        XCTAssertEqual(ApiHttp.lireReponse(401, "Identifiant incorrect").status, "refused")
        XCTAssertEqual(ApiHttp.lireReponse(503, "").status, "error")
        XCTAssertEqual(ApiHttp.lireReponse(200, "<html>").status, "error")
    }

    func testAdresses() {
        XCTAssertEqual(Adresse.normaliser("ccs.exemple.fr"), "https://ccs.exemple.fr")
        XCTAssertEqual(Adresse.normaliser(" https://Hote.fr/ccs/?a=1#x "), "https://hote.fr/ccs")
        XCTAssertNil(Adresse.normaliser("ftp://hote.fr"))
        XCTAssertNil(Adresse.normaliser("https://moi:secret@hote.fr"))
        XCTAssertNil(Adresse.normaliser("deux mots"))
        XCTAssertEqual(Adresse.api("https://hote.fr/ccs", "/api/health")?.absoluteString, "https://hote.fr/ccs/api/health")
        XCTAssertEqual(Adresse.ws("https://hote.fr", "api/ws")?.absoluteString, "wss://hote.fr/api/ws")
        XCTAssertEqual(Adresse.ws("http://127.0.0.1:8420", "api/ws")?.absoluteString, "ws://127.0.0.1:8420/api/ws")
    }
}
