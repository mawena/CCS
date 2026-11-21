import XCTest
@testable import CCS

/// Usage des tours, cache expiré, couleur du contexte, gros consommateurs (`token_use.py`).
final class UsageTests: XCTestCase {
    private func ev(_ texte: String) -> EvChat { return EvChat.lire(JSON.lire(texte)!) }

    // usage de `tests/test_token_use.py` (RESULT)
    private let tourAvecUsage = #"""
    {"type": "TurnResult", "ok": true, "subtype": "success", "cost_usd": 1.5, "text": "",
     "usage": {"input": 4, "cache_read": 35952, "cache_write": 15423, "output": 403, "cost_usd": 0.0365,
               "context": 27100, "cache_ttl_s": 3600, "model": "claude-opus-5-5"}}
    """#

    func testTokensCourtsCommeFmtTokens() {
        XCTAssertEqual(Jetons.court(0), "0")
        XCTAssertEqual(Jetons.court(403), "403")
        XCTAssertEqual(Jetons.court(999), "999")
        XCTAssertEqual(Jetons.court(1000), "1 k")
        XCTAssertEqual(Jetons.court(12_345), "12 k")
        XCTAssertEqual(Jetons.court(35_952), "36 k")
        XCTAssertEqual(Jetons.court(999_999), "1000 k")
        XCTAssertEqual(Jetons.court(1_234_567), "1,2 M")
        XCTAssertEqual(Jetons.court(-5), "0")
    }

    func testResumeCommeSummary() {
        guard case .tour(_, _, _, _, _, _, let usage) = ev(tourAvecUsage) else { return XCTFail("tour attendu") }
        XCTAssertEqual(Jetons.resume(usage), "36 k lus · 15 k écrits · 403 produits · 0,04 $")
        XCTAssertEqual(Jetons.resume(nil), "")
        // coût nul omis, rien lu dans le cache
        XCTAssertEqual(Jetons.resume(UsageTour(entree: 1200, produits: 5)), "1 k écrits · 5 produits")
    }

    func testDecodageDeLUsageDuTour() {
        guard case .tour(let ok, _, let cout, _, _, _, let usage) = ev(tourAvecUsage) else { return XCTFail("tour attendu") }
        XCTAssertTrue(ok)
        XCTAssertEqual(cout, 1.5)
        XCTAssertEqual(usage, UsageTour(entree: 4, cacheLu: 35952, cacheEcrit: 15423, produits: 403, coutUsd: 0.0365,
                                        contexte: 27100, ttlCache: 3600, modele: "claude-opus-5-5"))
    }

    func testTourSansUsage() {
        for texte in [#"{"type": "TurnResult", "ok": true}"#, #"{"type": "TurnResult", "ok": true, "usage": {}}"#,
                      #"{"type": "TurnResult", "ok": true, "usage": null}"#] {
            guard case .tour(_, _, _, _, _, _, let usage) = ev(texte) else { return XCTFail("tour attendu") }
            XCTAssertNil(usage, texte)
        }
    }

    func testDecodageDuCacheExpire() {
        let e = ev(#"{"type": "CacheExpired", "context": 200000, "ttl_s": 3600, "rewrite_usd": 1.6, "text": "Cache expiré : …"}"#)
        XCTAssertEqual(e, .cacheExpire(contexte: 200_000, ttlS: 3600, reecritureUsd: 1.6, texte: "Cache expiré : …"))
        let sansPrix = ev(#"{"type": "CacheExpired", "context": 50000, "ttl_s": 300, "rewrite_usd": null, "text": ""}"#)
        XCTAssertEqual(sansPrix, .cacheExpire(contexte: 50_000, ttlS: 300, reecritureUsd: nil, texte: ""))
    }

    func testLeFilMontreLUsageSousLaFinDuTour() {
        let f = FilChat()
        _ = f.recevoir(1, ev(#"{"type": "AssistantText", "msg_id": "m1", "text": "Fait."}"#))
        _ = f.recevoir(2, ev(tourAvecUsage))
        XCTAssertEqual(f.fil.taille, 2)
        guard case .usage(let u) = f.fil.elements[1] else { return XCTFail("ligne d'usage attendue") }
        XCTAssertEqual(u.texte, "36 k lus · 15 k écrits · 403 produits · 0,04 $")
        XCTAssertEqual(f.dernierUsage?.contexte, 27100)
        // sans usage : pas de ligne
        _ = f.recevoir(3, ev(#"{"type": "TurnResult", "ok": true}"#))
        XCTAssertEqual(f.fil.taille, 2)
    }

    func testCacheExpireJusquAuTourSuivant() {
        let f = FilChat()
        _ = f.recevoir(1, ev(#"{"type": "CacheExpired", "context": 200000, "ttl_s": 3600, "rewrite_usd": 1.6, "text": "Cache expiré."}"#))
        XCTAssertEqual(f.cacheExpire, 200_000)
        guard case .note(let n) = f.fil.elements[0] else { return XCTFail("note attendue") }
        XCTAssertEqual(n.texte, "Cache expiré.")
        XCTAssertEqual(n.action, .cacheExpire)
        XCTAssertEqual(n.genre, "warning")
        _ = f.recevoir(2, ev(tourAvecUsage))
        XCTAssertNil(f.cacheExpire)
    }

    func testAvertissementCache() {
        XCTAssertEqual(Jetons.avertissementCache(200_000), "Le cache a expiré : ce message relira 200 k tokens au prix fort.")
    }

    func testCouleurDuContexte() {
        XCTAssertEqual(Jetons.niveau(74_999, seuil: 0), .vert)          // défaut 150 000
        XCTAssertEqual(Jetons.niveau(75_000, seuil: 0), .orange)
        XCTAssertEqual(Jetons.niveau(150_000, seuil: 0), .orange)
        XCTAssertEqual(Jetons.niveau(150_001, seuil: 0), .rouge)
        XCTAssertEqual(Jetons.niveau(40_000, seuil: 100_000), .vert)
        XCTAssertEqual(Jetons.niveau(60_000, seuil: 100_000), .orange)
        XCTAssertEqual(Jetons.niveau(120_000, seuil: 100_000), .rouge)
    }

    func testGrosConsommateursDuRapport() {
        let r = Rapport(json: JSON.lire(#"""
        {"total": 1000, "responses": 12, "by_hour": [], "top": [
          {"title": "Refonte du pont", "project": "CCS", "file": "/j/a.jsonl", "share": 42.5, "answers": 120,
           "avg_context": 180000, "rewrite_share": 35.0,
           "causes": ["contexte long (180 k tokens relus à chaque réponse) : /compact, ou une nouvelle session par sujet"]},
          {"title": "Petit", "project": "X", "file": "/j/b.jsonl", "share": 3, "answers": 2, "avg_context": 9000,
           "rewrite_share": 0, "causes": []}
        ]}
        """#)!)
        XCTAssertEqual(r.top.count, 2)
        XCTAssertEqual(r.top[0].titre, "Refonte du pont")
        XCTAssertEqual(r.top[0].projet, "CCS")
        XCTAssertEqual(r.top[0].part, 42.5)
        XCTAssertEqual(r.top[0].reponses, 120)
        XCTAssertEqual(r.top[0].contexteMoyen, 180_000)
        XCTAssertEqual(r.top[0].partReecrite, 35.0)
        XCTAssertEqual(r.top[0].causes.count, 1)
        XCTAssertEqual(r.top[1].causes, [])
        XCTAssertEqual(Rapport(json: JSON.lire(#"{"total": 0}"#)!).top, [])
    }
}
