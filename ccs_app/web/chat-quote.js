// Répondre en citant un message du chat : format du message envoyé (logique pure, testée avec node).
// Le message commence par la citation, en bloc Markdown, puis la réponse :
//
//   > **Claude :**
//   > le passage cité
//
//   la réponse
//
// L'auteur est « Claude » (une de ses réponses) ou « Moi » (un message de l'utilisateur). Ce texte
// est celui du journal : le même format sert à la relecture pour montrer la citation à part.
// Même code que `ccs_app/chat_quote.py`.
export const CLAUDE = "claude";
export const ME = "moi";
export const LABELS = { [CLAUDE]: "Claude", [ME]: "Moi" };     // dans le texte envoyé
export const SHOWN = { [CLAUDE]: "Claude", [ME]: "Toi" };      // à l'écran
export const QUOTE_MAX = 1200;        // message cité en entier : au-delà, seulement son début
export const SELECTION_MAX = 4000;    // passage choisi par l'utilisateur : coupé plus loin
export const CUT_MARK = " […]";
const HEADS = new Map(Object.entries(LABELS).map(([author, label]) => [`> **${label} :**`, author]));

const clean = (text) => String(text || "").replace(/\r\n/g, "\n").trim();

// Texte à citer : sans blancs autour, coupé à `limit` caractères (entre deux mots si possible).
export function excerpt(text, limit = QUOTE_MAX) {
  const chars = [...clean(text)];                 // par caractère, pas par demi-code (émojis)
  if (chars.length <= limit) return chars.join("");
  let cut = chars.slice(0, limit).join("");
  const space = Math.max(cut.lastIndexOf(" "), cut.lastIndexOf("\n"));
  if (space >= cut.length - 80) cut = cut.slice(0, space);
  return cut.trimEnd() + CUT_MARK;
}

// Message à envoyer : la citation puis `body`. Sans citation valable : `body` tel quel.
export function compose(author, quoted, body = "") {
  const text = clean(quoted);
  if (!(author in LABELS) || !text) return body;
  const head = [`> **${LABELS[author]} :**`, ...text.split("\n").map((line) => (line.trim() ? `> ${line}` : ">"))].join("\n");
  return body ? `${head}\n\n${body}` : head;
}

// Citation en tête d'un message de l'utilisateur ({ author, text, body }), ou null.
export function split(text) {
  if (typeof text !== "string" || !text.startsWith("> **")) return null;
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const author = HEADS.get(lines[0].trimEnd());
  if (!author) return null;
  const quoted = [];
  let i = 1;
  for (; i < lines.length && lines[i].startsWith(">"); i += 1) {
    const line = lines[i].slice(1);
    quoted.push(line.startsWith(" ") ? line.slice(1) : line);
  }
  const quotedText = quoted.join("\n").trim();
  if (!quotedText) return null;
  let rest = lines.slice(i);
  if (rest.length && !rest[0].trim()) rest = rest.slice(1);
  return { author, text: quotedText, body: rest.join("\n") };
}

// Texte d'un message de l'utilisateur à citer à son tour : sa réponse, pas ce qu'il citait.
export function sourceText(text) {
  const q = split(text);
  if (!q) return text;
  return q.body.trim() ? q.body : q.text;
}

// Aperçu sur une ligne (bandeau au-dessus de la saisie).
export function oneLine(text, limit = 140) {
  const line = String(text || "").split(/\s+/).filter(Boolean).join(" ");
  return line.length > limit ? `${line.slice(0, limit - 1)}…` : line;
}
