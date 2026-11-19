import XCTest
@testable import CCS

final class FichiersTests: XCTestCase {
    func testChemins() {
        XCTAssertEqual(Fichiers.nom("/a/b.txt"), "b.txt")
        XCTAssertEqual(Fichiers.nom("/a/"), "a")
        XCTAssertEqual(Fichiers.nom("/"), "/")
        XCTAssertEqual(Fichiers.parent("/a/b"), "/a")
        XCTAssertEqual(Fichiers.parent("/a"), "/")
        XCTAssertEqual(Fichiers.joindre("/a/b/", "c"), "/a/b/c")
        XCTAssertEqual(Fichiers.joindre("/a", ""), "/a")
        XCTAssertEqual(Fichiers.relatif("/home/c", "/home/c"), "")
        XCTAssertEqual(Fichiers.relatif("/home/c/x/y", "/home/c"), "x/y")
        XCTAssertNil(Fichiers.relatif("/home/cc/x", "/home/c"))
        XCTAssertTrue(Fichiers.sous("/srv/site", "/srv"))
        XCTAssertFalse(Fichiers.sous("/srvx", "/srv"))
    }

    func testRacineEtAriane() {
        let racines = ["/home/c", "/var/www", "/srv"]
        XCTAssertEqual(Fichiers.racineDe("/var/www/site/a", racines, "/home/c"), "/var/www")
        XCTAssertEqual(Fichiers.racineDe("/etc", racines, "/home/c"), "/home/c")
        let fil = Fichiers.ariane("/home/c/Work/ccs", "/home/c", "/home/c")
        XCTAssertEqual(fil.map { $0.nom }, ["Personnel", "Work", "ccs"])
        XCTAssertEqual(fil.map { $0.chemin }, ["/home/c", "/home/c/Work", "/home/c/Work/ccs"])
        XCTAssertEqual(Fichiers.ariane("/srv", "/srv", "/home/c").map { $0.nom }, ["/srv"])
    }

    func testGenresEtLangues() {
        XCTAssertEqual(Fichiers.genre("src", dossier: true), .dossier)
        XCTAssertEqual(Fichiers.genre("Main.KT"), .code)
        XCTAssertEqual(Fichiers.genre("Makefile"), .code)
        XCTAssertEqual(Fichiers.genre(".bashrc"), .config)
        XCTAssertEqual(Fichiers.genre("logo.svg"), .image)
        XCTAssertEqual(Fichiers.genre("donnees"), .fichier)
        XCTAssertEqual(Fichiers.langue("A.kt"), "kt")
        XCTAssertEqual(Fichiers.langue("Makefile"), "make")
        XCTAssertEqual(Fichiers.langue("ccs.service"), "ini")
        XCTAssertEqual(Fichiers.langue("NOTES.markdown"), "md")
        XCTAssertTrue(Fichiers.estMarkdown("README.md"))
        XCTAssertFalse(Fichiers.estMarkdown("md"))
    }

    func testTaillesEtTextes() {
        XCTAssertEqual(Fichiers.taille(512), "512 o")
        XCTAssertEqual(Fichiers.taille(12 * 1024), "12 Ko")
        XCTAssertEqual(Fichiers.taille(3_670_016), "3,5 Mo")
        XCTAssertEqual(Fichiers.texteSuppression(dossier: true, nombre: 0, octets: 0), "Ce dossier vide sera supprimé.")
        XCTAssertTrue(Fichiers.texteSuppression(dossier: true, nombre: 4, octets: 0).contains("4 éléments"))
        XCTAssertTrue(Fichiers.texteSuppression(dossier: false, nombre: 0, octets: 2048).contains("2 Ko"))
    }

    func testNoms() {
        XCTAssertNil(Fichiers.nomRefuse("a.txt"))
        XCTAssertNotNil(Fichiers.nomRefuse(" "))
        XCTAssertNotNil(Fichiers.nomRefuse(".."))
        XCTAssertNotNil(Fichiers.nomRefuse("a/b"))
        XCTAssertNotNil(Fichiers.nomRefuse(String(repeating: "é", count: 128)))
    }

    func testMorceauxEtLignes() {
        XCTAssertEqual(Fichiers.morceaux(0).map { $0.longueur }, [0])
        let m = Fichiers.morceaux(25, morceau: 10)
        XCTAssertEqual(m.map { $0.debut }, [0, 10, 20])
        XCTAssertEqual(m.map { $0.longueur }, [10, 10, 5])
        XCTAssertEqual(Fichiers.morceaux(10, morceau: 10).count, 1)
        XCTAssertEqual(Fichiers.lignes("a\r\nb\n"), ["a", "b"])
        XCTAssertEqual(Fichiers.lignes(""), [""])
        XCTAssertEqual(Fichiers.lignes("a\n\n"), ["a", ""])
    }

    func testModelesEtTamponExact() {
        let l = ListeFichiers(json: JSON.lire(#"{"entries": [{"name": "src", "path": "src", "dir": true, "mark": ""}, {"name": "a.kt", "path": "a.kt", "dir": false, "mark": "M"}], "truncated": true}"#)!)
        XCTAssertEqual(l.entries.count, 2)
        XCTAssertTrue(l.entries[0].dir)
        XCTAssertEqual(l.entries[1].mark, "M")
        XCTAssertTrue(l.truncated)
        let r = FichierLu(json: JSON.lire(#"{"kind": "text", "stamp": [1763500000123456789, 42], "text": "x", "encoding": "utf-8"}"#)!)
        XCTAssertEqual(r.kind, "text")
        // le tampon repart tel quel vers files.write (grand entier compris)
        XCTAssertEqual(r.stamp?.texteCompact, "[1763500000123456789,42]")
        let m = MorceauFichier(json: JSON.lire(#"{"size": 300000000, "data": "YQ==", "done": false}"#)!)
        XCTAssertEqual(m.size, 300_000_000)
        XCTAssertEqual(InfoFichier(json: JSON.lire(#"{"dir": true, "count": 7, "size": 0}"#)!).count, 7)
        XCTAssertEqual(RacinesFichiers(json: JSON.lire(#"{"home": "/home/c", "roots": ["/home/c", "/srv"]}"#)!).roots, ["/home/c", "/srv"])
    }

    func testColoration() {
        let j = Coloration.jetons("let x = \"a\" // note\n42", "swift")
        XCTAssertEqual(j.first, Coloration.Jeton(debut: 0, fin: 3, genre: .motCle))
        XCTAssertTrue(j.contains(Coloration.Jeton(debut: 8, fin: 11, genre: .chaine)))
        XCTAssertTrue(j.contains(Coloration.Jeton(debut: 12, fin: 19, genre: .commentaire)))
        XCTAssertTrue(j.contains(Coloration.Jeton(debut: 20, fin: 22, genre: .nombre)))
        // « a#b » n'est pas un commentaire en shell ; « # x » l'est
        XCTAssertTrue(Coloration.jetons("a#b", "sh").isEmpty)
        XCTAssertEqual(Coloration.jetons("# x", "sh"), [Coloration.Jeton(debut: 0, fin: 3, genre: .commentaire)])
        let d = Coloration.jetons("@@ -1 +1 @@\n-a\n+b", "diff").map { $0.genre }
        XCTAssertEqual(d, [.titre, .retrait, .ajout])
        let lignes = LignesColorees.colorer(["let a", "b"], "swift", sombre: false)
        XCTAssertEqual(lignes.map { String($0.characters) }, ["let a", "b"])
    }
}
