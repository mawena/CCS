import XCTest
@testable import CCS

/// Mot de passe root depuis l'iPhone (phase 34) : décodage des `root.*` et suivi de la demande.
final class RootTests: XCTestCase {
    private func json(_ t: String) -> JSON { return JSON.lire(t)! }
    private let t0: Double = 1_800_000_000

    private func ask(_ id: String = "abc", tries: Int = 3, error: String? = nil, expire: Double? = nil) -> JSON {
        let e = error.map { ", \"error\": \"\($0)\"" } ?? ""
        let x = JSON.texteNombre(expire ?? t0 + 300)
        return json("""
        {"id": "\(id)", "machine": "lp-work", "command": "apt update", "expires_at": \(x), "tries_left": \(tries)\(e)}
        """)
    }

    func testDecodageDemande() {
        let d = DemandeRoot.lire(ask(error: "Mot de passe refusé (essai 1 sur 3)."), maintenant: t0)!
        XCTAssertEqual(d.id, "abc")
        XCTAssertEqual(d.machine, "lp-work")
        XCTAssertEqual(d.commande, "apt update")
        XCTAssertEqual(d.expire, t0 + 300)
        XCTAssertEqual(d.essais, 3)
        XCTAssertEqual(d.erreur, "Mot de passe refusé (essai 1 sur 3).")
        XCTAssertEqual(d.titre, "lp-work demande le mot de passe root")
        XCTAssertEqual(d.restant(maintenant: t0 + 55.5), 245)
        XCTAssertNil(DemandeRoot.lire(json("{\"machine\": \"x\"}"), maintenant: t0))
        XCTAssertNil(DemandeRoot.lire(ask(error: "  "), maintenant: t0)!.erreur)
    }

    func testHorlogeDecaleeDuServeur() {
        // déjà passée ou bien trop loin à l'heure du téléphone : 5 min à partir de maintenant
        XCTAssertEqual(DemandeRoot.lire(ask(expire: t0 - 10), maintenant: t0)!.expire, t0 + 300)
        XCTAssertEqual(DemandeRoot.lire(ask(expire: t0 + 3600), maintenant: t0)!.expire, t0 + 300)
        XCTAssertEqual(DemandeRoot.lire(ask(expire: t0 + 120), maintenant: t0)!.expire, t0 + 120)
    }

    func testEssais() {
        XCTAssertEqual(DemandeRoot.lire(ask(tries: 2), maintenant: t0)!.texteEssais, "2 essais restants.")
        XCTAssertEqual(DemandeRoot.lire(ask(tries: 1), maintenant: t0)!.texteEssais, "Dernier essai.")
    }

    func testDecodageEvenements() {
        XCTAssertEqual(EvRoot.lire("root.resolved", json("{\"id\": \"abc\", \"ok\": true}"), maintenant: t0), .reglee(id: "abc", ok: true))
        XCTAssertNil(EvRoot.lire("root.resolved", json("{\"ok\": true}"), maintenant: t0))
        XCTAssertEqual(EvRoot.lire("root.used", json("{\"machine\": \"vps\", \"command\": \"ls /root\", \"at\": 1}"), maintenant: t0),
                       .utilise(machine: "vps", commande: "ls /root"))
        XCTAssertEqual(EvRoot.lire("root.forgotten", json("{\"machine\": \"vps\", \"reason\": \"revoke\"}"), maintenant: t0),
                       .oublie(machine: "vps", raison: "revoke"))
        if case .demande(let d)? = EvRoot.lire("root.ask", ask(), maintenant: t0) { XCTAssertEqual(d.id, "abc") } else { XCTFail() }
        XCTAssertNil(EvRoot.lire("root.autre", .vide, maintenant: t0))
    }

    func testEtat() {
        let e = EtatRoot(json: json("""
        {"machine": "vps", "kept": true, "expires_at": 1800003600, "remaining": 1800, "pending": null}
        """))
        XCTAssertEqual(e.machine, "vps")
        XCTAssertTrue(e.garde)
        XCTAssertEqual(e.restant, 1800)
        XCTAssertNil(e.enAttente)
        let p = EtatRoot(json: json("""
        {"machine": "vps", "kept": false, "expires_at": null, "remaining": 0,
         "pending": {"id": "z", "machine": "vps", "command": "id", "expires_at": 1800000100, "tries_left": 2}}
        """))
        XCTAssertFalse(p.garde)
        XCTAssertEqual(p.enAttente?.texte("id"), "z")
    }

