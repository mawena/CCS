import XCTest
@testable import CCS

/// Onglet Réseau : adresses, appareils, bilan (mêmes règles que le web et Android).
final class ReseauTests: XCTestCase {
    func testAdresses() {
        XCTAssertEqual(Reseau.adresse("192.168.0.12:41641").sorte, .locale)
        XCTAssertEqual(Reseau.adresse("84.46.246.202:41641").sorte, .publique)
        XCTAssertEqual(Reseau.adresse("100.64.0.2:41641").sorte, .maille)
        XCTAssertEqual(Reseau.adresse("[2a02:c207::1]:41641"), Reseau.Adresse(ip: "2a02:c207::1", sorte: .v6))
        XCTAssertEqual(Reseau.adresse("[fe80::1]:41641").sorte, .locale)
    }

    func testGenres() {
        XCTAssertEqual(Reseau.genre(Appareil(name: "iphone", os: "iOS")), .iphone)
        XCTAssertEqual(Reseau.genre(Appareil(name: "x", os: "android")), .android)
        XCTAssertEqual(Reseau.genre(Appareil(name: "mawena-cloud", os: "linux")), .serveur)
        XCTAssertEqual(Reseau.genre(Appareil(name: "pc-bureau", os: "linux")), .bureau)
    }

    func testBilanEtListe() {
        let e = EtatReseau(
            ici: Appareil(name: "a", online: true, path: "self"),
            peers: [Appareil(name: "b", online: true, path: "lan"), Appareil(name: "c", path: "offline")],
            nodes: [NoeudServeur(name: "b"), NoeudServeur(name: "pixel")])
        XCTAssertEqual(Reseau.bilan(e), Reseau.Bilan(total: 3, enLigne: 2, lan: 1, direct: 0, relais: 0))
        XCTAssertEqual(Reseau.appareils(e).map { $0.0.name }, ["a", "b", "c", "pixel"])
        XCTAssertTrue(Reseau.appareils(e)[0].1)
        XCTAssertEqual(Reseau.appareils(e)[3].0.path, "offline")
    }

    func testFormats() {
        XCTAssertEqual(Reseau.octets(1536), "1,5 Ko")
        XCTAssertEqual(Reseau.octets(12 * 1024 * 1024), "12 Mo")
        XCTAssertTrue(Reseau.nomValide("pc-x"))
        XCTAssertFalse(Reseau.nomValide("Pas Bon"))
        XCTAssertEqual(Reseau.ligneLinux(["a", "b"]), "sudo sh -c 'a && b'")
    }

    func testLectureJson() {
        let e = EtatReseau(json: JSON.lire("""
        {"url":"https://network.mawena.cloud","self":{"name":"vps","path":"self","online":true},"peers":[],"state":"Running"}
        """)!)
        XCTAssertEqual(e.ici?.name, "vps")
        XCTAssertEqual(e.state, "Running")
    }
}
