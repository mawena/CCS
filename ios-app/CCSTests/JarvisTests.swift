import XCTest
@testable import CCS

final class JarvisTests: XCTestCase {
    private let fp = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_abcde"

    // MARK: adresse d'appairage

    func testAdresseValide() throws {
        let c = try Jarvis.lireAdresse("jarvis://pair?v=1&id=a1b2&h=192.168.1.20,10.0.0.5&p=7341&fp=\(fp)&c=482913")
        XCTAssertEqual(c, CibleAppairage(code: "482913", empreinte: fp, cerveau: "a1b2", port: 7341))
    }

    func testAdresseCollee() throws {
        let c = try Jarvis.lireAdresse("\n  « jarvis://pair?v=1&id=x&h=&p=7341&fp=\(fp)&c=000123 »\nsuite")
        XCTAssertEqual(c.code, "000123")
        XCTAssertEqual(c.empreinte, fp)
    }

    func testAdressesRefusees() {
        let fausses = [
            "https://jarvis/pair?v=1",
            "jarvis://pair?v=2&fp=\(fp)&c=123456",
            "jarvis://pair?v=1&fp=court&c=123456",
            "jarvis://pair?v=1&fp=\(fp)&c=12345",
            "jarvis://pair?v=1&fp=\(fp)&c=12345a",
            "jarvis://pair?v=1&v=1&fp=\(fp)&c=123456",
            "jarvis://pair?v=1&fp=\(fp)&c=123456&rien",
        ]
        for f in fausses { XCTAssertThrowsError(try Jarvis.lireAdresse(f), f) }
    }

    func testEmpreinteEtCode() {
        XCTAssertTrue(Jarvis.empreinteValide(fp))
        XCTAssertFalse(Jarvis.empreinteValide(fp + "a"))
        XCTAssertFalse(Jarvis.empreinteValide(String(fp.dropLast()) + "="))
        XCTAssertFalse(Jarvis.empreinteValide(String(fp.dropLast()) + "é"))
        XCTAssertTrue(Jarvis.codeValide("012345"))
        XCTAssertFalse(Jarvis.codeValide("12345"))
        XCTAssertFalse(Jarvis.codeValide("١٢٣٤٥٦"))
    }

    func testAdresseDuRelais() {
        XCTAssertEqual(Adresse.oreilleJarvis("https://ccs.mawena.cloud/", empreinte: fp)?.absoluteString,
                       "wss://ccs.mawena.cloud/api/jarvis/oreille?fp=\(fp)")
        XCTAssertEqual(Adresse.oreilleJarvis("http://192.168.1.5:8420", empreinte: fp)?.absoluteString,
                       "ws://192.168.1.5:8420/api/jarvis/oreille?fp=\(fp)")
    }

    // MARK: messages