    func testDemandePuisReglee() {
        var s = SuiviRoot()
        XCTAssertFalse(s.aMontrer)
        XCTAssertNil(s.recevoir(.demande(DemandeRoot.lire(ask(), maintenant: t0)!), maintenant: t0))
        XCTAssertTrue(s.aMontrer)
        XCTAssertEqual(s.machine, "lp-work")
        // « Plus tard », puis la même demande revient avec une erreur : elle reste de côté
        s.masquee = true
        _ = s.recevoir(.demande(DemandeRoot.lire(ask(tries: 2, error: "refusé"), maintenant: t0)!), maintenant: t0)
        XCTAssertFalse(s.aMontrer)
        XCTAssertEqual(s.demande?.erreur, "refusé")
        // une nouvelle demande revient au premier plan
        _ = s.recevoir(.demande(DemandeRoot.lire(ask("def"), maintenant: t0)!), maintenant: t0)
        XCTAssertTrue(s.aMontrer)
        // `root.resolved` d'une autre demande : rien ne change ; de la bonne : la feuille se ferme
        _ = s.recevoir(.reglee(id: "abc", ok: true), maintenant: t0)
        XCTAssertEqual(s.demande?.id, "def")
        _ = s.recevoir(.reglee(id: "def", ok: false), maintenant: t0)
        XCTAssertNil(s.demande)
        XCTAssertFalse(s.aMontrer)
    }

    func testDemandeExpiree() {
        var s = SuiviRoot()
        _ = s.recevoir(.demande(DemandeRoot.lire(ask(expire: t0 + 60), maintenant: t0)!), maintenant: t0)
        XCTAssertEqual(s.prochaineEcheance, t0 + 60)
        s.expirer(maintenant: t0 + 59)
        XCTAssertNotNil(s.demande)
        s.expirer(maintenant: t0 + 60)
        XCTAssertNil(s.demande)
        XCTAssertNil(s.prochaineEcheance)
        // une demande arrivée déjà finie n'est pas montrée
        let vieille = DemandeRoot(id: "v", machine: "", commande: "", expire: t0 - 1, essais: 3, erreur: nil)
        _ = s.recevoir(.demande(vieille), maintenant: t0)
        XCTAssertNil(s.demande)
    }

    func testMotDePasseGardeEtOublie() {
        var s = SuiviRoot()
        s.etat(EtatRoot(json: json("{\"machine\": \"vps\", \"kept\": true, \"remaining\": 1790, \"pending\": null}")), maintenant: t0)
        XCTAssertEqual(s.minutesGarde(maintenant: t0), 30)
        XCTAssertEqual(s.minutesGarde(maintenant: t0 + 1789), 1)
        XCTAssertNil(s.minutesGarde(maintenant: t0 + 1790))
        XCTAssertEqual(s.recevoir(.utilise(machine: "vps", commande: "apt update"), maintenant: t0), "vps a lancé en root : apt update")
        XCTAssertEqual(s.recevoir(.utilise(machine: "", commande: ""), maintenant: t0), "La machine a lancé une commande root.")
        XCTAssertEqual(s.recevoir(.oublie(machine: "vps", raison: "revoke"), maintenant: t0), "Mot de passe root révoqué.")
        XCTAssertNil(s.minutesGarde(maintenant: t0))
        // déjà oublié : pas de second avis
        XCTAssertNil(s.recevoir(.oublie(machine: "vps", raison: "expired"), maintenant: t0))
    }

    func testEtatAvecDemandeEnAttente() {
        var s = SuiviRoot()
        let e = EtatRoot(json: json("""
        {"machine": "vps", "kept": false, "remaining": 0,
         "pending": {"id": "z", "machine": "vps", "command": "id", "expires_at": \(JSON.texteNombre(t0 + 100)), "tries_left": 2}}
        """))
        s.etat(e, maintenant: t0)
        XCTAssertEqual(s.demande?.id, "z")
        XCTAssertTrue(s.aMontrer)
        XCTAssertNil(s.minutesGarde(maintenant: t0))
        // plus rien en attente au statut suivant : la feuille se ferme
        s.etat(EtatRoot(json: json("{\"kept\": false, \"pending\": null}")), maintenant: t0)
        XCTAssertNil(s.demande)
    }

    func testOublieEtVider() {
        var s = SuiviRoot()
        s.etat(EtatRoot(json: json("{\"machine\": \"vps\", \"kept\": true, \"remaining\": 60}")), maintenant: t0)
        _ = s.recevoir(.demande(DemandeRoot.lire(ask(), maintenant: t0)!), maintenant: t0)
        s.oublie()
        XCTAssertNil(s.demande)
        XCTAssertNil(s.minutesGarde(maintenant: t0))
        s.vider()
        XCTAssertEqual(s, SuiviRoot())
    }

    func testCompteARebours() {
        XCTAssertEqual(texteMinutesSecondes(245), "4:05")
        XCTAssertEqual(texteMinutesSecondes(-3), "0:00")
    }
}
