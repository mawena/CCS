import SwiftUI

/**
 * Connexion : appairage de l'appareil (identifiant et mot de passe Ubuntu, puis code TOTP ; à la
 * première connexion, secret à ajouter dans l'appli d'authentification), ou connexion par Portier
 * si le serveur l'a activée. L'appairage rend un jeton d'appareil, gardé dans le trousseau.
 */
@MainActor
struct EcranConnexion: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.openURL) private var ouvrirLien

    @State private var utilisateur = ""
    @State private var motDePasse = ""
    @State private var code = ""
    @State private var voirMotDePasse = false
    @State private var codeDemande = false
    @State private var enAttente: String?
    @State private var secret: String?
    @State private var message: String?
    @State private var occupe = false
    @State private var portier: InfoPortier?
    @State private var vuePortier = false
    @State private var changerServeur = false
    @State private var nouvelleAdresse = ""

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                Image("Logo")
                    .resizable()
                    .frame(width: 96, height: 96)
                    .clipShape(RoundedRectangle(cornerRadius: 22))
                    .padding(.top, 32)
                Text("CCS").font(.largeTitle.weight(.semibold))
                HStack {
                    Text(modele.adresse.replacingOccurrences(of: "https://", with: ""))
                        .foregroundStyle(.secondary)
                    Button("Changer") {
                        nouvelleAdresse = modele.adresse
                        changerServeur = true
                    }
                    .disabled(occupe)
                }
                .font(.subheadline)

                VStack(spacing: 12) {
                    if enAttente == nil {
                        champsIdentifiants
                    } else {
                        inscription
                    }
                    if codeDemande || enAttente != nil {
                        TextField("Code à 6 chiffres", text: $code)
                            .keyboardType(.numberPad)
                            .textContentType(.oneTimeCode)
                            .textFieldStyle(.roundedBorder)
                            .disabled(occupe)
                            .onChange(of: code) { _, v in
                                let chiffres = String(v.filter { $0.isNumber }.prefix(8))
                                if chiffres != v { code = chiffres }
                            }
                            .onSubmit { valider() }
                    }
                    if let m = message {
                        Text(m).foregroundStyle(.red).frame(maxWidth: .infinity, alignment: .leading)
                    }
                    Button {
                        valider()
                    } label: {
                        Group {
                            if occupe { ProgressView() } else { Text(enAttente != nil ? "Valider le code" : "Appairer cet appareil") }
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(occupe || (enAttente == nil && (utilisateur.trimmingCharacters(in: .whitespaces).isEmpty || motDePasse.isEmpty)))
                    if enAttente != nil {
                        Button("Annuler") {
                            enAttente = nil
                            secret = nil
                            code = ""
                        }
                    }
                    if portier?.actif == true && enAttente == nil {
                        Divider().padding(.vertical, 8)
                        Button {
                            vuePortier = true
                        } label: {
                            Text("Se connecter via Portier").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.large)
                        .disabled(occupe)
                    }
                    Text("L'appareil reçoit un jeton propre, gardé dans le trousseau de l'iPhone, que tu peux révoquer depuis la version web.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: 420)
            }
            .padding(24)
        }
        .scrollDismissesKeyboard(.interactively)
        .task(id: modele.adresse) {
            portier = try? await ApiHttp.portier(modele.adresse)
        }
        .onAppear {
            if let a = modele.avisConnexion {
                message = a
                modele.avisConnexion = nil
            }
        }
        .fullScreenCover(isPresented: $vuePortier) {
            EcranPortier(adresse: modele.adresse, connexion: portier?.connexion ?? "", fermer: { vuePortier = false }) { cookies in
                vuePortier = false
                apresPortier(cookies)
            }
        }
        .alert("Serveur", isPresented: $changerServeur) {
            TextField("Adresse", text: $nouvelleAdresse)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
            Button("Par défaut") {
                _ = modele.changerAdresse(Adresse.parDefaut)
                reinitialiser()
            }
            Button("Enregistrer") {
                if modele.changerAdresse(nouvelleAdresse) {
                    reinitialiser()
                } else {
                    message = "Adresse invalide (exemple : https://ccs.mawena.cloud)."
                }
            }
            Button("Annuler", role: .cancel) {}
        } message: {
            Text("Adresse du serveur CCS.")
        }
    }

    private var champsIdentifiants: some View {
        VStack(spacing: 12) {
            TextField("Identifiant Ubuntu", text: $utilisateur)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textContentType(.username)
                .textFieldStyle(.roundedBorder)
                .disabled(occupe)
            HStack {
                Group {
                    if voirMotDePasse {
                        TextField("Mot de passe", text: $motDePasse)
                    } else {
                        SecureField("Mot de passe", text: $motDePasse)
                    }
                }
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textContentType(.password)
                .textFieldStyle(.roundedBorder)
                .disabled(occupe)
                Button {
                    voirMotDePasse.toggle()
                } label: {
                    Image(systemName: voirMotDePasse ? "eye.slash" : "eye")
                }
                .accessibilityLabel(voirMotDePasse ? "Masquer" : "Afficher")
            }
        }
    }

    private var inscription: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Première connexion : ajoute ce secret dans ton appli d'authentification, puis saisis le premier code.")
            Text(secret ?? "")
                .font(.system(.body, design: .monospaced))
                .textSelection(.enabled)
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.carte))
            HStack {
                Button("Copier") {
                    copier(secret ?? "")
                    modele.avis.dire("Secret copié.")
                }
                .buttonStyle(.bordered)
                Button("Ouvrir l'appli") { ouvrirAuthentificateur() }
                    .buttonStyle(.bordered)
            }
        }
    }

    private func reinitialiser() {
        enAttente = nil
        secret = nil
        codeDemande = false
        message = nil
    }

    private func ouvrirAuthentificateur() {
        let hote = Adresse.hote(modele.adresse) ?? "ccs"
        var c = URLComponents()
        c.scheme = "otpauth"
        c.host = "totp"
        c.path = "/CCS:\(utilisateur)@\(hote)"
        c.queryItems = [URLQueryItem(name: "secret", value: secret ?? ""), URLQueryItem(name: "issuer", value: "CCS")]
        guard let url = c.url else { return }
        ouvrirLien(url) { reussi in
            if !reussi { message = "Aucune appli d'authentification ne prend ce lien : copie le secret." }
        }
    }

    private func traiter(_ r: ReponseConnexion) {
        switch r.status {
        case "ok":
            if let t = r.token {
                motDePasse = ""
                let nom = r.user ?? utilisateur.trimmingCharacters(in: .whitespaces)
                modele.connecte(Identifiants(serveur: modele.adresse, utilisateur: nom, jeton: t))
            } else {
                message = "Le serveur n'a pas remis de jeton d'appareil."
            }
        case "code":
            codeDemande = true
            message = "Saisis le code de ton appli d'authentification."
        case "enroll":
            enAttente = r.pending
            secret = r.secret
            code = ""
            message = nil
        case "blocked":
            let minutes = max(1, Int(((r.retryAfter ?? 60) / 60).rounded(.up)))
            message = "Trop d'essais : réessaie dans \(minutes) min."
        default:
            message = r.message ?? "Connexion impossible."
        }
    }

    private func valider() {
        if occupe { return }
        message = nil
        occupe = true
        let adresse = modele.adresse
        let attente = enAttente
        let u = utilisateur.trimmingCharacters(in: .whitespaces)
        let mdp = motDePasse
        let c = code.trimmingCharacters(in: .whitespaces)
        Task { @MainActor in
            let r: ReponseConnexion
            if let p = attente {
                r = await ApiHttp.inscrire(adresse, enAttente: p, code: c)
            } else {
                r = await ApiHttp.appairer(adresse, utilisateur: u, motDePasse: mdp, code: c, nom: ModeleAppli.nomAppareil())
            }
            occupe = false
            if attente != nil && r.status != "ok" && (r.message ?? "").contains("expir") {
                enAttente = nil
                secret = nil
            }
            traiter(r)
        }
    }

    /// Cookies de Portier reçus : on vérifie qu'ils ouvrent CCS, puis on demande un jeton d'appareil.
    private func apresPortier(_ cookies: String) {
        occupe = true
        let i = Identifiants(serveur: modele.adresse, utilisateur: "", cookies: cookies)
        Task { @MainActor in
            do {
                guard let s = try await ApiHttp.session(i) else {
                    occupe = false
                    message = "Portier n'a pas ouvert CCS pour ce compte."
                    return
                }
                // jeton d'appareil durable si le serveur sait le donner, sinon les cookies seuls
                let jeton = await ApiHttp.jetonAppli(i, nom: ModeleAppli.nomModele())
                occupe = false
                var j = i
                j.utilisateur = s.user
                j.jeton = jeton
                modele.connecte(j)
            } catch {
                occupe = false
                message = "Serveur injoignable."
            }
        }
    }
}
