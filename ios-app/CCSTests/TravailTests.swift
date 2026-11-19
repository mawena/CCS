import XCTest
@testable import CCS

/// Feuille de route, tâches de fond, changements du chat et réglages : la logique sans écran.
final class TravailTests: XCTestCase {
    private func phase(_ faites: Bool...) -> PhaseFeuille {
        let taches: [JSON] = faites.enumerated().map { i, f in .objet(["text": .chaine("t\(i)"), "done": .booleen(f), "line": .de(i + 1)]) }
        return PhaseFeuille(json: .objet(["title": "P", "tasks": .tableau(taches)]))
    }

    func testProgressionEtPhasesOuvertes() {
        let phases = [phase(true, true), phase(true, false, false), phase(), phase(false)]
        XCTAssertEqual(FeuilleRoute.progression(phases[0]).description, "2/2")
        XCTAssertEqual(FeuilleRoute.progression(phases[1]).fraction, 1.0 / 3, accuracy: 1e-9)
        XCTAssertEqual(FeuilleRoute.progression(phases[2]).fraction, 0)
        XCTAssertEqual(FeuilleRoute.ouvertes(phases), [1, 3])
        XCTAssertEqual(FeuilleRoute.enCours(phases), 1)
        XCTAssertNil(FeuilleRoute.enCours([phase(true)]))
        XCTAssertEqual(FeuilleRoute.niveau(7), 3)
        XCTAssertEqual(FeuilleRoute.niveau(-1), 0)
    }

    private func tache(_ etat: String, id: String? = nil, _ autres: [String: JSON] = [:]) -> TacheFond {
        var o: [String: JSON] = ["id": .chaine(id ?? etat), "message": "Ranger le dépôt\nen détail", "cwd": "/home/c/Work/ccs", "state": .chaine(etat)]
        o.merge(autres) { _, b in b }
        return TacheFond(json: .objet(o))
    }

    func testSousTitresDesTaches() {
        XCTAssertEqual(TachesFond.sousTitre(tache("queued", ["when": "nuit"])), "En attente · cette nuit · ~/Work/ccs")
        XCTAssertEqual(TachesFond.sousTitre(tache("queued", ["when": "03:30"])), "En attente · à 03:30 · ~/Work/ccs")
        XCTAssertEqual(TachesFond.sousTitre(tache("waiting", ["note": "limite du compte"])), "À reprendre (limite atteinte) · limite du compte · ~/Work/ccs")
        XCTAssertEqual(TachesFond.sousTitre(tache("failed", ["error": "délai dépassé"])), "Échouée · délai dépassé · ~/Work/ccs")
        XCTAssertEqual(TachesFond.sousTitre(tache("done", ["finished": 1000]), maintenant: 1000 + 7200), "Finie · il y a 2 h · ~/Work/ccs")
        XCTAssertEqual(TachesFond.titre(tache("done")), "Ranger le dépôt")
        XCTAssertEqual(TachesFond.libelleDroits("modifications"), "Modifications des fichiers")
    }

    func testFiltresDesTaches() {
        let l = [tache("done"), tache("failed"), tache("running", id: "r1"), tache("queued", id: "q2")]
        XCTAssertEqual(TachesFond.filtreInitial(l), "actives")
        XCTAssertEqual(TachesFond.filtreInitial([tache("done")]), "done")
        XCTAssertEqual(TachesFond.filtreInitial([]), "actives")
        XCTAssertEqual(TachesFond.filtrer(l, "actives").map { $0.id }, ["q2", "r1"])      // plus récentes d'abord
        XCTAssertEqual(TachesFond.nombre(l, TachesFond.filtres[2]), 1)
        XCTAssertTrue(TachesFond.active(tache("waiting")))
    }

    func testFormulaireDeTache() {
        XCTAssertEqual(TachesFond.dossier(" ~/Work/x ", home: "/home/c"), "/home/c/Work/x")
        XCTAssertEqual(TachesFond.dossier("~/x", home: ""), "~/x")
        XCTAssertEqual(TachesFond.verifier(dossier: "", message: "m", quand: "quota", heure: ""), "Indique le dossier du projet.")
        XCTAssertEqual(TachesFond.verifier(dossier: "/d", message: "  ", quand: "quota", heure: ""), "Écris ce que Claude doit faire.")
        XCTAssertEqual(TachesFond.verifier(dossier: "/d", message: "m", quand: "heure", heure: "25:00"), "Choisis l'heure (HH:MM).")
        XCTAssertNil(TachesFond.verifier(dossier: "/d", message: "m", quand: "heure", heure: "3:05"))
        XCTAssertEqual(TachesFond.quandEnvoye("heure", heure: "3:05"), "03:05")
        XCTAssertEqual(TachesFond.quandEnvoye("nuit", heure: "3:05"), "nuit")
    }

