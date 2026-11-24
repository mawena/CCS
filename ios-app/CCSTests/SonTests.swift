import XCTest
@testable import CCS

/// Son partagé (phase 42) : paquets RTP, tampon de gigue, conversion PCM, nom de l'appareil, événements.
final class SonTests: XCTestCase {
    // MARK: RTP

    func testPaquetEtLecture() {
        let e = Rtp.EnTete(sequence: 0xABCD, horodatage: 0x01020304, ssrc: 0xDEADBEEF)
        let p = Rtp.paquet(e, Data([0xFC, 1, 2]))
        XCTAssertEqual(Array(p.prefix(12)), [0x80, 96, 0xAB, 0xCD, 1, 2, 3, 4, 0xDE, 0xAD, 0xBE, 0xEF])
        let (l, charge) = Rtp.lire(p)!
        XCTAssertEqual(l, e)
        XCTAssertEqual(charge, Data([0xFC, 1, 2]))
    }

    func testLectureRefuseEtSaute() {
        XCTAssertNil(Rtp.lire(Data([0x80, 96, 0, 1])))                         // trop court
        XCTAssertNil(Rtp.lire(Data([0x40] + [UInt8](repeating: 0, count: 12)))) // version 1
        // un CSRC, une extension d'un mot, deux octets de bourrage
        var o: [UInt8] = [0xB1, 0xE0, 0, 7, 0, 0, 0, 9, 0, 0, 0, 1]
        o += [9, 9, 9, 9]                 // CSRC
        o += [0xBE, 0xDE, 0, 1, 5, 5, 5, 5] // extension
        o += [0xAA, 0xBB]                 // charge
        o += [0, 2]                       // bourrage
        let (e, charge) = Rtp.lire(Data(o))!
        XCTAssertEqual(e.sequence, 7)
        XCTAssertEqual(e.type, 96)
        XCTAssertTrue(e.marqueur)
        XCTAssertEqual(charge, Data([0xAA, 0xBB]))
    }

    func testPaqueteur() {
        var p = PaqueteurRtp(sequence: 0xFFFF, horodatage: 0xFFFF_FFFF - 100, ssrc: 42)
        let a = Rtp.lire(p.paquet(Data([1])))!.0
        let b = Rtp.lire(p.paquet(Data([2])))!.0
        XCTAssertEqual(a.sequence, 0xFFFF)
        XCTAssertEqual(b.sequence, 0)
        XCTAssertEqual(b.horodatage, a.horodatage &+ 480)   // trames de 10 ms par défaut
        XCTAssertEqual(b.ssrc, 42)
        let c = Rtp.lire(p.paquet(Data([3]), echantillons: 960))!.0
        let d = Rtp.lire(p.paquet(Data([4])))!.0
        XCTAssertEqual(c.horodatage, b.horodatage &+ 480)
        XCTAssertEqual(d.horodatage, c.horodatage &+ 960)   // la trame de 20 ms compte double
    }

    func testDureeOpus() {
        XCTAssertEqual(Rtp.echantillonsOpus(Data([0xF4])), 480)        // CELT 10 ms stéréo
        XCTAssertEqual(Rtp.echantillonsOpus(Data([0xFC])), 960)        // CELT 20 ms stéréo
        XCTAssertEqual(Rtp.echantillonsOpus(Data([0xFD])), 1920)       // deux trames de 20 ms
        XCTAssertEqual(Rtp.echantillonsOpus(Data([0xFF, 0x03])), 2880) // trois trames de 20 ms
        XCTAssertEqual(Rtp.echantillonsOpus(Data([0x08])), 960)        // SILK 20 ms
        XCTAssertEqual(Rtp.echantillonsOpus(Data([0x18])), 2880)       // SILK 60 ms
        XCTAssertEqual(Rtp.echantillonsOpus(Data([0x60])), 480)        // hybride 10 ms
        XCTAssertNil(Rtp.echantillonsOpus(Data()))
        XCTAssertNil(Rtp.echantillonsOpus(Data([0xFF])))               // nombre de trames absent
        XCTAssertNil(Rtp.echantillonsOpus(Data([0xFF, 0x3F])))         // plus de 120 ms
    }

