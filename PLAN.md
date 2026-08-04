# PolicyUpdate.eu — Build Plan

Starting focus: EU Green Deal legislation. Longer term: expand to security, tech, and health policy tracks under the same site and infrastructure. The data model and website already support this — see "Multi-field roadmap" below.

## Stack, v2: Lovable + GitHub + Claude Code + Supabase

Everything below this point (through "Phase 3") describes the original plain HTML/CSS/JS + GitHub Pages build, which is done and working. The active direction going forward is a different split:

- **Lovable** — the frontend. A React app, built by prompting (see `LOVABLE_PROMPT.md` for the exact prompt, written to reproduce the navy/gold "Politico Pro" design already validated). Lovable syncs its code to GitHub automatically once connected.
- **GitHub** — the shared repo. Lovable pushes frontend code here; Claude Code works on the `backend/` folder in the same repo, locally.
- **Claude Code** — the backend. Maintains `backend/fetch_digest.py`, `backend/sources.yaml`, and the GitHub Actions workflow that runs it weekly. This is the same scraping logic as before, just now upserting into Supabase instead of writing a local JSON file.
- **Supabase** — the connective layer. One table, `digest_entries` (schema in `supabase/schema.sql`). The backend writes to it with a service-role key (kept as a GitHub Actions secret, never in code); Lovable's frontend reads from it with the public anon key. Also the natural home for the Phase 3 RAG chatbot's vector search later (`pgvector`), so this isn't throwaway setup.

**Setup order:**
1. Create the Supabase project, run `supabase/schema.sql` in its SQL editor.
2. Start a Lovable project, connect Supabase to it, paste in `LOVABLE_PROMPT.md`.
3. Once Lovable's happy with the frontend, connect it to GitHub (creates the repo).
4. Install Claude Code locally, clone that repo, add a `backend/` folder there with `backend/fetch_digest.py`, `backend/sources.yaml`, `backend/requirements.txt`.
5. Move `backend/weekly-digest-supabase.yml` to `.github/workflows/weekly-digest.yml` in that repo (GitHub only reads workflows from that exact path at repo root).
6. Add `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` as GitHub Actions secrets (repo Settings -> Secrets and variables -> Actions) — get both from Supabase's Project Settings -> API page. Never paste the service role key into a file that gets committed.
7. Run the workflow once manually (Actions tab -> Weekly Green Deal Digest -> Run workflow) to confirm entries land in Supabase and Lovable's frontend picks them up.

One practical note on splitting work this way: keep Lovable's generated frontend code and Claude Code's backend code in clearly separate folders (Lovable owns everything it scaffolds at repo root except `backend/`) so the two tools don't end up editing and reverting each other's changes.

## Stack (all free to start)

| Piece | Tool | Why |
|---|---|---|
| Data collection | Python script (`fetch_digest.py`, provided) + RSS feeds | Most think tanks already publish RSS — no scraping needed for these |
| Scheduling | GitHub Actions (free tier) | Runs the script weekly, no server to maintain |
| Website | Framer, Super (Notion), or GitHub Pages + a static template | Pick whichever you can update without touching code |
| Newsletter | Buttondown (free to 100 subs) or Substack (free, no cap) | Both handle GDPR consent/unsubscribe for you |
| Domain | Namecheap/Porkbun | ~€10–15/year |

You will only need to *touch* code in the scraper part. The website and newsletter can be run entirely through their dashboards.

## Week 1, day by day

**Day 1–2: Source list.**
Go through 15–20 EU Green Deal-relevant organizations and find their RSS feed (usually `sitename.org/feed` or `/rss.xml`). I've already confirmed these five work:

- Bruegel — `https://www.bruegel.org/rss.xml`
- E3G — `https://www.e3g.org/feed`
- CAN Europe — `https://caneurope.org/feed`
- IEEP — `https://ieep.eu/feed`
- ECFR — `https://ecfr.eu/feed`

Still worth checking (feed URL unclear or not RSS): CEPS, EPC, Transport & Environment, Agora Energiewende, Ember, WWF EU, ClientEarth, Green10 coalition members. Quick way to check any site: try `/feed`, `/feed/`, `/rss`, `/rss.xml`, or search "[org name] RSS feed." If none exists, note it as a manual-check site for later (v2 problem, not week 1).

Put every confirmed feed into `sources.yaml` (provided, already seeded with the five above).

**Day 3: Get the script running.**
Use `fetch_digest.py` (provided) — it reads `sources.yaml`, pulls everything published in the last 7 days, and writes `digest.md`. Run it locally:

```
pip install -r requirements.txt
python fetch_digest.py
```

Open `digest.md` and sanity-check the results against the actual sites.

