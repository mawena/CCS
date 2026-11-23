import XCTest
@testable import CCS

/// Barre d'appareils de l'onglet Fichiers (`web/files-browser.js`).
final class AppareilsTests: XCTestCase {
    private func machines(_ t: String) -> [Machine] {
        return ListeMachines(json: JSON.lire(t)!).machines
    }

    private let exemple = """
    {"machines": [
      {"id": "vps", "name": "VPS", "online": true, "local": true, "tunnel": true},
      {"id": "pc-bureau", "name": "PC bureau", "online": true, "tunnel": false, "mesh_ip": "100.64.0.2"},
      {"id": "laptop-maison", "online": true, "tunnel": true, "mesh_ip": ""},
      {"id": "vieux", "online": true, "tunnel": false, "mesh_ip": "  "},
      {"id": "eteint", "online": false, "tunnel": true, "mesh_ip": "100.64.0.9"},
      {"id": "ancien", "online": true}
    ]}
    """

    func testServeurDAbordEtServeurLocalExclu() {
        let l = Appareils.liste(machines(exemple))
        XCTAssertEqual(l.map { $0.id }, ["", "pc-bureau", "laptop-maison", "vieux", "eteint", "ancien"])
        XCTAssertEqual(l[0].nom, "Serveur CCS")
        XCTAssertTrue(l[0].estServeur)
        XCTAssertTrue(l[0].joignable)
        XCTAssertNil(l[0].raison)
        XCTAssertEqual(l[1].nom, "PC bureau")
        XCTAssertEqual(l[2].nom, "laptop-maison")
    }

    func testJoignableParReseauMailleOuTunnel() {
        let l = Appareils.liste(machines(exemple))
        let joignables = l.filter { $0.joignable }.map { $0.id }
        XCTAssertEqual(joignables, ["", "pc-bureau", "laptop-maison"])
    }

    func testRaisons() {
        let m = machines(exemple)
        XCTAssertNil(Appareils.raison(m[1]))
        XCTAssertNil(Appareils.raison(m[2]))
        // adresse maillée faite d'espaces : comme vide
        XCTAssertEqual(Appareils.raison(m[3]), "ni réseau maillé ni tunnel")
        XCTAssertEqual(Appareils.raison(m[4]), "hors ligne")
        // ancien serveur : ni `mesh_ip` ni `tunnel`
        XCTAssertEqual(Appareils.raison(m[5]), "ni réseau maillé ni tunnel")
        // le serveur lui-même n'est jamais un appareil à part
        XCTAssertFalse(Appareils.joignable(m[0]))
    }

    func testIcones() {
        let m = machines(exemple)
        XCTAssertEqual(Appareils.icone(m[1]), "desktopcomputer")
        XCTAssertEqual(Appareils.icone(m[2]), "laptopcomputer")
        XCTAssertEqual(Appareils.liste(m)[0].icone, "cloud")
    }

    func testNomEtMessage() {
        let m = machines(exemple)
        XCTAssertEqual(Appareils.nom("", m), "Serveur CCS")
        XCTAssertEqual(Appareils.nom("pc-bureau", m), "PC bureau")
        XCTAssertEqual(Appareils.nom("inconnu", m), "inconnu")
        XCTAssertEqual(Appareils.messageInjoignable("PC bureau", serveur: false, "Machine injoignable."),
                       "PC bureau injoignable : Machine injoignable.")
        XCTAssertEqual(Appareils.messageInjoignable("Serveur CCS", serveur: true, "Pas de réponse du serveur."),
                       "Pas de réponse du serveur.")
    }

    func testConnexionAPartSeulementSiAutreQueLaMachinePilotee() {
        XCTAssertFalse(Appareils.connexionAPart(appareil: "", pilotee: ""))
        XCTAssertTrue(Appareils.connexionAPart(appareil: "pc-bureau", pilotee: ""))
        XCTAssertFalse(Appareils.connexionAPart(appareil: "pc-bureau", pilotee: "pc-bureau"))
        // on pilote un PC : le serveur CCS demande sa propre connexion
        XCTAssertTrue(Appareils.connexionAPart(appareil: "", pilotee: "pc-bureau"))
    }

    func testAdresseDeLaConnexionDeLAppareil() {
        XCTAssertEqual(Adresse.ws("https://ccs.mawena.cloud", "api/ws", machine: "laptop-maison")?.absoluteString,
                       "wss://ccs.mawena.cloud/api/ws?protocol=1&machine=laptop-maison")
        XCTAssertEqual(Adresse.ws("http://192.168.1.5:8080/ccs/", "api/ws", machine: "")?.absoluteString,
                       "ws://192.168.1.5:8080/ccs/api/ws?protocol=1")
    }

    @MainActor
    func testClientFixeNeTouchePasLaMachinePilotee() {
        let avant = Prefs.lire("machine")
        let c = CcsClient(machineFixe: "pc-bureau")
        XCTAssertTrue(c.fixe)
        XCTAssertEqual(c.machine, "pc-bureau")
        c.changerMachine("autre", nom: "Autre")
        XCTAssertEqual(c.machine, "autre")
        XCTAssertEqual(Prefs.lire("machine"), avant)
        let serveur = CcsClient(machineFixe: "")
        XCTAssertEqual(serveur.machine, "")
        XCTAssertFalse(CcsClient().fixe)
    }
}