    func testEcartEtCanaux() {
        XCTAssertEqual(Rtp.ecart(1, 0xFFFF), 2)
        XCTAssertEqual(Rtp.ecart(0xFFFF, 1), -2)
        XCTAssertEqual(Rtp.canauxOpus(Data([0xFC])), 2)
        XCTAssertEqual(Rtp.canauxOpus(Data([0xF8])), 1)
    }

    // MARK: tampon de gigue

    private func t(_ n: UInt8) -> Data { return Data([n]) }

    func testTamponAttendPuisRemetEnOrdre() {
        var g = TamponGigue(depart: 3, maximum: 7)
        g.ajouter(sequence: 10, t(10))
        XCTAssertEqual(g.sortir(), .attente)
        g.ajouter(sequence: 12, t(12))
        g.ajouter(sequence: 11, t(11))
        XCTAssertEqual(g.sortir(), .trame(t(10)))
        XCTAssertEqual(g.sortir(), .trame(t(11)))
        XCTAssertEqual(g.sortir(), .trame(t(12)))
        XCTAssertEqual(g.sortir(), .attente)          // creux : on remplit à nouveau
        XCTAssertFalse(g.joue)
    }

    func testTamponPerteRetardEtDouble() {
        var g = TamponGigue(depart: 2, maximum: 7)
        g.ajouter(sequence: 1, t(1))
        g.ajouter(sequence: 3, t(3))
        XCTAssertEqual(g.sortir(), .trame(t(1)))
        XCTAssertEqual(g.sortir(), .perte)
        XCTAssertFalse(g.ajouter(sequence: 2, t(2)))  // arrivé trop tard
        XCTAssertFalse(g.ajouter(sequence: 3, t(3)))  // en double
        XCTAssertEqual(g.sortir(), .trame(t(3)))
        XCTAssertEqual(g.perdues, 1)
        XCTAssertEqual(g.jetees, 2)
    }

    func testTamponDebordeEtBoucle() {
        var g = TamponGigue(depart: 3, maximum: 7)
        for i in 0..<10 { g.ajouter(sequence: UInt16(0xFFFA) &+ UInt16(i), t(UInt8(i))) }   // passe par 0
        // à la 8e trame (140 ms dépassés), on est revenu à 3 trames d'avance : les 5 premières sautées
        XCTAssertEqual(g.avance, 5)
        XCTAssertEqual(g.jetees, 5)
        XCTAssertEqual(g.sortir(), .trame(t(5)))
        XCTAssertEqual(g.sortir(), .trame(t(6)))
        XCTAssertEqual(g.sortir(), .trame(t(7)))
    }

    func testTamponSourceRedemarree() {
        var g = TamponGigue(depart: 1, maximum: 7)
        g.ajouter(sequence: 100, t(1))
        XCTAssertEqual(g.sortir(), .trame(t(1)))
        g.ajouter(sequence: 30_000, t(2))             // saut énorme : nouveau départ
        XCTAssertEqual(g.sortir(), .trame(t(2)))
    }

    // MARK: PCM

    func testPcmEntier16Entrelace() {
        // deux trames stéréo : (16384, -16384), (0, 32767), petit-boutien
        let d = Data([0x00, 0x40, 0x00, 0xC0, 0x00, 0x00, 0xFF, 0x7F])
        let (g, dr) = d.withUnsafeBytes { p in
            Pcm.stereo([p], Pcm.Format(canaux: 2, octets: 2, flottant: false, grandBoutien: false, entrelace: true), trames: 2)
        }
        XCTAssertEqual(g, [0.5, 0])
        XCTAssertEqual(dr[0], -0.5)
        XCTAssertEqual(dr[1], 32767 / 32768, accuracy: 1e-6)
    }

    func testPcmMonoGrandBoutien() {
        let d = Data([0x40, 0x00])
        let (g, dr) = d.withUnsafeBytes { p in
            Pcm.stereo([p], Pcm.Format(canaux: 1, octets: 2, flottant: false, grandBoutien: true, entrelace: true), trames: 1)
        }
        XCTAssertEqual(g, [0.5])
        XCTAssertEqual(dr, [0.5])
    }

