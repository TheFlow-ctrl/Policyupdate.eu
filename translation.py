"""
translation.py -- machine translation for non-English sources.

Used only for sources.yaml entries with `translate_from: <ISO 639-1 code>`
(the EU 27 Ministries whose national feeds are not in English). Titles and
summaries are translated to English BEFORE the usual filters run, so the
English keyword gate and the non-English filter see English text.

Engine: DeepL API Free (official, primary; needs the DEEPL_API_KEY env var)
with the "anylang" npm package (the translation core of the Linguist
browser extension, github.com/translate-tools/linguist) as fallback, both
called through translate_node.cjs. Every result is cached in
translation_cache.json so a given text is only ever translated once, and
any failure degrades gracefully: untranslated items keep their original
text and are then dropped by the non-English filter, never published in a
foreign language.
"""
import datetime as dt
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
CACHE_FILE = HERE / "translation_cache.json"
NODE_SCRIPT = HERE / "translate_node.cjs"
CACHE_MAX_AGE_DAYS = 120
SUMMARY_MAX_CHARS = 500  # translate only the start of long summaries
SUBPROCESS_TIMEOUT_S = 240

LANGUAGE_NAMES = {
    "bg": "Bulgarian", "hr": "Croatian", "cs": "Czech", "da": "Danish",
    "nl": "Dutch", "et": "Estonian", "fi": "Finnish", "fr": "French",
    "de": "German", "el": "Greek", "hu": "Hungarian", "it": "Italian",
    "lv": "Latvian", "lt": "Lithuanian", "mt": "Maltese", "pl": "Polish",
    "pt": "Portuguese", "ro": "Romanian", "sk": "Slovak", "sl": "Slovenian",
    "es": "Spanish", "sv": "Swedish",
}


def language_name(code):
    return LANGUAGE_NAMES.get(code, code)


def _today():
    return dt.date.today().isoformat()


def load_cache(path=CACHE_FILE):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache, path=CACHE_FILE):
    cutoff = (dt.date.today() - dt.timedelta(days=CACHE_MAX_AGE_DAYS)).isoformat()
    pruned = {k: v for k, v in cache.items() if v.get("d", "9999") >= cutoff}
    Path(path).write_text(
        json.dumps(pruned, ensure_ascii=False, indent=0, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _cache_key(lang, text):
    return f"{lang}|{text}"


def _call_node(texts, lang):
    """Returns a list of translations (or None per failed text), same
    length as `texts`. Never raises."""
    if not texts:
        return []
    if not NODE_SCRIPT.exists():
        print("  [translation] translate_node.cjs missing -- skipping translation")
        return [None] * len(texts)
    try:
        proc = subprocess.run(
            ["node", str(NODE_SCRIPT)],
            input=json.dumps({"from": lang, "to": "en", "texts": texts}),
            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_S,
            cwd=str(HERE),
        )
        if proc.stderr.strip():
            print("  [translation] " + proc.stderr.strip().splitlines()[-1][:200])
        out = json.loads(proc.stdout or "{}").get("translations", [])
        if len(out) != len(texts):
            return [None] * len(texts)
        return out
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"  [translation] node bridge failed: {exc}")
        return [None] * len(texts)


def translate_entries(entries, lang, cache=None, translate_fn=None):
    """Translates title + summary of each entry to English in place and
    tags it with translated_from / original_title. Entries whose title
    can't be translated are left untouched (the non-English filter removes
    them downstream). Returns (entries, translated_count, failed_count).

    `cache` is a dict shared across calls (load_cache()/save_cache() are the
    caller's job); `translate_fn(texts, lang)` is injectable for tests."""
    translate_fn = translate_fn or _call_node
    cache = cache if cache is not None else {}

    want = []  # unique texts needing a network call, in order
    for e in entries:
        for text in _texts_of(e):
            if _cache_key(lang, text) not in cache and text not in want:
                want.append(text)

    if want:
        results = translate_fn(want, lang)
        for text, out in zip(want, results):
            if out:
                cache[_cache_key(lang, text)] = {"t": out, "d": _today()}

    translated = failed = 0
    for e in entries:
        title = (e.get("title") or "").strip()
        hit = cache.get(_cache_key(lang, title))
        if not title or not hit:
            failed += 1
            continue
        e["original_title"] = title
        e["title"] = hit["t"]
        summary = (e.get("summary") or "").strip()
        s_hit = cache.get(_cache_key(lang, summary[:SUMMARY_MAX_CHARS])) if summary else None
        if s_hit:
            e["summary"] = s_hit["t"]
        elif summary:
            # Don't show a foreign-language summary under an English title.
            e["summary"] = ""
        e["translated_from"] = lang
        translated += 1
    return entries, translated, failed


def _texts_of(entry):
    texts = []
    title = (entry.get("title") or "").strip()
    if title:
        texts.append(title)
    summary = (entry.get("summary") or "").strip()
    if summary:
        texts.append(summary[:SUMMARY_MAX_CHARS])
    return texts
