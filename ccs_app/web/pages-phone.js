// Réglages > Téléphone (ntfy) : interrupteur, serveur, canal secret, QR code à scanner,
// événements, essai d'envoi. Le canal n'est jamais écrit dans un journal ni une adresse.
import { clear, confirmSheet, el, toast } from "./dom.js";
import { busy, settingRow } from "./pages-util.js";

export function phoneGroup(api, s, reload) {
  const box = el("section", { class: "card flat settings-group" }, el("h2", {}, "Téléphone (notifications ntfy)"),
    el("p", { class: "subtle" }, "Reçois sur ton téléphone « attend ta réponse », tâche finie, bascule. Installe l'application ntfy, puis scanne le QR code."));
  const rows = [
    { path: "phone.enabled", label: "Envoyer les notifications", type: "bool" },
    { path: "phone.server", label: "Serveur ntfy", type: "text", hint: "https://ntfy.sh par défaut" },
    { path: "phone.topic", label: "Canal secret", type: "text", hint: "Celui qui le connaît peut lire tes notifications : ne le partage pas." },
    { path: "phone.events.waiting", label: "Une session attend ma réponse", type: "bool" },
    { path: "phone.events.task", label: "Une tâche se termine", type: "bool" },
    { path: "phone.events.switch", label: "Bascule de compte", type: "bool" },
    { path: "phone.events.exhausted", label: "Tous les comptes sont épuisés", type: "bool" },
    { path: "phone.show_content", label: "Montrer la commande", type: "bool",
      hint: "La notification d'autorisation affiche la commande exacte (sinon : le type et le projet seulement)." },
  ];
  box.append(...rows.map((r) => settingRow(api, s, r)));
  const qrBox = el("div", { class: "qr-box", hidden: true });
  const result = el("p", { class: "form-error", role: "status" });
  const newTopic = el("button", { class: "small", onclick: (e) => busy(e.currentTarget, async () => {
    if (!await confirmSheet({ title: "Créer un nouveau canal ?", confirm: "Créer le canal",
      body: "L'ancien canal ne recevra plus rien : il faudra se réabonner au nouveau (QR code) sur chaque téléphone." })) return;
    try { await api.call("phone.new_topic"); } catch (err) { result.textContent = err.message; return; }
    toast("Nouveau canal créé.", { kind: "success" });
    reload();
  }) }, "Créer un nouveau canal");
  const showQr = el("button", { class: "small", onclick: (e) => busy(e.currentTarget, async () => {
    result.textContent = "";
    try {
      const r = await api.call("phone.qr");
      clear(qrBox).append(el("img", { src: r.image, alt: "QR code d'abonnement ntfy" }),
        el("span", { class: "subtle" }, "Scanne-le avec l'application ntfy (ou ouvre ce lien) :"), el("code", {}, r.url));
      qrBox.hidden = false;
    } catch (err) { qrBox.hidden = true; result.textContent = err.message; }
  }) }, "Afficher le QR code");
  const test = el("button", { class: "small primary", onclick: (e) => busy(e.currentTarget, async () => {
    result.textContent = "";
    result.className = "form-error";
    try {
      const r = await api.call("phone.test");
      if (r.ok) toast(r.message, { kind: "success" }); else result.textContent = r.message;
    } catch (err) { result.textContent = err.message; }
  }) }, "Envoyer un essai");
  box.append(el("div", { class: "row" }, newTopic, showQr, test), result, qrBox);
  return box;
}
