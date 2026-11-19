import XCTest
@testable import CCS

final class GitVueTests: XCTestCase {
    private let etat = EtatGit(json: JSON.lire("""
        {"repo": true, "root": "/p", "branch": {"name": "develop", "upstream": "origin/develop", "ahead": 2, "behind": 0},
         "files": [{"path": "a.kt", "staged": "M", "unstaged": "."},
                   {"path": "b.kt", "staged": "M", "unstaged": "M"},
                   {"path": "c.kt", "staged": ".", "unstaged": "D"},
                   {"path": "n.txt", "staged": "?", "unstaged": "?"},
                   {"path": "r.kt", "staged": "R", "unstaged": ".", "orig_path": "q.kt"}],
         "truncated": false, "proposed": "feat: x", "last_message": "fix: y", "inconnu": 1}
        """)!)

    func testLectureEtGroupes() {
        XCTAssertEqual(etat.files[4].ancien, "q.kt")
        XCTAssertEqual(etat.dernierMessage, "fix: y")
        let g = GitVue.groupes(etat)
        XCTAssertEqual(g.map { $0.titre }, ["Indexés", "Modifiés", "Non suivis"])
        XCTAssertEqual(g[0].fichiers.map { $0.path }, ["a.kt", "b.kt", "r.kt"])
        XCTAssertEqual(g[1].fichiers.map { $0.path }, ["b.kt", "c.kt"])
        XCTAssertEqual(g[2].methode, "git.stage")
        XCTAssertEqual(g[2].lettre(etat.files[3]), "?")
        XCTAssertTrue(GitVue.peutCommit(etat, amend: false))
        var e = etat
        e.files = [FichierGit("n", "?", "?")]
        XCTAssertFalse(GitVue.peutCommit(e, amend: false))
        e.files = []
        XCTAssertTrue(GitVue.peutCommit(e, amend: true))
        XCTAssertTrue(GitVue.groupes(e).isEmpty)
    }

    func testClesGardees() {
        let ouvertes: Set<String> = [GitVue.cle(.index, "a.kt"), GitVue.cle(.travail, "a.kt"),
                                     GitVue.cle(.travail, "n.txt"), GitVue.cle(.index, "parti.kt")]
        XCTAssertEqual(GitVue.clesGardees(ouvertes, etat), ["Index:a.kt", "Travail:n.txt"])
    }

    func testSynchroEtTextes() {
        XCTAssertEqual(GitVue.synchro(etat.branch), "origin/develop · ↑2")
        XCTAssertEqual(GitVue.synchro(BrancheGit("m", "o/m", 1, 3)), "o/m · ↑1 ↓3")
        XCTAssertEqual(GitVue.synchro(BrancheGit("m", "o/m")), "o/m · à jour")
        XCTAssertEqual(GitVue.synchro(BrancheGit("m")), "pas de suivi distant")
        XCTAssertEqual(GitVue.textePush(etat.branch), "2 commit(s) partiront vers origin/develop.")
        XCTAssertTrue(GitVue.textePush(BrancheGit("m")).contains("premier push"))
        XCTAssertEqual(GitVue.marque("M"), "modifié")
        XCTAssertEqual(GitVue.marque("X"), "X")
    }

    func testDiffsEnLignes() {
        let r = ReponseDiff(json: JSON.lire("""
            {"diff": {"path": "a.kt", "old_path": null, "binary": false, "new_file": false, "deleted": false,
              "hunks": [{"header": "@@ -1,2 +1,2 @@", "lines": [
                {"kind": " ", "text": "x", "old_no": 1, "new_no": 1},
                {"kind": "-", "text": "a", "old_no": 2, "new_no": null},
                {"kind": "+", "text": "b", "old_no": null, "new_no": 2}]}],
              "truncated": false, "too_big": false}}
            """)!)
        guard let d = r.diff else { return XCTFail("diff attendu") }
        XCTAssertNil(GitVue.sansDiff(d))
        XCTAssertTrue(GitVue.parMorceau("M", d))
        XCTAssertFalse(GitVue.parMorceau("?", d))
        var neuf = d
        neuf.nouveau = true
        XCTAssertFalse(GitVue.parMorceau("A", neuf))
        let l = GitVue.lignes(d.hunks[0])
        XCTAssertEqual(l.map { $0.genre }, [.contexte, .retrait, .ajout])
        XCTAssertEqual(l[1].ancien, 2)
        XCTAssertNil(l[1].nouveau)
        let f = GitVue.fichier(d)
        XCTAssertEqual(f.lignes[0].genre, .morceau)
        XCTAssertEqual(f.ajouts, 1)
        var gros = d
        gros.tropGros = true
        XCTAssertEqual(GitVue.sansDiff(gros), "Fichier trop gros pour être montré.")
        var binaire = d
        binaire.binary = true
        XCTAssertEqual(GitVue.sansDiff(binaire), "Fichier binaire : pas de diff.")
        XCTAssertEqual(GitVue.sansDiff(nil), "Pas de différence à montrer.")
        XCTAssertEqual(GitVue.etatFichier(DiffGit(path: "a.kt", ancien: "b.kt")), "renommé (b.kt)")
        XCTAssertEqual(GitVue.etatFichier(DiffGit(path: "a.kt", ancien: "a.kt")), "modifié")
    }

    func testCommitEtRefs() {
        let d = DetailCommit(json: JSON.lire("""
            {"commit": {"id": "abcdef0123", "short": "abcdef01", "author": "C", "email": "c@x", "time": 1763500000,
                        "subject": "feat", "parents": ["1"], "body": "corps"},
             "files": [{"path": "a", "hunks": [], "truncated": true}], "truncated": false}
            """)!)
        XCTAssertEqual(d.commit.time, 1_763_500_000)
        XCTAssertTrue(d.files[0].truncated)
        let g = GitVue.refs([RefGit("HEAD", "head", "1"), RefGit("v1", "tag", "1"), RefGit("v2", "tag", "2"),
                             RefGit("main", "branch", "1"), RefGit("Dev", "branch", "2"), RefGit("origin/main", "remote", "1")])
        XCTAssertEqual(g.map { $0.titre }, ["Branches", "Branches distantes", "Tags"])
        XCTAssertEqual(g[0].refs.map { $0.name }, ["Dev", "main"])
        XCTAssertEqual(g[2].refs.map { $0.name }, ["v2", "v1"])
    }
}
