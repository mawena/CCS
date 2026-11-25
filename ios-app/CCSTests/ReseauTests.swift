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
        XCTAssertEqual(Reseau.genre(Appareil(name: "srv-mawena-cloud", os: "linux")), .serveur)
        XCTAssertEqual(Reseau.genre(Appareil(name: "lp-work", os: "linux")), .bureau)
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

    private func machine(_ id: String, local: Bool = false, host: String? = nil, mesh: String? = nil, meshIp: String? = nil) -> Machine {
        var m = Machine(id: id, online: true, local: local)
        m.host = host
        m.mesh = mesh
        m.meshIp = meshIp
        return m
    }

    func testRattachement() {
        let machines = [
            machine("vps", local: true),
            machine("bureau", meshIp: "100.64.0.3"),
            machine("salon", mesh: "PC-Salon"),
            machine("laptop", host: ""),
            machine("autre", host: "Mon-Portable"),
        ]
        // la fiche du serveur ↔ la machine locale
        XCTAssertEqual(Reseau.machine(pour: Appareil(name: "srv-mawena-cloud"), ici: true, parmi: machines)?.id, "vps")
        // par l'adresse du réseau maillé
        XCTAssertEqual(Reseau.machine(pour: Appareil(name: "lp-work", ips: ["100.64.0.3", "fd7a::3"]), ici: false, parmi: machines)?.id, "bureau")
        // par `mesh`, sans casse
        XCTAssertEqual(Reseau.machine(pour: Appareil(name: "pc-salon"), ici: false, parmi: machines)?.id, "salon")
        // par l'identifiant
        XCTAssertEqual(Reseau.machine(pour: Appareil(name: "laptop"), ici: false, parmi: machines)?.id, "laptop")
        // par l'hôte de la machine comparé à l'hôte de l'appareil
        XCTAssertEqual(Reseau.machine(pour: Appareil(name: "x", host: "mon-portable"), ici: false, parmi: machines)?.id, "autre")
        // jamais la machine locale pour un autre appareil ; chaînes vides ignorées
        XCTAssertNil(Reseau.machine(pour: Appareil(name: "vps"), ici: false, parmi: machines))
        XCTAssertNil(Reseau.machine(pour: Appareil(name: "", host: ""), ici: false, parmi: machines))
        XCTAssertNil(Reseau.machine(pour: Appareil(name: "iphone"), ici: true, parmi: [machine("pc")]))
    }

    func testFichesAvecRicochet() {
        let e = EtatReseau(
            ici: Appareil(name: "srv-mawena-cloud", online: true, path: "self"),
            peers: [Appareil(name: "lp-work", ips: ["100.64.0.3"], online: true, path: "lan"), Appareil(name: "iphone", path: "offline")])
        var hors = Machine(id: "pc-salon", name: "PC du salon", online: false)
        hors.tunnel = true
        let f = Reseau.fiches(e, machines: [machine("vps", local: true), machine("bureau", meshIp: "100.64.0.3"), hors])
        XCTAssertEqual(f.map { $0.appareil.name }, ["srv-mawena-cloud", "lp-work", "iphone", "PC du salon"])
        XCTAssertEqual(f.map { $0.machine?.id }, ["vps", "bureau", nil, "pc-salon"])
        XCTAssertEqual(f.map { $0.ricochet }, [false, false, false, true])
        XCTAssertEqual(f[3].id, "ricochet:pc-salon")
        XCTAssertEqual(f[3].appareil.path, "offline")
        XCTAssertTrue(f[3].appareil.ips.isEmpty)
        XCTAssertEqual(Reseau.Chemin.de("ricochet").libelle, "Par Ricochet")
        XCTAssertEqual(Reseau.Chemin.de("self").libelle, "Serveur CCS")
        // en ligne par Ricochet
        XCTAssertEqual(Reseau.fiches(EtatReseau(), machines: [machine("pc-salon")]).first?.appareil.path, "ricochet")
    }

    func testBarresEtAjout() {
        var m = Machine(id: "pc", online: true, cores: 8, load: 1.25)
        m.memUsed = 3.5 * 1_073_741_824
        m.memTotal = 16 * 1_073_741_824
        let b = Reseau.barres(m)
        XCTAssertEqual(b.map { $0.libelle }, ["Charge", "Mémoire"])
        XCTAssertEqual(b[0].valeur, "0,16/cœur")
        XCTAssertEqual(b[1].valeur, "3,5/16 Go")
        XCTAssertFalse(b[1].chaude)
        XCTAssertEqual(Reseau.barres(Machine(id: "x", online: false, cores: 4, load: 9)), [])
        XCTAssertTrue(Reseau.barres(Machine(id: "x", online: true, cores: 2, load: 4)).first?.chaude ?? false)
        XCTAssertTrue(Reseau.injoignable(Machine(id: "x")))
        XCTAssertFalse(Reseau.injoignable(machine("x", meshIp: "100.64.0.9")))
        XCTAssertFalse(Reseau.ajoutParRicochet(nil))
        XCTAssertFalse(Reseau.ajoutParRicochet(ReglagesRelais(relais: "https://r.ex", jetonDefini: true)))
        XCTAssertTrue(Reseau.ajoutParRicochet(ReglagesRelais(relais: "https://r.ex", jetonDefini: true, operateurDefini: true)))
    }

    func testLectureJson() {
        let e = EtatReseau(json: JSON.lire("""
        {"url":"https://network.mawena.cloud","self":{"name":"vps","path":"self","online":true},"peers":[],"state":"Running"}
        """)!)
        XCTAssertEqual(e.ici?.name, "vps")
        XCTAssertEqual(e.state, "Running")
    }
}
