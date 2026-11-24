import XCTest
@testable import CCS

final class RicheTests: XCTestCase {
    func testMediaParExtension() {
        XCTAssertEqual(Riche.media("a/b.MP3"), .son)
        XCTAssertEqual(Riche.media("https://x.fr/v.mp4?t=3#debut"), .video)
        XCTAssertEqual(Riche.media("clip.mov"), .video)
        XCTAssertNil(Riche.media("image.png"))
        XCTAssertNil(Riche.media("sans-extension"))
    }

    func testResoudre() {
        XCTAssertEqual(Riche.resoudre("https://x.fr/a.png", cwd: "/p"), .url(URL(string: "https://x.fr/a.png")!))
        XCTAssertEqual(Riche.resoudre("img/a.png", cwd: "/home/c/projet"), .chemin("/home/c/projet/img/a.png"))
        XCTAssertEqual(Riche.resoudre("./../b/./c.mp3", cwd: "/home/c/projet/"), .chemin("/home/c/b/c.mp3"))
        XCTAssertEqual(Riche.resoudre("/tmp/x.wav", cwd: "/p"), .chemin("/tmp/x.wav"))
        XCTAssertNil(Riche.resoudre("http://x.fr/a.png", cwd: "/p"))
        XCTAssertNil(Riche.resoudre("javascript:alert(1)", cwd: "/p"))
        XCTAssertNil(Riche.resoudre("//hote/a.png", cwd: "/p"))
        XCTAssertNil(Riche.resoudre("  ", cwd: "/p"))
    }

    func testSegmentImage() {
        let s = Markdown.enLigne("voir ![logo](img/a.png) ici")
        let img = s.first(where: { $0.image })
        XCTAssertEqual(img?.texte, "logo")
        XCTAssertEqual(img?.lien, "img/a.png")
        XCTAssertEqual(Riche.medias(s).map { $0.genre }, [.image])
        XCTAssertEqual(Riche.medias(Markdown.enLigne("écoute `son/a.ogg` et [clip](https://x.fr/c.mp4)")).map { $0.genre },
                       [.son, .video])
        XCTAssertTrue(Riche.medias(Markdown.enLigne("[site](https://x.fr)")).isEmpty)
    }

    func testBlocChoix() {
        let c = Riche.bloc(#"{"type":"choix","question":"Quelle base ?","options":["SQLite",{"label":"Postgres","message":"Prends Postgres"},{"label":"Doc","lien":"https://x.fr"}]}"#)
        guard case .some(.choix(let titre, let options)) = c else { return XCTFail("choix attendu") }
        XCTAssertEqual(titre, "Quelle base ?")
        XCTAssertEqual(options.map { $0.label }, ["SQLite", "Postgres", "Doc"])
        XCTAssertEqual(options[1].message, "Prends Postgres")
        XCTAssertEqual(options[2].lien, URL(string: "https://x.fr"))
    }

    func testBlocsInvalides() {
        XCTAssertNil(Riche.bloc("pas du json"))
        XCTAssertNil(Riche.bloc(#"{"type":"inconnu"}"#))
        XCTAssertNil(Riche.bloc(#"{"type":"choix","options":[]}"#))
        XCTAssertNil(Riche.bloc(#"{"type":"carte"}"#))
        XCTAssertNil(Riche.bloc(#"{"type":"cartes","items":[]}"#))
        XCTAssertNil(Riche.bloc(#"{"type":"formulaire","champs":[]}"#))
        XCTAssertNil(Riche.bloc(#"[1,2]"#))
    }

    func testCarteLienWebSeulement() {
        guard case .some(.carte(let c)) = Riche.bloc(#"{"type":"carte","titre":"Vélo","prix":120,"lien":"javascript:x","actions":[{"label":"Acheter","message":"Je prends le vélo"}]}"#)
        else { return XCTFail("carte attendue") }
        XCTAssertEqual(c.prix, "120")
        XCTAssertNil(c.lien)
        XCTAssertEqual(c.actions.first?.message, "Je prends le vélo")
    }

    func testMessageFormulaire() {
        guard case .some(.formulaire(let titre, let bouton, let champs)) = Riche.bloc(
            #"{"type":"formulaire","titre":"Réservation","champs":[{"nom":"n","label":"Nom"},{"label":"Nombre","type":"nombre"},{"nom":"v","label":"Ville","type":"liste","options":["Lomé","Kara"]}]}"#)
        else { return XCTFail("formulaire attendu") }
        XCTAssertEqual(bouton, "Envoyer")
        XCTAssertEqual(champs.map { $0.cle }, ["n", "Nombre", "v"])
        XCTAssertEqual(Riche.messageFormulaire(titre: titre, champs: champs, valeurs: ["n": " Ama ", "Nombre": "", "v": "Kara"]),
                       "Réservation\n- Nom : Ama\n- Ville : Kara")
    }
}
