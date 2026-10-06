#!/usr/bin/env node
/**
 * translate_node.cjs -- tiny stdin/stdout bridge between fetch_digest.py and
 * the "anylang" translation kit (npm i anylang), which is the open-source
 * translation core behind the Linguist browser extension
 * (https://github.com/translate-tools/linguist). Used for the EU 27
 * Ministries sources whose national feeds are not in English.
 *
 * Protocol:  stdin  -> {"from": "cs", "to": "en", "texts": ["...", ...]}
 *            stdout -> {"translations": ["...", null, ...]}   (same length;
 *                       null = this text could not be translated)
 * Exit code is 0 even when every text failed -- the Python side treats nulls
 * as "leave untranslated" and the language filter then drops those items.
 *
 * Engine chain (first that works wins, per chunk): DeepL API Free (official;
 * only when the DEEPL_API_KEY env var is set) -> Google Translate (free web
 * endpoint) -> Google Translate (token-free variant) -> Lingva (public
 * Google proxy). The last three are unofficial free endpoints that can
 * rate-limit or break without notice, which is why DeepL is the standard
 * and they are only the safety net; the on-disk cache in
 * translation_cache.json means each text is translated once.
 *
 * TRANSLATOR=fake switches to anylang's FakeTranslator (prefixes the input)
 * so the plumbing can be tested offline.
 */
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";
const CHUNK = 12; // texts per request
const PAUSE_MS = 400; // politeness delay between chunks

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (c) => (data += c));
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * DeepL API Free (official). Used first whenever DEEPL_API_KEY is set
 * (free keys end in ":fx" and talk to api-free.deepl.com; paid keys use
 * api.deepl.com). Free tier: 500,000 characters/month. On quota exhaustion
 * (HTTP 456) or auth errors (403) the engine disables itself for the rest
 * of the run so the Google/Lingva fallbacks take over without retrying.
 */
class DeepLTranslator {
  constructor(key) {
    this.key = key;
    this.url =
      process.env.DEEPL_API_URL ||
      (key.endsWith(":fx")
        ? "https://api-free.deepl.com/v2/translate"
        : "https://api.deepl.com/v2/translate");
    this.disabled = false;
  }
  async translateBatch(texts, from, to) {
    if (this.disabled) throw new Error("DeepL disabled for this run");
    const out = [];
    for (let i = 0; i < texts.length; i += 50) {
      // DeepL accepts max 50 texts per request
      const part = texts.slice(i, i + 50);
      const body = {
        text: part,
        target_lang: to.toLowerCase() === "en" ? "EN-GB" : to.toUpperCase(),
      };
      if (from && from !== "auto") body.source_lang = from.toUpperCase();
      const res = await fetch(this.url, {
        method: "POST",
        headers: {
          Authorization: `DeepL-Auth-Key ${this.key}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });
      if (res.status === 456 || res.status === 403) {
        this.disabled = true;
        throw new Error(
          res.status === 456
            ? "DeepL quota exceeded (456)"
            : "DeepL auth rejected (403) -- check DEEPL_API_KEY"
        );
      }
      if (!res.ok) throw new Error(`DeepL HTTP ${res.status}`);
      const data = await res.json();
      const tr = (data.translations || []).map((x) => x.text);
      if (tr.length !== part.length) throw new Error("DeepL length mismatch");
      out.push(...tr);
    }
    return out;
  }
}

function buildEngines() {
  const engines = [];
  const deeplKey = (process.env.DEEPL_API_KEY || "").trim();
  if (deeplKey && process.env.TRANSLATOR !== "fake") {
    engines.push({ name: "deepl", t: new DeepLTranslator(deeplKey) });
  }
  let tr;
  try {
    tr = require("anylang/translators");
  } catch (err) {
    process.stderr.write(`[translate_node] anylang unavailable: ${String(err).slice(0, 100)}\n`);
    return engines; // DeepL alone still works
  }
  if (process.env.TRANSLATOR === "fake") {
    return [{ name: "fake", t: new tr.FakeTranslator() }];
  }
  const opts = { headers: { "User-Agent": UA } };
  engines.push(
    { name: "google", t: new tr.GoogleTranslator(opts) },
    { name: "google-tokenfree", t: new tr.GoogleTranslatorTokenFree(opts) }
  );
  try {
    const unstable = require("anylang/translators/unstable");
    if (unstable.LingvaTranslate) {
      engines.push({ name: "lingva", t: new unstable.LingvaTranslate(opts) });
    }
  } catch (_) {
    /* unstable translators are optional */
  }
  return engines;
}

async function translateChunk(engines, texts, from, to) {
  for (const { name, t } of engines) {
    try {
      const out = await t.translateBatch(texts, from, to);
      if (Array.isArray(out) && out.length === texts.length && out.some((x) => x)) {
        return out.map((x) => (typeof x === "string" && x.trim() ? x : null));
      }
    } catch (err) {
      process.stderr.write(`[translate_node] ${name} failed: ${String(err).slice(0, 160)}\n`);
    }
  }
  return texts.map(() => null);
}

(async () => {
  const req = JSON.parse((await readStdin()) || "{}");
  const texts = Array.isArray(req.texts) ? req.texts : [];
  const from = req.from || "auto";
  const to = req.to || "en";
  const engines = buildEngines();
  const result = [];
  for (let i = 0; i < texts.length; i += CHUNK) {
    const chunk = texts.slice(i, i + CHUNK);
    result.push(...(await translateChunk(engines, chunk, from, to)));
    if (i + CHUNK < texts.length) await sleep(PAUSE_MS);
  }
  process.stdout.write(JSON.stringify({ translations: result }));
})().catch((err) => {
  process.stderr.write(`[translate_node] fatal: ${String(err)}\n`);
  process.stdout.write(JSON.stringify({ translations: [] }));
});
