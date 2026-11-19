import XCTest
@testable import CCS

final class TerminalTests: XCTestCase {
    func testFlechesNormalesEtApplication() {
        XCTAssertEqual(Touches.Fleche.haut.sequence(application: false), "\u{1B}[A")
        XCTAssertEqual(Touches.Fleche.haut.sequence(application: true), "\u{1B}OA")
        XCTAssertEqual(Touches.Fleche.gauche.sequence(application: false), "\u{1B}[D")
    }

    func testFlechesAvecModificateurs() {
        XCTAssertEqual(Touches.Fleche.gauche.sequence(application: true, ctrl: true), "\u{1B}[1;5D")
        XCTAssertEqual(Touches.Fleche.droite.sequence(application: false, alt: true), "\u{1B}[1;3C")
        XCTAssertEqual(Touches.Fleche.bas.sequence(application: false, ctrl: true, alt: true), "\u{1B}[1;7B")
    }

    func testTailleBornee() {
        XCTAssertEqual(Touches.borner(2), Touches.tailleMin)
        XCTAssertEqual(Touches.borner(100), Touches.tailleMax)
        XCTAssertEqual(Touches.borner(14), 14)
    }

    func testMessageDeFin() {
        XCTAssertEqual(Touches.messageFin(0), "\r\n[terminé, code 0]\r\n")
        XCTAssertEqual(Touches.messageFin(-1), "\r\n[terminal fermé]\r\n")
    }

    func testNomDuDossier() {
        XCTAssertEqual(Terminaux.nomDossier("/home/moi/Work/ccs"), "ccs")
        XCTAssertEqual(Terminaux.nomDossier("/home/moi/Work/ccs/"), "ccs")
        XCTAssertEqual(Terminaux.nomDossier("/"), "Terminal")
    }

    func testModelesDuPont() {
        let l = ListeTerminaux(json: .objet(["terms": .tableau([
            .objet(["term_id": .chaine("t1"), "cwd": .chaine("/tmp"), "name": .chaine("tmp")]),
            .objet(["term_id": .chaine("t2")]),
        ])]))
        XCTAssertEqual(l.terms.map { $0.termId }, ["t1", "t2"])
        XCTAssertEqual(l.terms[1].name, "Terminal")
        XCTAssertEqual(TerminalOuvert(json: .objet(["term_id": .chaine("x")])).termId, "x")
        XCTAssertEqual(SortieTerminal(json: .objet(["output": .chaine("$ ")])).output, "$ ")
    }
}