    func testDiffUnifieNumerote() {
        let d = "--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,3 @@\n un\n-deux\n+DEUX\n trois\n\\ No newline at end of file\n@@ -10 +10,2 @@\n+neuf\n dix\n"
        let l = ChangementsChat.lignes(d)
        XCTAssertEqual(l[0].genre, .morceau)
        XCTAssertEqual(l[1], Diff.Ligne(genre: .contexte, texte: "un", ancien: 1, nouveau: 1))
        XCTAssertEqual(l[2], Diff.Ligne(genre: .retrait, texte: "deux", ancien: 2, nouveau: nil))
        XCTAssertEqual(l[3], Diff.Ligne(genre: .ajout, texte: "DEUX", ancien: nil, nouveau: 2))
        XCTAssertEqual(l[4], Diff.Ligne(genre: .contexte, texte: "trois", ancien: 3, nouveau: 3))
        XCTAssertEqual(l[5].genre, .morceau)
        XCTAssertEqual(l[6], Diff.Ligne(genre: .ajout, texte: "neuf", ancien: nil, nouveau: 10))
        XCTAssertEqual(l[7], Diff.Ligne(genre: .contexte, texte: "dix", ancien: 10, nouveau: 11))
        XCTAssertEqual(l.count, 8)
        XCTAssertTrue(ChangementsChat.lignes("").isEmpty)
    }

    func testTexteDuRetourArriere() {
        let plan = PlanRetour(json: JSON.lire("""
            {"steps": [{"path": "/p/a.txt", "deleted": true}, {"path": "/p/src/b.kt", "user_edited": true}, {"path": "/ailleurs/c"}],
             "skipped": ["/etc/x"]}
            """)!)
        XCTAssertEqual(ChangementsChat.texteRetour(plan, "/p"),
                       "a.txt (supprimé)\nsrc/b.kt (modifié depuis par toi ?)\n/ailleurs/c\n\nLaissés tels quels (hors des dossiers permis) :\n/etc/x\n\nC'est définitif.")
        XCTAssertEqual(ChangementsChat.titreRetour(plan), "Revenir avant ce message ? (3 fichiers)")
        XCTAssertEqual(ChangementsChat.titreRetour(PlanRetour(json: JSON.lire(#"{"steps": [{"path": "/p/a"}]}"#)!)), "Revenir avant ce message ? (1 fichier)")
        let cree = FichierChange(json: .objet(["kind": "created"]))
        XCTAssertEqual(ChangementsChat.texteAnnulation(cree), "Le fichier sera supprimé (Claude l'a créé). C'est définitif.")
        XCTAssertEqual(ChangementsChat.genre(cree), "créé")
    }

    private let r = JSON.lire("""
        {"chat":{"auto_clear":true,"rights":"manual","idle_suspend_min":30},"sessions":{"idle_hours":0.5},
         "alerts":{"quiet":{"start":"22:00"}},"phone":{"topic":""}}
        """)!

    func testLireEtEcrireUnChemin() {
        XCTAssertTrue(DefReglages.booleen(DefReglages.lire(r, "chat.auto_clear")))
        XCTAssertFalse(DefReglages.booleen(DefReglages.lire(r, "chat.absent")))
        XCTAssertNil(DefReglages.lire(r, "x.y.z"))
        XCTAssertEqual(DefReglages.texte(DefReglages.lire(r, "alerts.quiet.start")), "22:00")
        XCTAssertEqual(DefReglages.texte(DefReglages.lire(r, "chat.idle_suspend_min")), "30")
        XCTAssertEqual(DefReglages.texte(DefReglages.lire(r, "sessions.idle_hours")), "0.5")
        let e = DefReglages.ecrire(r, "alerts.quiet.end", "07:00")
        XCTAssertEqual(DefReglages.texte(DefReglages.lire(e, "alerts.quiet.end")), "07:00")
        XCTAssertEqual(DefReglages.texte(DefReglages.lire(e, "alerts.quiet.start")), "22:00")
        XCTAssertEqual(DefReglages.ecrire(.vide, "a.b", false).texteCompact, #"{"a":{"b":false}}"#)
    }

    func testNombresEtHeures() {
        XCTAssertEqual(DefReglages.nombre(" 42 ", min: 1, max: 100, entier: false).valeur, 42)
        XCTAssertEqual(DefReglages.nombre("2,5", min: 1, max: 100, entier: false).valeur, 2.5)
        XCTAssertEqual(DefReglages.nombre("abc", min: 1, max: 100, entier: false).erreur, "Entre un nombre.")
        XCTAssertEqual(DefReglages.nombre("0", min: 1, max: 100, entier: false).erreur, "Entre 1 et 100.")
        XCTAssertEqual(DefReglages.nombre("2.5", min: 1, max: 10, entier: true).erreur, "Entre un nombre entier.")
        XCTAssertEqual(DefReglages.heure("7:05"), "07:05")
        XCTAssertNil(DefReglages.heure("24:00"))
        XCTAssertNil(DefReglages.heure("7h"))
    }

    func testTousLesReglagesDuWeb() {
        let chemins = (DefReglages.groupes + [DefReglages.telephone]).flatMap { g in g.reglages.map { $0.chemin } }
        XCTAssertEqual(chemins.count, Set(chemins).count)
        XCTAssertTrue(chemins.contains("chat.auto_clear"))
        XCTAssertEqual(chemins.count, 44)
    }
}
