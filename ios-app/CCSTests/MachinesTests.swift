import XCTest
@testable import CCS

final class MachinesTests: XCTestCase {
    private func json(_ t: String) -> JSON { return JSON.lire(t)! }

    func testAdresseWebSocketAvecMachine() {
        XCTAssertEqual(Adresse.ws("https://ccs.mawena.cloud", "api/ws")?.absoluteString, "wss://ccs.mawena.cloud/api/ws?protocol=1")
        XCTAssertEqual(Adresse.ws("https://ccs.mawena.cloud", "api/ws", machine: "pc-bureau")?.absoluteString,
                       "wss://ccs.mawena.cloud/api/ws?protocol=1&machine=pc-bureau")
    }

    func testListeEtDescription() {
        let l = ListeMachines(json: json("""
        {"configured": true, "machines": [
          {"id": "vps", "name": "VPS", "online": true, "local": true},
          {"id": "pc-bureau", "name": "", "online": true, "tunnel": true, "cores": 8, "load": 1.25,
           "tools": ["flutter", "node"], "limit": 3, "running": 1, "waiting": 2},
          {"id": "portable", "online": true, "tunnel": false}
        ]}
        """))
        XCTAssertEqual(l.autres.map { $0.id }, ["pc-bureau", "portable"])
        let pc = l.autres[0]
        XCTAssertEqual(pc.nom, "pc-bureau")
        XCTAssertTrue(pc.choisissable)
        XCTAssertEqual(pc.description, "en ligne · charge 1.2 sur 8 cœurs")
        XCTAssertEqual(pc.places, "Places : 1/3 · 2 en attente")
        XCTAssertEqual(pc.tools, ["flutter", "node"])
        XCTAssertFalse(l.autres[1].choisissable)
        XCTAssertEqual(l.autres[1].description, "en ligne · tunnel SSH non activé")
        XCTAssertEqual(Machine(id: "x").description, "hors ligne")
    }

    func testMachineGardeeEnCache() throws {
        let m = Machine(id: "pc", name: "PC", online: true, cores: 4, load: 0.5, tunnel: true)
        let d = try JSONEncoder().encode([m])
        XCTAssertEqual(try JSONDecoder().decode([Machine].self, from: d), [m])
    }

    func testDureeEtLigne() {
        XCTAssertEqual(Travaux.duree(42), "42 s")
        XCTAssertEqual(Travaux.duree(187), "3 min 07 s")
        XCTAssertEqual(Travaux.duree(7500), "2 h 05")
        let j = TravailDistant(json: json("""
        {"id": "a1", "text": "make test", "cwd": "/home/moi/Work/ccs", "machine": "pc-bureau",
         "state": "done", "code": 1, "created": 900, "started": 1000, "ended": 1187}
        """))
        XCTAssertEqual(Travaux.ligne(j, home: "/home/moi", maintenant: 2000), "pc-bureau · 3 min 07 s · code 1 · ~/Work/ccs")
        XCTAssertEqual(Travaux.teinte(j), .echec)
        XCTAssertFalse(Travaux.actif(j))
        let k = TravailDistant(json: json("""
        {"id": "b2", "text": "flutter build apk", "cwd": "", "machine": null, "state": "waiting", "code": null, "created": 1940}
        """))
        XCTAssertEqual(Travaux.ligne(k, maintenant: 2000), "machine à choisir · créé il y a 1 min")
        XCTAssertTrue(Travaux.actif(k))
        XCTAssertEqual(Travaux.teinte(k), .attente)
        XCTAssertEqual(Travaux.libelle(k), "attente")
        XCTAssertEqual(Travaux.libelle(j), "fini")
        XCTAssertEqual(Travaux.libelle(TravailDistant(json: json(#"{"state": "scheduled"}"#))), "programmé")
    }

    func testDemandeDeLancement() {
        XCTAssertEqual(Travaux.demande(commande: " ", dossier: "", home: "/h", machine: "", quand: "", heure: "").erreur,
                       "Écris la commande à lancer.")
        XCTAssertEqual(Travaux.demande(commande: "ls", dossier: "", home: "/h", machine: "", quand: "heure", heure: "25:00").erreur,
                       "Choisis l'heure.")
        let d = Travaux.demande(commande: "make deb", dossier: "~/Work/ccs", home: "/h", machine: "pc", quand: "nuit", heure: "")
        XCTAssertEqual(d.params?["cwd"]?.chaine, "/h/Work/ccs")
        XCTAssertEqual(d.params?["when"]?.chaine, "nuit")
        XCTAssertEqual(d.params?["machine"]?.chaine, "pc")
        let e = Travaux.demande(commande: "ls", dossier: "", home: "/h", machine: "", quand: "heure", heure: "22:30")
        XCTAssertEqual(e.params?["cwd"]?.chaine, "/h")
        XCTAssertEqual(e.params?["when"]?.chaine, "22:30")
        XCTAssertNil(e.params?["machine"])
    }
}

final class LiensFichiersTests: XCTestCase {
    private let l = LiensFichiers(cwd: "/home/moi/ccs", fichiers: ["ccs_app/core.py", "README.md", "web/app.js"])

    func testReferenceSeule() {
        XCTAssertEqual(l.ref("ccs_app/core.py")?.chemin, "ccs_app/core.py")
        XCTAssertEqual(l.ref("ccs_app/core.py:42")?.ligne, 42)
        XCTAssertEqual(l.ref("./README.md")?.chemin, "README.md")
        XCTAssertEqual(l.ref("/home/moi/ccs/web/app.js:3:7")?.chemin, "web/app.js")
        XCTAssertNil(l.ref("/ailleurs/web/app.js"))
        XCTAssertNil(l.ref("inconnu.py"))
        XCTAssertNil(l.ref("../ccs/README.md"))
    }

    func testDansLeTexte() {
        let t = "Vu dans ccs_app/core.py:12 et README.md, pas dans autre.txt."
        let r = l.trouver(t)
        XCTAssertEqual(r.map { $0.texte }, ["ccs_app/core.py:12", "README.md"])
        XCTAssertEqual(r.first?.ligne, 12)
        XCTAssertEqual((t as NSString).substring(with: NSRange(location: r[1].debut, length: 9)), "README.md")
        XCTAssertTrue(LiensFichiers(cwd: "/x", fichiers: []).trouver(t).isEmpty)
    }

    func testLienAllerRetour() {
        let r = l.ref("web/app.js:8")!
        let u = l.lien(r)!
        XCTAssertEqual(u.scheme, LiensFichiers.schema)
        let f = LiensFichiers.lire(u)
        XCTAssertEqual(f?.chemin, "/home/moi/ccs/web/app.js")
        XCTAssertEqual(f?.ligne, 8)
        XCTAssertNil(LiensFichiers.lire(URL(string: "https://ex.fr")!))
    }
}