    func testMessagesDeLOreille() {
        let a = AppairageJarvis(earId: "e1", token: "t", fingerprint: fp, brainName: "Jarvis", brainId: "b")
        XCTAssertEqual(Jarvis.hello(a), #"{"ear_id":"e1","token":"t","type":"hello","version":1}"#)
        XCTAssertEqual(Jarvis.wake(7), #"{"level_db":0,"muted":false,"score":2,"type":"wake","utterance":7}"#)
        XCTAssertEqual(Jarvis.listenStart(8), #"{"type":"listen_start","utterance":8}"#)
        XCTAssertEqual(Jarvis.listenEnd(4_000_000_000, sansParole: true),
                       #"{"cut":null,"muted":false,"no_speech":true,"type":"listen_end","utterance":4000000000}"#)
        let p = JSON.lire(Jarvis.pair(code: "123456", nom: String(repeating: "n", count: 80)))
        XCTAssertEqual(p?.texte("type"), "pair")
        XCTAssertEqual(p?.texte("platform"), "ios")
        XCTAssertEqual(p?.texte("code"), "123456")
        XCTAssertEqual(p?.texte("name").count, 60)
        XCTAssertEqual(p?.entier("version"), 1)
    }

    func testMessagesDuCerveau() {
        XCTAssertEqual(Jarvis.lire(#"{"type":"welcome","version":1,"brain_id":"b","brain_name":"Maison","status":{}}"#),
                       .bienvenue(nom: "Maison"))
        XCTAssertEqual(Jarvis.lire(#"{"type":"paired","ear_id":"e","token":"t","brain_id":"b","brain_name":"J"}"#),
                       .appaire(earId: "e", jeton: "t", cerveauId: "b", nom: "J"))
        XCTAssertEqual(Jarvis.lire(#"{"type":"rejected","reason":{"kind":"wrong_code","attempts_left":2}}"#),
                       .refus(motif: "wrong_code", essais: 2))
        XCTAssertEqual(Jarvis.lire(#"{"type":"rejected","reason":{"kind":"bad_token"}}"#), .refus(motif: "bad_token", essais: nil))
        XCTAssertEqual(Jarvis.lire(#"{"type":"elected","utterance":3}"#), .elu(3))
        XCTAssertEqual(Jarvis.lire(#"{"type":"stop","utterance":4}"#), .stop(4))
        XCTAssertEqual(Jarvis.lire(#"{"type":"relay_error","message":"Tunnel fermé."}"#), .relais("Tunnel fermé."))
        XCTAssertEqual(
            Jarvis.lire(#"{"type":"response","utterance":3,"response":{"type":"heard","text":"quelle heure","speech":"Midi.","ear_action":"await_reply","audio":{"pcm":"AQD+/wCA","sample_rate":22050}}}"#),
            .entendu(texte: "quelle heure", voix: "Midi.", audio: VoixJarvis(pcm: "AQD+/wCA", frequence: 22050), attendReponse: true))
        XCTAssertEqual(
            Jarvis.lire(#"{"type":"response","utterance":3,"response":{"type":"heard","text":"a","speech":"b","ear_action":null}}"#),
            .entendu(texte: "a", voix: "b", audio: nil, attendReponse: false))
        XCTAssertEqual(Jarvis.lire(#"{"type":"response","utterance":null,"response":{"type":"reply","speech":"Oui."}}"#), .reponse("Oui."))
        XCTAssertEqual(Jarvis.lire(#"{"type":"response","response":{"type":"error","message":"Panne."}}"#), .erreur("Panne."))
        XCTAssertEqual(Jarvis.lire(#"{"type":"offline_phrase","id":"x","audio":{}}"#), .autre)
        XCTAssertEqual(Jarvis.lire("pas du json"), .autre)
    }

    func testTextesDErreur() {
        XCTAssertEqual(Jarvis.texteRefus("wrong_code", essais: 1), "Code d'appairage faux. Essais restants : 1.")
        XCTAssertEqual(Jarvis.texteRefus("inconnu", essais: nil), "Jarvis a refusé la connexion.")
        XCTAssertEqual(Jarvis.texteFermeture(code: 4011, relais: "laptop-maison hors ligne.", raison: "x"),
                       "Jarvis est injoignable : laptop-maison hors ligne.")
        XCTAssertEqual(Jarvis.texteFermeture(code: 4011, relais: nil, raison: ""), "Jarvis est injoignable.")
        XCTAssertEqual(Jarvis.texteFermeture(code: 1011, relais: nil, raison: ""), "Pont CCS injoignable.")
        XCTAssertEqual(Jarvis.texteFermeture(code: 1006, relais: nil, raison: " "), "Connexion au relais de Jarvis perdue.")
    }

    // MARK: son

    func testTrameMicro() {
        let t = Jarvis.trameMicro(0x0102_0304, [1, -2, Int16.min][...])
        XCTAssertEqual([UInt8](t), [0x01, 0x04, 0x03, 0x02, 0x01, 0x01, 0x00, 0xFE, 0xFF, 0x00, 0x80])
    }

    func testDecodagePcmEtWav() {
        XCTAssertEqual(Jarvis.decoderPcm("AQD+/wCA"), [1, -2, Int16.min])
        XCTAssertEqual(Jarvis.decoderPcm("pas du base64 !"), [])
        let w = [UInt8](Jarvis.wav([1, -2], frequence: 22050))
        XCTAssertEqual(w.count, 48)
        XCTAssertEqual(Array(w[0..<4]), Array("RIFF".utf8))
        XCTAssertEqual(Array(w[8..<16]), Array("WAVEfmt ".utf8))
        XCTAssertEqual(Array(w[24..<28]), [0x22, 0x56, 0x00, 0x00])        // 22 050 Hz
        XCTAssertEqual(Array(w[36..<48]), Array("data".utf8) + [4, 0, 0, 0, 1, 0, 0xFE, 0xFF])
    }

    func testReechantillonnage() {
        let r = Reechantillonneur(frequence: 48_000)
        var total = 0
        for _ in 0..<10 {
            let s = r.pousser([Float](repeating: 0.5, count: 480))
            total += s.count
            XCTAssertTrue(s.allSatisfy { $0 == 16384 })
        }
        XCTAssertEqual(total, 1600)
        XCTAssertEqual(Reechantillonneur(frequence: 16_000).pousser([-1, 1, 2]), [Int16.min, Int16.max, Int16.max])
        let n = Reechantillonneur(frequence: 44_100).pousser([Float](repeating: 0, count: 44_100)).count
        XCTAssertTrue((15_999...16_000).contains(n), "\(n)")
    }

    // MARK: phrase

    func testPhraseAttendLeLienPuisDecoupe() {
        var p = PhraseJarvis(numero: 9, auto: false, maintenant: 0)
        XCTAssertFalse(p.ajouter([Int16](repeating: 1, count: 5_000), fort: true, maintenant: 10))
        XCTAssertEqual(p.trames(toutes: true), [])          // lien pas prêt : tout reste en attente
        p.prete = true
        let t = p.trames(toutes: false)
        XCTAssertEqual(t.map(\.count), [5 + 3_200, 5 + 3_200, 5 + 3_200])
        XCTAssertEqual(p.tampon.count, 200)
        XCTAssertEqual(p.trames(toutes: true).map(\.count), [5 + 400])
        XCTAssertTrue(p.tampon.isEmpty)
        XCTAssertFalse(p.sansParole)
    }

    func testTrameDeRattrapageAuPlus1s() {
        var p = PhraseJarvis(numero: 1, auto: false, maintenant: 0)
        _ = p.ajouter([Int16](repeating: 0, count: 40_000), fort: false, maintenant: 0)
        p.prete = true
        XCTAssertEqual(p.trames(toutes: true).map(\.count), [32_005, 32_005, 16_005])
    }

    func testPhraseBorneeA14s() {
        var p = PhraseJarvis(numero: 1, auto: false, maintenant: 0)
        XCTAssertFalse(p.ajouter([Int16](repeating: 0, count: 13 * 16_000), fort: true, maintenant: 0))
        XCTAssertTrue(p.ajouter([Int16](repeating: 0, count: 2 * 16_000), fort: true, maintenant: 0))
        XCTAssertEqual(p.total, 14 * 16_000)
    }

    func testFinAuSilenceEnModeAuto() {
        var p = PhraseJarvis(numero: 1, auto: true, maintenant: 0)
        XCTAssertFalse(p.ajouter([Int16](repeating: 0, count: 1_600), fort: true, maintenant: 100))
        XCTAssertFalse(p.ajouter([Int16](repeating: 0, count: 1_600), fort: false, maintenant: 1_200))
        XCTAssertTrue(p.ajouter([Int16](repeating: 0, count: 1_600), fort: false, maintenant: 1_400))
        // au relâché (mode maintenu), le silence n'arrête rien
        var q = PhraseJarvis(numero: 2, auto: false, maintenant: 0)
        _ = q.ajouter([1], fort: true, maintenant: 0)
        XCTAssertFalse(q.ajouter([1], fort: false, maintenant: 10_000))
    }

    func testRienDitEn6s() {
        var p = PhraseJarvis(numero: 1, auto: true, maintenant: 0)
        XCTAssertFalse(p.ajouter([Int16](repeating: 0, count: 6 * 16_000), fort: false, maintenant: 0))
        XCTAssertTrue(p.ajouter([0], fort: false, maintenant: 0))
        XCTAssertTrue(p.sansParole)
        var court = PhraseJarvis(numero: 2, auto: false, maintenant: 0)
        _ = court.ajouter([Int16](repeating: 0, count: 4_000), fort: true, maintenant: 0)
        XCTAssertTrue(court.sansParole)                       // moins de 0,3 s
    }
}