    func testPcmFlottantNonEntrelace() {
        var a: [Float] = [0.25]
        var b: [Float] = [-1]
        let da = Data(bytes: &a, count: 4), db = Data(bytes: &b, count: 4)
        let (g, dr) = da.withUnsafeBytes { pa in
            db.withUnsafeBytes { pb in
                Pcm.stereo([pa, pb], Pcm.Format(canaux: 2, octets: 4, flottant: true, grandBoutien: false, entrelace: false), trames: 1)
            }
        }
        XCTAssertEqual(g, [0.25])
        XCTAssertEqual(dr, [-1])
    }

    // MARK: nom de l'appareil

    func testAdresseMaillee() {
        XCTAssertTrue(Son.estMaillee("100.64.0.4"))
        XCTAssertTrue(Son.estMaillee("100.127.255.1"))
        XCTAssertFalse(Son.estMaillee("100.128.0.1"))
        XCTAssertFalse(Son.estMaillee("192.168.1.4"))
        XCTAssertFalse(Son.estMaillee("100.64.0"))
        XCTAssertEqual(Son.adresseMaillee([("en0", "192.168.1.4"), ("pdp_ip0", "100.70.0.1"), ("utun4", "100.64.0.4")]), "100.64.0.4")
        XCTAssertEqual(Son.adresseMaillee([("en0", "192.168.1.4")]), nil)
    }

    func testNomAppareil() {
        let e = EtatReseau(ici: Appareil(name: "mawena-cloud", ips: ["100.64.0.1"]),
                           peers: [Appareil(name: "iphone-charles", ips: ["100.64.0.4", "fd7a::4"]),
                                   Appareil(name: "pixel", ips: ["100.64.0.3"])])
        XCTAssertEqual(Son.nomAppareil(ip: "100.64.0.4", etat: e, modele: "iPhone"), "iphone-charles")
        XCTAssertEqual(Son.nomAppareil(ip: "100.64.0.9", etat: e, modele: "iPhone"), "iphone")
        XCTAssertEqual(Son.nomAppareil(ip: nil, etat: nil, modele: "iPad"), "ipad")
        XCTAssertEqual(Son.nettoyer(" -iPhone de Charles"), "iPhone-de-Charles")
        XCTAssertEqual(Son.nettoyer(String(repeating: "a", count: 80)).count, 63)
    }

    // MARK: événements et liste

