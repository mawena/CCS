import XCTest
@testable import CCS

final class FormatTests: XCTestCase {
    private let t0 = 1_000_000.0

    func testIlYAcommeLaVersionWeb() {
        XCTAssertEqual(Format.ilYA(nil, maintenant: t0), "")
        XCTAssertEqual(Format.ilYA(0, maintenant: t0), "")
        XCTAssertEqual(Format.ilYA(t0 - 30, maintenant: t0), "à l'instant")
        XCTAssertEqual(Format.ilYA(t0 + 30, maintenant: t0), "à l'instant")       // horloges décalées
        XCTAssertEqual(Format.ilYA(t0 - 5 * 60 - 10, maintenant: t0), "il y a 5 min")
        XCTAssertEqual(Format.ilYA(t0 - 3 * 3600 - 59, maintenant: t0), "il y a 3 h")
        XCTAssertEqual(Format.ilYA(t0 - 86400 - 5, maintenant: t0), "hier")
        XCTAssertEqual(Format.ilYA(t0 - 4 * 86400, maintenant: t0), "il y a 4 j")
    }

    func testNombreCourt() {
        XCTAssertEqual(Format.nombreCourt(999.4), "999")
        XCTAssertEqual(Format.nombreCourt(12_345), "12 k")
        XCTAssertEqual(Format.nombreCourt(1_234_567), "1.2 M")
        XCTAssertEqual(Format.nombreCourt(3e9), "3.0 G")
    }

    func testCheminsCourts() {
        XCTAssertEqual(Format.base("/home/c/Work/ccs/"), "ccs")
        XCTAssertEqual(Format.base(nil), "")
        XCTAssertEqual(Format.court("/home/c/Work/ccs", home: "/home/c"), "~/Work/ccs")
        XCTAssertEqual(Format.court("/srv/site", home: "/home/c"), "/srv/site")
        XCTAssertEqual(Format.court("/home/cc", home: "/home/c"), "/home/cc")
    }

    func testPourcentBorne() {
        XCTAssertEqual(Format.pourcent(-3), 0)
        XCTAssertEqual(Format.pourcent(42.6), 43)
        XCTAssertEqual(Format.pourcent(130), 100)
    }

    func testBarresTrieesEtLimitees() {
        var d: [String: Double] = [:]
        for i in 1...10 { d["p\(i)"] = Double(i) }
        let b = Format.barres(d, total: 55)
        XCTAssertEqual(b.count, 8)
        XCTAssertEqual(b.first?.nom, "p10")
        XCTAssertEqual(b.first?.part ?? 0, 100 * 10 / 55.0, accuracy: 1e-9)
        XCTAssertEqual(Format.barres(["a": 1], total: 0).first?.part, 0)
    }

    func testRolesEtEtats() {
        XCTAssertEqual(Format.role("utilisateur"), .toi)
        XCTAssertEqual(Format.role("USER"), .toi)
        XCTAssertEqual(Format.role("assistant"), .claude)
        XCTAssertNil(Format.role("outil"))
        XCTAssertEqual(EtatChat.de("busy").libelle, "Claude travaille")
        XCTAssertEqual(EtatChat.de("permission").libelle, "attend ta réponse")
        XCTAssertEqual(EtatChat.de("idle").ton, .pret)
        XCTAssertEqual(EtatChat.de("inconnu").libelle, "arrêté")
    }

    func testDossiersProposesSansDoublonEtFiltres() {
        let home = "/home/c"
        let tous = dossiersProposes(
            recents: ["/home/c/Work/ccs"], connus: ["/home/c/Work/ccs", "/home/c/Work/site"],
            depots: ["/home/c/Work/site", "/srv/app"], saisie: "", home: home
        )
        XCTAssertEqual(tous.map { $0.etiquette }, ["récent", "projet", "git"])
        XCTAssertEqual(tous.map { $0.chemin }, ["/home/c/Work/ccs", "/home/c/Work/site", "/srv/app"])
        let filtre = dossiersProposes(recents: ["/home/c/Work/ccs"], connus: [], depots: ["/srv/app"], saisie: "~/work", home: home)
        XCTAssertEqual(filtre.map { $0.chemin }, ["/home/c/Work/ccs"])
        XCTAssertEqual(dossiersProposes(recents: [], connus: [], depots: ["/srv/app"], saisie: "APP", home: home).map { $0.chemin }, ["/srv/app"])
    }

    func testCartesDeComptes() {
        let texte = #"""
        {"cards": [{"name": "perso", "plan": "Max", "active": true, "color": "#62a0ea",
          "main": [{"kind": "five_hour", "label": "5 h", "percent": 42.5, "reset": "dans 2 h"}],
          "others": [], "status": {"text": "OK", "kind": "success"}, "error_raw": null,
          "details": ["Relevé à 10:00"], "fetched_at": 1795091812.06, "has_data": true,
          "inconnu": 1}], "best": {"name": "perso", "reason": "le plus de marge"}, "auto_switch": true,
          "updated_at": 1795091812.5, "running_chats": 2}
        """#
        let c = Cartes(json: JSON.lire(texte) ?? .vide)
        XCTAssertEqual(c.cards.count, 1)
        XCTAssertEqual(c.cards[0].name, "perso")
        XCTAssertEqual(c.cards[0].main[0].percent, 42.5)
        XCTAssertEqual(c.cards[0].status?.kind, "success")
        XCTAssertNil(c.cards[0].erreur)
        XCTAssertTrue(c.cards[0].donnees)
        XCTAssertEqual(c.chatsEnCours, 2)
        XCTAssertEqual(texteDans(c.best, "name"), "perso")
        XCTAssertNil(texteDans(c.bascule, "decision", "reason"))
    }

    func testEtatDesComptesEtPause() {
        let j = JSON.lire(#"{"user": "c", "home": "/home/c", "active": "perso", "pause": null, "pause_choices": [["1h", "1 heure"], ["demain", "jusqu'à demain"], ["seul"]]}"#) ?? .vide
        let e = EtatComptes(json: j)
        XCTAssertNil(e.pause)
        XCTAssertEqual(e.choix.map { $0.valeur }, ["1h", "demain"])
        XCTAssertEqual(e.home, "/home/c")
    }
}
