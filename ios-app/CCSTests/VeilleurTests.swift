import XCTest
@testable import CCS

final class VeilleurTests: XCTestCase {
    private func autorisation(_ r: String, outil: String = "Bash") -> EvChat {
        return .autorisation(requestId: r, outil: outil, affiche: "", entree: .objet(["command": .chaine("ls")]), description: "", agentId: nil)
    }

    private func tour(_ texte: String = "", interrompu: Bool = false) -> EvChat {
        return .tour(ok: true, sousType: "success", coutUsd: 0, texte: texte, limite: false, interrompu: interrompu)
    }

    func testFinDeTourAnnonceeAvecLeDernierTexte() {
        let v = Veilleur()
        _ = v.recevoir("c", .etat("busy"), ts: 0)
        _ = v.recevoir("c", .texte(msgId: "m", texte: "C'est **fait**.", parentId: nil), ts: 1)
        let a = v.recevoir("c", .etat("idle"), ts: 2)
        XCTAssertEqual(a, [.finTour(chatId: "c", resume: "C'est fait.")])
    }

    func testPasDeFinPourLeChatAfficheNiApresInterruption() {
        let v = Veilleur()
        _ = v.afficher("c")
        _ = v.recevoir("c", .etat("busy"), ts: 0)
        XCTAssertTrue(v.recevoir("c", .etat("idle"), ts: 1).isEmpty)
        _ = v.afficher(nil)
        _ = v.recevoir("c", .etat("busy"), ts: 2)
        _ = v.recevoir("c", tour(interrompu: true), ts: 3)
        XCTAssertTrue(v.recevoir("c", .etat("idle"), ts: 4).isEmpty)
    }

    func testAttentePuisReglee() {
        let v = Veilleur()
        let a = v.recevoir("c", autorisation("r1"), ts: 0)
        guard case .attente(_, let r, let question, _) = a.first else { return XCTFail("attente attendue") }
        XCTAssertEqual(r, "r1")
        XCTAssertFalse(question)
        XCTAssertEqual(v.attentes("c"), ["r1"])
        XCTAssertEqual(v.recevoir("c", .reglee(requestId: "r1", decision: "allow"), ts: 1), [.retirerAttente(chatId: "c", requestId: "r1")])
        XCTAssertTrue(v.attentes("c").isEmpty)
    }

    func testRappelUniqueApresLeSeuil() {
        let v = Veilleur()
        _ = v.recevoir("c", autorisation("r1"), ts: 0)
        XCTAssertTrue(v.rappels(maintenant: 100, seuil: 600).isEmpty)
        let r = v.rappels(maintenant: 660, seuil: 600)
        guard case .rappel(_, _, _, _, let minutes) = r.first else { return XCTFail("rappel attendu") }
        XCTAssertEqual(minutes, 11)
        XCTAssertTrue(v.rappels(maintenant: 1200, seuil: 600).isEmpty)
        XCTAssertTrue(v.rappels(maintenant: 1200, seuil: nil).isEmpty)
    }

    func testSilencieuxNAnnonceRien() {
        let v = Veilleur()
        XCTAssertTrue(v.recevoir("c", autorisation("r1"), ts: 0, silencieux: true).isEmpty)
        XCTAssertEqual(v.attentes("c"), ["r1"])
        v.marquerAnciennes(maintenant: 10_000, seuil: 600)
        XCTAssertTrue(v.rappels(maintenant: 10_000, seuil: 600).isEmpty)
    }

    func testChatsFermesRetires() {
        let v = Veilleur()
        _ = v.recevoir("a", .etat("busy"), ts: 0)
        _ = v.recevoir("b", .etat("busy"), ts: 0)
        XCTAssertEqual(v.garderSeulement(["a"]), [.retirerTout(chatId: "b")])
    }

    func testResume() {
        XCTAssertEqual(Veilleur.resumer("  "), "Prêt pour la suite.")
        XCTAssertEqual(Veilleur.resumer("# Titre\n\nligne   deux"), "Titre ligne deux")
        XCTAssertEqual(Veilleur.resumer(String(repeating: "a", count: 400)).count, 300)
    }

    func testContenuDesNotifications() {
        let a = Notifs.contenu(.attente(chatId: "c", requestId: "r", question: false, texte: "Bash : ls"))
        XCTAssertEqual(a?.texte, "Autorisation : Bash : ls")
        XCTAssertEqual(a?.demande, "r")
        XCTAssertNil(Notifs.contenu(.attente(chatId: "c", requestId: "r", question: true, texte: "?"))?.demande)
        XCTAssertNil(Notifs.contenu(.retirerFin(chatId: "c")))
    }
}

final class PartageTests: XCTestCase {
    func testResume() {
        XCTAssertEqual(Partage(texte: "x", fichiers: []).resume, "Du texte")
        let f = [URL(fileURLWithPath: "/a"), URL(fileURLWithPath: "/b")]
        XCTAssertEqual(Partage(texte: "x", fichiers: f).resume, "2 fichiers et du texte")
    }

    func testLienDePartage() {
        let p = Partage.depuisLien(URL(string: "ccs://partager?titre=Page&url=https%3A%2F%2Fex.fr")!)
        XCTAssertEqual(p?.texte, "Page\nhttps://ex.fr")
        XCTAssertNil(Partage.depuisLien(URL(string: "https://ex.fr")!))
    }

    func testNomLibre() {
        XCTAssertEqual(Partage.nomLibre("rapport.pdf", 1), "rapport.pdf")
        XCTAssertEqual(Partage.nomLibre("rapport.pdf", 2), "rapport (2).pdf")
        XCTAssertEqual(Partage.nomLibre(".env", 3), ".env (3)")
        XCTAssertEqual(Partage.nomLibre("notes", 2), "notes (2)")
    }

    func testComposer() {
        XCTAssertEqual(Partage.composer("brouillon  ", " lien ", ["a.pdf"]), "brouillon\n\nlien\n\nFichier ajouté au dossier du projet : `a.pdf`")
        XCTAssertEqual(Partage.composer("", "", ["a", "b"]), "Fichiers ajoutés au dossier du projet : `a`, `b`")
    }
}
