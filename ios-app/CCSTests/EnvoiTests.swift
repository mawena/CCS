import XCTest
@testable import CCS

final class EnvoiTests: XCTestCase {
    func testCommandesSlash() {
        XCTAssertTrue(Envoi.estCommandeSlash("/clear"))
        XCTAssertTrue(Envoi.estCommandeSlash("  /compact garde le plan"))
        XCTAssertFalse(Envoi.estCommandeSlash("/"))
        XCTAssertFalse(Envoi.estCommandeSlash("//x"))
        XCTAssertFalse(Envoi.estCommandeSlash("/1"))
        XCTAssertFalse(Envoi.estCommandeSlash("bonjour /clear"))
        XCTAssertFalse(Envoi.estCommandeSlash(nil))
    }

    func testCommandesShell() {
        XCTAssertEqual(Envoi.commandeShell("!ls -la", images: 0), "ls -la")
        XCTAssertEqual(Envoi.commandeShell("  ! git status ", images: 0), "git status")
        XCTAssertNil(Envoi.commandeShell("!", images: 0))
        XCTAssertNil(Envoi.commandeShell("!ls", images: 1))
        XCTAssertNil(Envoi.commandeShell("ls", images: 0))
    }

    func testPreparerUneCommandeLaissePasserCitationEtNotes() {
        let c = Citation.Cite(auteur: .claude, texte: "avant")
        let p = Envoi.preparer(" /clear ", images: 0, citation: c, notesShell: ["note"])
        XCTAssertEqual(p, Envoi.Pret(envoye: "/clear", montre: "/clear", commande: true))
    }

    func testPreparerAvecCitationEtNotes() {
        let c = Citation.Cite(auteur: .claude, texte: "ligne 1\nligne 2")
        let p = Envoi.preparer("ma réponse", images: 0, citation: c, notesShell: ["N1 ", "N2 "])
        XCTAssertFalse(p.commande)
        XCTAssertTrue(p.envoye.hasPrefix("> **Claude :**\n> ligne 1\n> ligne 2"))
        XCTAssertTrue(p.envoye.hasSuffix("N1 N2 ma réponse"))
        XCTAssertTrue(p.montre.hasSuffix("ma réponse"))
        XCTAssertFalse(p.montre.contains("N1"))
        let sans = Envoi.preparer("salut", images: 0, citation: nil, notesShell: [])
        XCTAssertEqual(sans, Envoi.Pret(envoye: "salut", montre: "salut", commande: false))
    }

    func testCompleterLesCommandes() {
        let cmds = [CommandeSlash(nom: "clear"), CommandeSlash(nom: "compact"), CommandeSlash(nom: "context"), CommandeSlash(nom: "agents")]
        XCTAssertEqual(Envoi.completer("/c", cmds).map { $0.nom }, ["clear", "compact", "context"])
        XCTAssertEqual(Envoi.completer("/ent", cmds).map { $0.nom }, ["agents"])
        XCTAssertEqual(Envoi.completer("/clear ", cmds), [])
        XCTAssertEqual(Envoi.completer("clear", cmds), [])
        XCTAssertEqual(Envoi.completer("/", cmds, max: 2).count, 2)
    }

    func testCitationAllerRetour() {
        let compose = Citation.composer(.moi, "question\n\nsuite", "ma réponse")
        let d = Citation.decouper(compose)
        XCTAssertEqual(d?.auteur, .moi)
        XCTAssertEqual(d?.texte, "question\n\nsuite")
        XCTAssertEqual(d?.corps, "ma réponse")
        XCTAssertNil(Citation.decouper("texte simple"))
        XCTAssertEqual(Citation.texteSource(compose), "ma réponse")
        XCTAssertEqual(Citation.composer(nil, "x", "corps"), "corps")
    }

    func testCitationDUnMessageLong() {
        let long = String(repeating: "mot ", count: 600)
        let c = Citation.de(.claude, long)
        XCTAssertNotNil(c)
        XCTAssertTrue((c?.texte ?? "").hasSuffix(Citation.coupe))
        XCTAssertLessThanOrEqual((c?.texte ?? "").count, Citation.maxCite + Citation.coupe.count)
        XCTAssertNil(Citation.de(.moi, "   "))
        XCTAssertEqual(Citation.uneLigne("a\n  b\tc"), "a b c")
    }

    func testEtiquettes() {
        XCTAssertEqual(Etiquettes.lire("important, à revoir,, Important ,"), ["important", "à revoir"])
        XCTAssertEqual(Etiquettes.nettoyer("  deux   mots "), "deux mots")
        XCTAssertEqual(Etiquettes.nettoyer(String(repeating: "x", count: 50)).count, Etiquettes.maxCar)
        let m: [String: EntreeEtiquettes] = [
            "b": EntreeEtiquettes(etiquettes: ["zut", "Alpha"], ts: 2),
            "a": EntreeEtiquettes(etiquettes: ["alpha"], ts: 1),
        ]
        let g = Etiquettes.parEtiquette(m)
        XCTAssertEqual(g.map { $0.etiquette }, ["alpha", "zut"])
        XCTAssertEqual(g[0].messages.map { $0.id }, ["a", "b"])
    }

    func testAlerteContexte() {
        let m = MesureContexte(pourcentage: 80, total: 100_000, maximum: 200_000, auto: false)
        XCTAssertEqual(AlerteContexte.decider(m, actif: true, seuil: 90_000, dejaLourd: false),
                       AlerteContexte.Decision(lourd: true, gain: 80_000))
        XCTAssertEqual(AlerteContexte.decider(m, actif: true, seuil: 90_000, dejaLourd: true).gain, nil)
        XCTAssertFalse(AlerteContexte.decider(m, actif: false, seuil: 90_000, dejaLourd: false).lourd)
        let auto = MesureContexte(pourcentage: 80, total: 100_000, maximum: 200_000, auto: true)
        XCTAssertFalse(AlerteContexte.decider(auto, actif: true, seuil: 1, dejaLourd: false).lourd)
    }

    func testDiffParLignes() {
        let l = Diff.parLignes("a\nb\nc", "a\nB\nc")
        XCTAssertEqual(l.filter { $0.genre == .retrait }.map { $0.texte }, ["b"])
        XCTAssertEqual(l.filter { $0.genre == .ajout }.map { $0.texte }, ["B"])
        XCTAssertEqual(l.filter { $0.genre == .contexte }.map { $0.texte }, ["a", "c"])
    }

    func testDiffDUnOutilEdit() {
        let e: JSON = ["file_path": "/p/x.txt", "old_string": "un", "new_string": "deux\ntrois"]
        let d = Diff.deOutil("Edit", e)
        XCTAssertEqual(d?.chemin, "/p/x.txt")
        XCTAssertEqual(d?.ajouts, 2)
        XCTAssertEqual(d?.retraits, 1)
        XCTAssertNil(Diff.deOutil("Bash", ["command": "ls"]))
    }

    func testTypeDImage() {
        XCTAssertEqual(typeImage(Data([0xFF, 0xD8, 0xFF, 0xE0])), "image/jpeg")
        XCTAssertEqual(typeImage(Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])), "image/png")
        XCTAssertEqual(typeImage(Data("GIF89a".utf8)), "image/gif")
        XCTAssertNil(typeImage(Data("bonjour".utf8)))
    }
}
