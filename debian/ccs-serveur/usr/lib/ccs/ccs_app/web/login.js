// Écran de connexion : identifiant et mot de passe Ubuntu, puis code ; à la première connexion,
// QR code à scanner et premier code à saisir.
import { post } from "./api.js";

export function showLogin(onDone) {
  const root = document.getElementById("login");
  const form = document.getElementById("login-form");
  const codeField = document.getElementById("login-code-field");
  const enroll = document.getElementById("login-enroll");
  const message = document.getElementById("login-message");
  const submit = document.getElementById("login-submit");
  let pending = null;

  document.getElementById("shell").hidden = true;
  root.hidden = false;
  form.elements.user.focus();

  const say = (text) => { message.textContent = text || ""; };
  const askCode = () => {
    codeField.hidden = false;
    form.elements.code.required = true;
    form.elements.code.value = "";
    form.elements.code.focus();
  };

  form.onsubmit = async (e) => {
    e.preventDefault();
    say("");
    submit.disabled = true;
    const f = form.elements;
    const remember = f.remember.checked;
    let r;
    try {
      r = pending
        ? await post("/api/enroll", { pending, code: f.code.value.trim(), remember })
        : await post("/api/login", { user: f.user.value.trim(), password: f.password.value,
          code: f.code.value.trim(), remember });
    } catch {
      r = { status: "error", message: "Serveur injoignable." };
    }
    submit.disabled = false;
    if (r.status === "ok") {
      f.password.value = "";
      f.code.value = "";
      pending = null;
      enroll.hidden = true;
      root.hidden = true;
      onDone(r.user);
    } else if (r.status === "code") {
      askCode();
    } else if (r.status === "enroll") {
      pending = r.pending;
      document.getElementById("login-qr").src = `data:image/svg+xml;base64,${btoa(r.qr_svg)}`;
      document.getElementById("login-secret").textContent = r.secret;
      document.getElementById("login-credentials").hidden = true;
      enroll.hidden = false;
      askCode();
    } else if (r.status === "blocked") {
      say(`Trop d'essais : réessaie dans ${Math.max(1, Math.ceil(r.retry_after / 60))} min.`);
    } else {
      say(r.message || "Connexion impossible.");
      if (pending) f.code.select();
    }
  };
}
