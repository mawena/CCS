import XCTest
@testable import CCS

final class FilChatTests: XCTestCase {
    private func ev(_ o: [String: JSON]) -> EvChat { return EvChat.lire(.objet(o)) }

    private func textes(_ f: FilChat) -> [String] { return f.fil.elements.map { LigneFil.texte($0) } }

    func testLesDeltasSAccumulentDansUneSeuleBulle() {
        let f = FilChat()
        _ = f.recevoir(1, ev(["type": "TextDelta", "msg_id": "m1", "text": "Bon"]))
        _ = f.recevoir(2, ev(["type": "TextDelta", "msg_id": "m1", "text": "jour"]))
        XCTAssertEqual(f.fil.taille, 1)
        _ = f.recevoir(3, ev(["type": "AssistantText", "msg_id": "m1", "text": "Bonjour !"]))
        XCTAssertEqual(textes(f), ["Bonjour !"])
        if case .claude(let m) = f.fil.elements[0] {
            XCTAssertTrue(m.fini)
            XCTAssertEqual(m.msgId, "m1")
        } else {
            XCTFail("bulle de Claude attendue")
        }
    }

    func testUnNumeroDejaVuEstIgnore() {
        let f = FilChat()
        _ = f.recevoir(5, ev(["type": "Notice", "text": "un"]))
        _ = f.recevoir(5, ev(["type": "Notice", "text": "deux"]))
        _ = f.recevoir(4, ev(["type": "Notice", "text": "trois"]))
        XCTAssertEqual(f.fil.taille, 1)
        XCTAssertEqual(f.seq, 5)
    }

    func testOutilLancePuisFini() {
        let f = FilChat()
        _ = f.recevoir(1, ev(["type": "ToolUse", "tool_id": "t1", "name": "Bash", "input": ["command": "ls -la"]]))
        guard case .outil(let o) = f.fil.elements[0] else { return XCTFail("outil attendu") }
        XCTAssertEqual(o.cible, "ls -la")
        XCTAssertFalse(o.fini)
        _ = f.recevoir(2, ev(["type": "ToolResult", "tool_id": "t1", "text": "a\nb", "is_error": true]))
        guard case .outil(let o2) = f.fil.elements[0] else { return XCTFail("outil attendu") }
        XCTAssertTrue(o2.fini)
        XCTAssertTrue(o2.erreur)
        XCTAssertEqual(o2.resultat, "a\nb")
    }

    func testLesOutilsQuiSeSuiventSontGroupes() {
        let f = FilChat()
        _ = f.recevoir(1, ev(["type": "ToolUse", "tool_id": "t1", "name": "Read", "input": ["file_path": "/a"]]))
        _ = f.recevoir(2, ev(["type": "ToolUse", "tool_id": "t2", "name": "Read", "input": ["file_path": "/b"]]))
        _ = f.recevoir(3, ev(["type": "AssistantText", "msg_id": "m", "text": "fini"]))
        let lignes = LigneFil.de(f.fil.elements)
        XCTAssertEqual(lignes.count, 2)
        if case .groupe(let o, _) = lignes[0] {
            XCTAssertEqual(o.map { $0.cle }, ["t1", "t2"])
        } else {
            XCTFail("groupe attendu")
        }
    }

    func testUnSousAgentAUneCarteEtSonFil() {
        let f = FilChat()
        _ = f.recevoir(1, ev(["type": "ToolUse", "tool_id": "a1", "name": "Task",
                              "input": ["description": "Chercher", "prompt": "Trouve X", "subagent_type": "Explore"]]))
        guard case .agent(let a) = f.fil.elements[0] else { return XCTFail("carte de sous-agent attendue") }
        XCTAssertEqual(a.statut, .travaille)
        _ = f.recevoir(2, ev(["type": "AssistantText", "msg_id": "s1", "text": "dans l'agent", "parent_id": "a1"]))
        XCTAssertEqual(f.fil.taille, 1)
        XCTAssertEqual(f.filAgent("a1").map { LigneFil.texte($0) }, ["dans l'agent"])
        XCTAssertEqual(f.vuesAgents.map { $0.id }, ["a1"])
        _ = f.recevoir(3, ev(["type": "ToolResult", "tool_id": "a1", "text": "X est là"]))
        guard case .agent(let a2) = f.fil.elements[0] else { return XCTFail("carte de sous-agent attendue") }
        XCTAssertEqual(a2.statut, .fini)
        XCTAssertEqual(a2.resultat, "X est là")
    }

    func testLEnvoiRetenuNAjoutePasDeBulleEnDouble() {
        let f = FilChat()
        _ = f.bulleToi("salut")
        f.retenirEnvoi("n1")
        _ = f.recevoir(1, ev(["type": "UserSent", "text": "salut", "nonce": "n1", "uuid": "u1"]))
        XCTAssertEqual(f.fil.taille, 1)
        _ = f.recevoir(2, ev(["type": "UserSent", "text": "d'ailleurs", "nonce": "n2", "uuid": "u2"]))
        XCTAssertEqual(textes(f), ["salut", "d'ailleurs"])
    }

    func testLaDemandeDisparaitQuandElleEstReglee() {
        let f = FilChat()
        let effets = f.recevoir(1, ev(["type": "PermissionRequest", "request_id": "r1", "tool_name": "Bash",
                                       "input": ["command": "rm x"], "description": "Supprimer"]))
        XCTAssertTrue(effets.contains(.autorisationArrivee))
        XCTAssertEqual(f.fil.taille, 1)
        _ = f.recevoir(2, ev(["type": "PermissionSettled", "request_id": "r1", "decision": "allow"]))
        XCTAssertEqual(f.fil.taille, 0)
    }

    func testFinDeTourInterrompu() {
        let f = FilChat()
        let effets = f.recevoir(1, ev(["type": "TurnResult", "ok": true, "interrupted": true, "cost_usd": 0.5]))
        XCTAssertTrue(effets.contains(.tourFini))
        XCTAssertEqual(textes(f), ["Arrêté."])
    }

    func testReinitialisationAjouteUnSeparateur() {
        let f = FilChat()
        _ = f.recevoir(1, ev(["type": "ConversationReset"]))
        guard case .separateur = f.fil.elements.last else { return XCTFail("séparateur attendu") }
    }

    func testArretEtReprise() {
        let f = FilChat()
        f.arrete(reprenable: true)
        XCTAssertEqual(f.fil.taille, 1)
        f.repris()
        XCTAssertEqual(f.fil.taille, 0)
    }

    func testCommandeShell() {
        let f = FilChat()
        let c = f.commande("ls")
        f.majCommande(c) { var x = $0; x.code = 0; x.sortie = "a"; return x }
        guard case .commande(let e) = f.fil.elements[0] else { return XCTFail("commande attendue") }
        XCTAssertTrue(e.finie)
        XCTAssertEqual(e.sortie, "a")
    }

    func testRechercheDansLeFil() {
        let textes = ["Bonjour Été", "rien", "ete chaud"]
        XCTAssertEqual(Recherche.trouver(textes, "ÉTÉ"), [0, 2])
        XCTAssertEqual(Recherche.trouver(textes, "  "), [])
        XCTAssertEqual(Recherche.pas(1, 2, 1), 0)
        XCTAssertEqual(Recherche.pas(0, 2, -1), 1)
        XCTAssertEqual(Recherche.pas(0, 0, 1), -1)
    }
}
