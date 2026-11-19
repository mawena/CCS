import XCTest
@testable import CCS

final class ModelesSessionsTests: XCTestCase {
    func testListeDesProjets() {
        let j = JSON.lire(#"{"entries": [{"cwd": null, "name": "Tous", "total": 9}, {"cwd": "/home/c/ccs", "name": "ccs", "total": 3, "open": 1, "exists": false, "moved_to": "/home/c/Work/ccs", "profile": "pro"}], "conversations": [{"session_id": "s1", "path": "/p/s1.jsonl", "cwd": "/home/c/ccs", "title": "", "first_prompt": "Bonjour", "updated_at": 1795091812.5, "folder_exists": true}, {"session_id": "s2", "title": "  ", "first_prompt": ""}], "total": 2}"#) ?? .vide
        let l = ListeProjets(json: j)
        XCTAssertEqual(l.entries.count, 2)
        XCTAssertEqual(l.projets.map { $0.name }, ["ccs"])          // sans l'entrée « Tous »
        XCTAssertFalse(l.projets[0].exists)
        XCTAssertEqual(l.projets[0].deplaceVers, "/home/c/Work/ccs")
        XCTAssertEqual(l.conversations[0].titre, "Bonjour")          // titre vide : la première demande
        XCTAssertEqual(l.conversations[1].titre, "(sans titre)")
        XCTAssertTrue(l.conversations[1].dossierExiste)               // absent : vrai par défaut
        XCTAssertEqual(l.conversations[0].misAJour, 1795091812.5)
    }

    func testChatOuvertEtOptions() {
        let j = JSON.lire(#"{"chat_id": "c1", "cwd": "/p", "state": "idle", "seq": 12, "options": {"model": "opus", "effort": null, "rights": "acceptEdits"}, "session_id": null, "history_before": 1795000000}"#) ?? .vide
        let c = ChatOuvert(json: j)
        XCTAssertEqual(c.chatId, "c1")
        XCTAssertEqual(c.seq, 12)
        XCTAssertEqual(c.options?.model, "opus")
        XCTAssertNil(c.options?.effort)
        XCTAssertEqual(c.options?.rights, "acceptEdits")
        XCTAssertNil(c.sessionId)
        XCTAssertEqual(c.historiqueAvant, 1795000000)
        XCTAssertEqual(OptionsChat(json: .vide).rights, "manual")
        let o = OptionsChat(json: j["options"] ?? .vide).enJSON
        XCTAssertEqual(o["effort"], .nul)
        XCTAssertEqual(o["ultracode"], .booleen(false))
    }

    func testCompteDuProjetEtHistorique() {
        let cp = CompteProjet(json: JSON.lire(#"{"profiles": [{"name": "perso", "email": "a@b", "active": true}, {"name": "pro"}], "active": "perso", "preferred": "pro", "hint": "Compte conseillé : pro"}"#) ?? .vide)
        XCTAssertEqual(cp.profiles.count, 2)
        XCTAssertEqual(cp.preferred, "pro")
        let m = Messages(json: JSON.lire(#"{"messages": [{"role": "outil", "text": "", "tool": {"name": "Bash", "target": "ls", "result": "a", "tool_id": "t1", "is_error": true}}, {"role": "assistant", "text": "ok", "msg_id": "m1"}]}"#) ?? .vide)
        XCTAssertEqual(m.messages[0].tool?.erreur, true)
        XCTAssertEqual(m.messages[1].msgId, "m1")
        XCTAssertNil(m.messages[1].tool)
    }
}
