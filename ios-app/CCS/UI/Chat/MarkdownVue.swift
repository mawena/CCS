import SwiftUI
import UIKit

/// Taille du texte du fil (un peu plus petit que le corps d'iOS, comme `bodyMedium` d'Android).
let tailleTexteChat: CGFloat = 16

/// Segments en ligne (gras, italique, code, barré, liens touchables) en texte attribué.
func annoter(_ segments: [Markdown.Segment], taille: CGFloat = tailleTexteChat, gras: Bool = false) -> AttributedString {
    var r = AttributedString()
    for s in segments {
        var a = AttributedString(s.texte)
        var police: Font = s.code ? Font.system(size: taille - 1, design: .monospaced) : Font.system(size: taille)
        if s.gras || gras { police = police.bold() }
        if s.italique { police = police.italic() }
        a.font = police
        if s.barre { a.strikethroughStyle = Text.LineStyle.single }
        if s.code { a.backgroundColor = Color.fondCode }
        if let l = s.lien, let u = URL(string: l), let schema = u.scheme?.lowercased(), ["http", "https", "mailto"].contains(schema) {
            a.link = u
            a.foregroundColor = Color.accentCcs
            a.underlineStyle = Text.LineStyle.single
        }
        r.append(a)
    }
    return r
}

/// Réponse de Claude rendue en blocs Markdown.
@MainActor
struct MarkdownVue: View {
    let texte: String

    var body: some View {
        let blocs = Markdown.analyser(texte)
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(blocs.enumerated()), id: \.offset) { _, b in
                BlocVue(bloc: b)
            }
        }
    }
}

@MainActor
private struct BlocVue: View {
    let bloc: Markdown.Bloc

    var body: some View {
        switch bloc {
        case .paragraphe(let contenu):
            Text(annoter(contenu)).fixedSize(horizontal: false, vertical: true)
        case .titre(let niveau, let contenu):
            Text(annoter(contenu, taille: niveau == 1 ? 21 : (niveau == 2 ? 19 : 17), gras: true))
                .padding(.top, 4)
                .fixedSize(horizontal: false, vertical: true)
        case .liste(let elements):
            VStack(alignment: .leading, spacing: 2) {
                ForEach(Array(elements.enumerated()), id: \.offset) { _, e in
                    HStack(alignment: .firstTextBaseline, spacing: 4) {
                        Text(marque(e))
                            .font(.system(size: tailleTexteChat))
                            .foregroundStyle(.secondary)
                            .frame(minWidth: e.marque.count > 2 ? 26 : 16, alignment: .leading)
                        Text(annoter(e.contenu)).fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.leading, CGFloat(e.niveau * 16))
                }
            }
        case .code(let langue, let texte):
            BlocCode(code: texte, langue: langue)
        case .citation(let blocs):
            HStack(alignment: .top, spacing: 10) {
                RoundedRectangle(cornerRadius: 2).fill(Color.secondary.opacity(0.5)).frame(width: 3)
                // vue récursive : AnyView coupe le type opaque qui se contiendrait lui-même
                AnyView(
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(Array(blocs.enumerated()), id: \.offset) { _, b in BlocVue(bloc: b) }
                    }
                    .foregroundStyle(.secondary)
                )
            }
            .padding(.vertical, 2)
        case .tableau(let entetes, let lignes):
            VueTableau(entetes: entetes, lignes: lignes)
        case .regle:
            Divider().padding(.vertical, 4)
        }
    }

    private func marque(_ e: Markdown.Element) -> String {
        switch e.coche {
        case .some(true): return "☑"
        case .some(false): return "☐"
        case .none: return e.marque
        }
    }
}

/// Bloc de code : langue, bouton Copier, défilement horizontal.
@MainActor
struct BlocCode: View {
    @Environment(ModeleAppli.self) private var modele
    let code: String
    let langue: String

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(langue.isEmpty ? "code" : langue).font(.caption2).foregroundStyle(.secondary)
                Spacer()
                Button {
                    copier(code)
                    modele.avis.dire("Code copié.")
                } label: {
                    Image(systemName: "doc.on.doc").font(.caption)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("Copier le code")
            }
            .padding(.horizontal, 10)
            .padding(.top, 6)
            ScrollView(.horizontal, showsIndicators: false) {
                Text(code)
                    .font(.system(size: 13, design: .monospaced))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: true, vertical: true)
                    .padding(10)
            }
        }
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.fondCode))
    }
}

@MainActor
private struct VueTableau: View {
    let entetes: [[Markdown.Segment]]
    let lignes: [[[Markdown.Segment]]]

    var body: some View {
        let n = max(entetes.count, lignes.map { $0.count }.max() ?? 0)
        ScrollView(.horizontal, showsIndicators: false) {
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 6) {
                GridRow {
                    ForEach(0..<n, id: \.self) { k in
                        Text(annoter(k < entetes.count ? entetes[k] : [], taille: 14, gras: true))
                    }
                }
                Divider()
                ForEach(Array(lignes.enumerated()), id: \.offset) { _, rang in
                    GridRow {
                        ForEach(0..<n, id: \.self) { k in
                            Text(annoter(k < rang.count ? rang[k] : [], taille: 14))
                                .frame(maxWidth: 260, alignment: .leading)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
            .padding(8)
        }
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.fondCode.opacity(0.6)))
    }
}