**Day 4: Automate it.**
Push the folder to a GitHub repo, add the included `.github/workflows/weekly-digest.yml`. It runs the script every Monday morning and commits the new `digest.md` back to the repo — no server needed. (I can walk you through this step if you haven't set up GitHub Actions before.)

**Day 5: Website skeleton.**
Pick Framer/Super/GitHub Pages, set up one page that will hold the weekly digest, and a newsletter signup embed. Don't over-design — a clean list of "Title — Org — Date — [Link]" per entry is enough for v1.

**Day 6: Newsletter + LinkedIn.**
Set up Buttondown or Substack, connect the signup form to the site. Draft your first LinkedIn post format (a template you'll reuse weekly) so it takes 15 minutes, not an hour, going forward.

**Day 7: Publish v1 and do your first manual digest.**
Copy `digest.md` output onto the site by hand once, by way of proof of concept, before deciding whether to automate the site update too.

## Legal note (recap)

The script only collects titles, dates, links, and (optionally) the RSS summary — not full paper text. Keep it that way: link out to the source, don't mirror full publications. This keeps you inside the TDM/quotation-right exceptions we discussed rather than needing case-by-case permission.

## What v2 could add later

- Sites without RSS (real scraping with BeautifulSoup, one function per site)
- Auto-categorization by policy area (e.g. keyword-matching "CBAM," "ETS," "Nature Restoration Law")
- Auto-draft of the LinkedIn post from `digest.md` using an LLM API call

## Multi-field roadmap

The site is already structured to grow beyond Green Deal without a rebuild:

- `sources.yaml` tags every source with a `field` (`green-deal`, `security`, `tech`, `health`). Adding a new policy field later is just adding sources with that tag — no schema change.
- `site/index.html` has tabs for all four fields already; Security/Tech/Health are disabled ("coming soon") until sources exist for them.
- `site/script.js` filters the digest by whichever tab is active.

To activate a new field: add sources under it in `sources.yaml`, then remove the `disabled` attribute from that tab's `<button>` in `index.html`. Don't launch a field with zero or near-zero sources — an empty or sparse tab undermines trust in the other tabs. Green Deal is your area of expertise, so it's the credible one to launch with; the others should wait until you (or a contributor) can vouch for source quality the same way.

## Domain check

I couldn't get a conclusive answer on whether whatshappening.eu is registered — the WHOIS lookup and a direct fetch of the site both came back empty, which is suggestive but not proof either way. Check directly with a `.eu` registrar (Gandi, EuroDNS, Namecheap) before relying on it being available. Note `.eu` domains require EU/EEA citizenship or residency to register, which shouldn't be an issue for you but is worth knowing.

**Update:** the project is now named PolicyUpdate.eu instead. Same caveat applies — a direct fetch of policyupdate.eu also came back empty, which again is suggestive but not conclusive. Confirm with a registrar before you commit to it, since you mentioned it "seems" free rather than having registered it yet.

## Phase 3 (later): RAG chatbot with citations

Idea: a chatbot that answers user questions by retrieving relevant passages from tracked policy papers and citing them. Technically a well-worn pattern; the harder part for this project is legal, not engineering.

**Why this is a bigger jump than v1/v2.** Everything so far only stores titles, dates, links, and short RSS summaries. A RAG chatbot needs the actual paper text to embed and retrieve from — that's a real change in what you're reproducing and storing, not just a new feature bolted onto the same data.

**The legal issue, concretely.** Reproducing lawfully accessible text for automated analysis (embedding included) is plausibly covered by the TDM exception (Art. 4 DSM Directive / Section 44b German Copyright Act, and equivalents in other member states) — but three things constrain that:
1. Rights holders can opt out, and opt-outs don't have to be your own site's `robots.txt` — a September 2024 Hamburg Regional Court ruling (*Kneschke v. LAION*) held that even a natural-language restriction in a source's terms of use might count as a valid "machine-readable" opt-out, depending on the crawler's sophistication. That question is unsettled and could be appealed, but it means you can't assume a source is fair game just because there's no `robots.txt` block — check each source's ToS when you get here.
2. The TDM exception covers the *mining copy*, not what you show the end user. Retrieving and embedding full text to find relevant passages is one thing; having the chatbot output long verbatim quotes back to a user is a separate act (communication to the public) that needs the quotation right instead — same principle as the current site's "link + short excerpt, don't mirror" rule, just applied to chat answers.
3. Under Section 44b(2)/Art. 4(2), TDM copies must be deleted once no longer needed for the mining purpose — indefinitely retaining full papers in a vector database for a live product sits in murkier territory than a one-off research analysis. Worth getting a real legal read (or writing this up yourself, given your PhD) before launch rather than after.

**Practical implication for now:** don't scrape full text "just in case" while building v1/v2. Keep the current metadata-only model. When you're ready for phase 3, treat full-text ingestion as its own step with its own source-by-source legal check, not a default extension of the RSS scraper.

**Rough stack, when you get there:** chunk full text → embeddings → vector store (Chroma or pgvector — both free at this scale) → retrieval + an LLM (e.g. Claude API) generating an answer that cites sources with short quotes, not long reproductions. Cost at student/early-traffic scale is low — cents per question, likely single-digit euros/month total — but scales with usage, so add caching for repeat questions and a rate limit before this is public-facing.