    func testEvenements() {
        let r = JSON.lire(#"{"action":"receive","device":"iphone","stream":"a1","source":"pc","target":"iphone","from":"pc","from_label":"PC bureau","from_ip":"100.64.0.2","port":4010}"#)!
        XCTAssertEqual(EvenementSon.lire(r), .recevoir(device: "iphone", flux: "a1", de: "pc", deNom: "PC bureau", port: 4010))
        XCTAssertTrue(EvenementSon.lire(r)!.concerne("iphone"))
        XCTAssertFalse(EvenementSon.lire(r)!.concerne("pixel"))
        let e = JSON.lire(#"{"action":"emit","device":"iphone","stream":"a2","to":"pc","to_label":"PC","ip":"100.64.0.2","port":4010}"#)!
        XCTAssertEqual(EvenementSon.lire(e), .emettre(device: "iphone", flux: "a2", vers: "pc", versNom: "PC", ip: "100.64.0.2", port: 4010))
        let s = JSON.lire(#"{"action":"stop","stream":"a2","devices":["iphone","pc"],"source":"iphone","target":"pc","reason":"arrêté"}"#)!
        XCTAssertEqual(EvenementSon.lire(s), .arret(flux: "a2", appareils: ["iphone", "pc"], raison: "arrêté"))
        XCTAssertTrue(EvenementSon.lire(s)!.concerne("pc"))
        XCTAssertFalse(EvenementSon.lire(s)!.concerne(""))
        XCTAssertNil(EvenementSon.lire(JSON.lire(#"{"action":"autre"}"#)!))
    }

    // MARK: tampon adaptatif

    /// Trame Opus de 10 ms (TOC 0xF4) ou de 20 ms (0xFC) numérotée `n`.
    private func o(_ n: UInt8, _ toc: UInt8 = 0xF4) -> Data { return Data([toc, n]) }

    func testGigueMonteSurPerteUneFoisParRafale() {
        var g = GigueAdaptative()
        XCTAssertEqual(g.cibleMs, 30)
        XCTAssertEqual(g.tampon.depart, 3)                 // 3 × 10 ms
        XCTAssertEqual(g.tampon.maximum, 7)                // + 40 ms de marge
        for s: UInt16 in [0, 1, 2, 4, 6] { g.ajouter(sequence: s, o(UInt8(s))) }
        XCTAssertEqual(g.sortir(), .trame(o(0)))
        XCTAssertEqual(g.sortir(), .trame(o(1)))
        XCTAssertEqual(g.sortir(), .trame(o(2)))
        XCTAssertEqual(g.sortir(), .perte)
        XCTAssertEqual(g.cibleMs, 40)
        XCTAssertEqual(g.tampon.depart, 4)
        XCTAssertEqual(g.sortir(), .trame(o(4)))
        XCTAssertEqual(g.sortir(), .perte)                 // même rafale : pas de second pas
        XCTAssertEqual(g.cibleMs, 40)
    }

    func testGigueRedescendQuandStable() {
        var g = GigueAdaptative()
        for s: UInt16 in 0..<3 { g.ajouter(sequence: s, o(UInt8(s & 0xFF))) }
        for k in 0..<999 {
            XCTAssertEqual(g.sortir(), .trame(o(UInt8(k & 0xFF))))
            g.ajouter(sequence: UInt16(k + 3), o(UInt8((k + 3) & 0xFF)))
        }
        XCTAssertEqual(g.cibleMs, 30)
        _ = g.sortir()                                     // 10 s jouées sans incident
        XCTAssertEqual(g.cibleMs, 20)
        XCTAssertEqual(g.tampon.depart, 2)
    }

    func testGigueCreuxCourtMaisPasPause() {
        var g = GigueAdaptative()
        for s: UInt16 in 0..<3 { g.ajouter(sequence: s, o(UInt8(s))) }
        for _ in 0..<3 { _ = g.sortir() }
        XCTAssertEqual(g.sortir(), .attente)               // sous-alimentation
        for s: UInt16 in 3..<6 { g.ajouter(sequence: s, o(UInt8(s))) }
        XCTAssertEqual(g.sortir(), .trame(o(3)))
        XCTAssertEqual(g.cibleMs, 40)
        // une pause de la source (plus de 300 ms) ne fait pas monter
        var h = GigueAdaptative()
        for s: UInt16 in 0..<3 { h.ajouter(sequence: s, o(UInt8(s))) }
        for _ in 0..<3 { _ = h.sortir() }
        for _ in 0..<40 { XCTAssertEqual(h.sortir(), .attente) }
        for s: UInt16 in 3..<6 { h.ajouter(sequence: s, o(UInt8(s))) }
        XCTAssertEqual(h.sortir(), .trame(o(3)))
        XCTAssertEqual(h.cibleMs, 30)
    }

    func testGigueTramesDe20ms() {
        var g = GigueAdaptative()
        g.ajouter(sequence: 0, o(0, 0xFC))
        XCTAssertEqual(g.echantillons, 960)
        XCTAssertEqual(g.dureeTrameMs, 20)
        XCTAssertEqual(g.tampon.depart, 2)                 // 30 ms → 2 trames de 20 ms
        XCTAssertEqual(g.tampon.maximum, 4)
        XCTAssertEqual(g.sortir(), .attente)
        g.ajouter(sequence: 1, o(1, 0xFC))
        XCTAssertEqual(g.sortir(), .trame(o(0, 0xFC)))
    }

    func testListe() {
        let j = JSON.lire(#"{"devices":[{"device":"iphone","label":"iPhone","ip":"100.64.0.4","port":4010,"play":true,"capture":true,"system":"ios","age":3},{"device":"pc","label":"","ip":"100.64.0.2","port":4010,"play":true,"capture":false,"system":"linux"},{"device":"web","play":false,"capture":false}],"streams":[{"stream":"a1","source":"pc","target":"iphone","started":1}]}"#)!
        let l = ListeSon(json: j)
        XCTAssertEqual(l.sorties.map { $0.device }, ["iphone", "pc"])
        XCTAssertEqual(l.sources.map { $0.device }, ["iphone"])
        XCTAssertEqual(l.nom("pc"), "pc")
        XCTAssertEqual(Son.sortiesPour("iphone", l).map { $0.device }, ["pc"])
        XCTAssertEqual(Son.flux(de: "iphone", l).recu?.stream, "a1")
        XCTAssertNil(Son.flux(de: "iphone", l).emis)
    }
}
