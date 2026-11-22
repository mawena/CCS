import XCTest
@testable import CCS

final class TexteParleTests: XCTestCase {
    func testTitresGrasItalique() {
        XCTAssertEqual(TexteParle.nettoyer("# Titre\n\nDu **gras** et de l'*italique*."), "Titre.\n\nDu gras et de l'italique.")
        XCTAssertEqual(TexteParle.nettoyer("## Étapes ##"), "Étapes.")
        XCTAssertEqual(TexteParle.nettoyer("### Fini !"), "Fini !")
    }

    func testLiensImagesEtCode() {
        XCTAssertEqual(TexteParle.nettoyer("Voir [la doc](https://x.fr) et `npm test`."), "Voir la doc et npm test.")
        XCTAssertEqual(TexteParle.nettoyer("![logo](a.png) ok"), "logo ok")
        XCTAssertEqual(TexteParle.nettoyer("le `__init__` reste"), "le __init__ reste")
        XCTAssertEqual(TexteParle.nettoyer("a `b"), "a `b")
    }

    func testBlocsDeCode() {
        XCTAssertEqual(TexteParle.nettoyer("Avant\n```swift\nlet x = 1\n```\nAprès"), "Avant\nbloc de code.\nAprès")
        XCTAssertEqual(TexteParle.nettoyer("~~~\n# pas un titre\n~~~"), "bloc de code.")
        XCTAssertEqual(TexteParle.nettoyer("Début\n```\nnon fermé"), "Début\nbloc de code.")
    }

    func testListesCitationsFiletsTableaux() {
        XCTAssertEqual(TexteParle.nettoyer("- un\n* deux\n- [x] fait"), "un\ndeux\nfait")
        XCTAssertEqual(TexteParle.nettoyer("> cité\n\n---\n\nfin"), "cité\n\nfin")
        XCTAssertEqual(TexteParle.nettoyer("| a | b |\n|---|:---:|\n| 1 | 2 |"), "a, b\n1, 2")
    }

    func testSoulignesDesNomsGardes() {
        XCTAssertEqual(TexteParle.nettoyer("le fichier mon_fichier_test.swift et _ceci_"), "le fichier mon_fichier_test.swift et ceci")
    }

    func testJoindreLaDictee() {
        XCTAssertEqual(TexteParle.joindre("", " bonjour "), "bonjour")
        XCTAssertEqual(TexteParle.joindre("Salut", "ça va"), "Salut ça va")
        XCTAssertEqual(TexteParle.joindre("Salut\n", "ça va"), "Salut\nça va")
        XCTAssertEqual(TexteParle.joindre("Salut", "  "), "Salut")
    }
}
