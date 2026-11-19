import SwiftUI
import WebKit

/**
 * Connexion par Portier dans une vue web : la page de Portier ramène sur le serveur une fois la
 * connexion faite. À ce moment, on arrête la vue et on rend les cookies valables pour le serveur
 * (ceux de Portier, sur le domaine commun), que l'appli enverra elle-même au WebSocket.
 */
struct EcranPortier: View {
    let adresse: String
    let connexion: String
    let fermer: () -> Void
    let reussi: (String) -> Void

    @State private var progression: Double = 0

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if progression > 0 && progression < 1 {
                    ProgressView(value: progression).progressViewStyle(.linear)
                }
                VueWebPortier(adresse: adresse, connexion: connexion, progression: $progression, reussi: reussi)
            }
            .navigationTitle("Connexion par Portier")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Fermer", action: fermer)
                }
            }
        }
    }
}

private struct VueWebPortier: UIViewRepresentable {
    let adresse: String
    let connexion: String
    @Binding var progression: Double
    let reussi: (String) -> Void

    func makeCoordinator() -> Coordinateur {
        return Coordinateur(hoteServeur: Adresse.hote(adresse), progression: $progression, reussi: reussi)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = WKWebsiteDataStore.default()
        let vue = WKWebView(frame: .zero, configuration: config)
        vue.navigationDelegate = context.coordinator
        context.coordinator.observer(vue)
        if let url = URL(string: connexion) {
            vue.load(URLRequest(url: url))
        }
        return vue
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    static func dismantleUIView(_ uiView: WKWebView, coordinator: Coordinateur) {
        uiView.stopLoading()
        coordinator.observation = nil
    }

    final class Coordinateur: NSObject, WKNavigationDelegate {
        let hoteServeur: String?
        var progression: Binding<Double>
        let reussi: (String) -> Void
        var fini = false
        var observation: NSKeyValueObservation?

        init(hoteServeur: String?, progression: Binding<Double>, reussi: @escaping (String) -> Void) {
            self.hoteServeur = hoteServeur
            self.progression = progression
            self.reussi = reussi
        }

        func observer(_ vue: WKWebView) {
            observation = vue.observe(\.estimatedProgress, options: [.new]) { [weak self] v, _ in
                let p = v.estimatedProgress
                DispatchQueue.main.async { self?.progression.wrappedValue = p }
            }
        }

        func webView(
            _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url, let schema = url.scheme?.lowercased() else {
                decisionHandler(.cancel)
                return
            }
            if schema != "https" && schema != "http" {
                decisionHandler(.cancel)
                return
            }
            let principal = navigationAction.targetFrame?.isMainFrame ?? true
            if principal, let hote = url.host?.lowercased(), hote == hoteServeur {
                decisionHandler(.cancel)
                revenu(webView)
                return
            }
            decisionHandler(.allow)
        }

        /// Retour sur le serveur : on lit les cookies qui le concernent (un court délai : ceux de la redirection).
        private func revenu(_ webView: WKWebView) {
            if fini { return }
            fini = true
            webView.stopLoading()
            let magasin = webView.configuration.websiteDataStore.httpCookieStore
            let hote = hoteServeur ?? ""
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                magasin.getAllCookies { cookies in
                    let pris = cookies.filter { c in
                        var d = c.domain.lowercased()
                        if d.hasPrefix(".") { d.removeFirst() }
                        return hote == d || hote.hasSuffix("." + d)
                    }
                    let texte = pris.map { "\($0.name)=\($0.value)" }.joined(separator: "; ")
                    DispatchQueue.main.async { self.reussi(texte) }
                }
            }
        }
    }
}
