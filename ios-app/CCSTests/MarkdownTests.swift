import XCTest
@testable import CCS

final class MarkdownTests: XCTestCase {
    private func seg(_ t: String, gras: Bool = false, italique: Bool = false, code: Bool = false, barre: Bool = false, lien: String? = nil) -> Markdown.Segment {
        return Markdown.Segment(texte: t, gras: gras, italique: italique, code: code, barre: barre, lien: lien)
    }

    func testStylesEnLigne() {
        XCTAssertEqual(Markdown.enLigne("un **gras** et *penché*"),
                       [seg("un "), seg("gras", gras: true), seg(" et "), seg("penché", italique: true)])
        XCTAssertEqual(Markdown.enLigne("le `code` ici"), [seg("le "), seg("code", code: true), seg(" ici")])
        XCTAssertEqual(Markdown.enLigne("~~barré~~"), [seg("barré", barre: true)])
    }

    func testSoulignesDansUnMotNeSontPasDeLItalique() {
        XCTAssertEqual(Markdown.texte(Markdown.enLigne("nom_de_fichier.txt")), "nom_de_fichier.txt")
        XCTAssertEqual(Markdown.enLigne("nom_de_fichier.txt"), [seg("nom_de_fichier.txt")])
    }

    func testLiens() {
        XCTAssertEqual(Markdown.enLigne("[site](https://x.fr)"), [seg("site", lien: "https://x.fr")])
        let nu = Markdown.enLigne("voir https://x.fr/a.")
        XCTAssertEqual(nu.first(where: { $0.lien != nil })?.lien, "https://x.fr/a")
        XCTAssertEqual(Markdown.rognerUrl("https://fr.wikipedia.org/wiki/A_(b))."), "https://fr.wikipedia.org/wiki/A_(b)")
    }

    func testTitresParagraphesEtRegle() {
        let b = Markdown.analyser("# Titre\n\nUn paragraphe\nsur deux lignes.\n\n---\n")
        XCTAssertEqual(b.count, 3)
        XCTAssertEqual(b[0], .titre(niveau: 1, contenu: [seg("Titre")]))
        if case .paragraphe(let s) = b[1] {
            XCTAssertTrue(Markdown.texte(s).contains("Un paragraphe"))
            XCTAssertTrue(Markdown.texte(s).contains("deux lignes."))
        } else {
            XCTFail("paragraphe attendu")
        }
        XCTAssertEqual(b[2], .regle)
    }

    func testBlocDeCode() {
        let b = Markdown.analyser("```swift\nlet a = 1\n**pas du gras**\n```")
        XCTAssertEqual(b, [.code(langue: "swift", texte: "let a = 1\n**pas du gras**")])
    }

    func testBlocDeCodeNonFermeVaJusquAuBout() {
        let b = Markdown.analyser("avant\n\n```\nen cours")
        XCTAssertEqual(b.last, .code(langue: "", texte: "en cours"))
    }

    func testListesEtCases() {
        let b = Markdown.analyser("- un\n- [x] fait\n  - dedans\n1. premier")
        guard b.count >= 1, case .liste(let e) = b[0] else { return XCTFail("liste attendue") }
        XCTAssertEqual(e.first?.contenu, [seg("un")])
        XCTAssertEqual(e.count >= 3, true)
        XCTAssertEqual(e[1].coche, true)
        XCTAssertEqual(e[2].niveau, 1)
        let tout = b.flatMap { bloc -> [Markdown.Element] in
            if case .liste(let x) = bloc { return x }
            return []
        }
        XCTAssertTrue(tout.contains { $0.marque == "1." })
    }

    func testCitation() {
        let b = Markdown.analyser("> cité\n> encore\n\naprès")
        guard case .citation(let dedans) = b[0] else { return XCTFail("citation attendue") }
        XCTAssertEqual(dedans.count, 1)
        XCTAssertEqual(b.count, 2)
    }

    func testTableau() {
        let b = Markdown.analyser("| a | b |\n|---|:-:|\n| 1 | **2** |")
        guard case .tableau(let entetes, let lignes) = b[0] else { return XCTFail("tableau attendu") }
        XCTAssertEqual(entetes, [[seg("a")], [seg("b")]])
        XCTAssertEqual(lignes, [[[seg("1")], [seg("2", gras: true)]]])
    }
}
