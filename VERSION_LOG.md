# StyleMate — version log

Internal change log. The filename is the version.
Newest first. Each entry: what prompted it, what changed, why.

> ## ⚑ END OF THE OLLAMA LINE
> **`StyleMate_frontend_v15_ollama_v8.html` is the LAST version built on Ollama.**
> From here the project migrates to the Gemini API. Everything below this line
> that carries an `ollama_vN` name is the local-model era and is kept for
> reference, not for further work.
>
> What that migration has to deal with, recorded while it is fresh:
> - The page calls Ollama **directly from the browser**. Gemini cannot work that
>   way: an API key in a page is readable by anyone who opens it. The calls must
>   move behind `backend/app/llm/` — which already has a Gemini path and a
>   provider router, so the destination exists.
> - `backend/.env` already holds `GEMINI_API_KEY` and `SM_PROVIDER`. Setting the
>   key and `SM_PROVIDER=gemini` is the switch, once the page talks to the backend.
> - Model shortlist and costed comparison: `Gemini_model_shortlist.xlsx`.
> - Worth keeping from the Ollama era, because none of it is model-specific:
>   the two-stage pipeline (understand → search in code → rank only when it
>   helps), hard-vs-soft constraint separation, prices parsed in code rather
>   than trusted to the model, the balanced-brace JSON parser, the off-brief
>   guard, and the audit log.

---

## `StyleMate_frontend_v15_gemini_v3.html` — 28 Oct 2026 — CAMERA + WARDROBE LAYOUT

**Prompted by:** "when I click camera the Capture option needs scrolling; the
wardrobe has oversized images with the text squeezed into the corner."

**Camera (Colour Studio, and Shop a Look which shares the controls).**
- Root cause: `#tone-ph{display:grid}` outranked the browser's `[hidden]` rule,
  so the big "Curious about your colour?" placeholder stayed on screen after
  the camera started and the live video stacked underneath it, pushing
  Capture below the fold. Added `#tone-ph[hidden]{display:none}`.
- While live, the preview is capped to `min(46vh, 380px)` with `contain` (the
  preview shows exactly the frame that will be captured), and the
  Capture / Cancel bar is sticky at the bottom of the panel as a backstop.
- Verified at 1280×720 with a stand-in camera stream: the placeholder hides,
  Capture is on screen with the panel unscrolled, capture still works, and the
  panel returns to normal afterwards. Same for the Shop a Look camera.

**Wardrobe drawer.**
- Root cause: `#drawer-content img.real` (an id rule) beat `.ward-row img.real`,
  so Myntra's 360×480 photos rendered at full size. HuggingFace thumbnails were
  small enough that this never showed before.
- Thumbnails are now 120×160 (a third of before), text gets the rest of the row.
- Intro said "Six backdated orders"; it now states the real count (5, since
  Beauty left the catalogue).

---

## `StyleMate_frontend_v15_gemini_v2.html` — 28 Oct 2026 — MYNTRA CATALOGUE + SHOP A LOOK

**Prompted by:** "upload a photo of a person, have the AI recognise the t-shirt,
jeans, watch, bands, lockets, give that to the Python backend, search the
catalogue for similar SKUs and recommend them. Use 1,000 Myntra SKUs across 5
categories instead of HuggingFace. Send the image once, turn it into text, and
use semantic search."

**Catalogue: 1,000 Myntra SKUs replace the HuggingFace fetch.**
- `stylemate/build_myntra_catalogue.py` (run once; `--force` to rebuild) streams
  the 1.4 GB `myntra dataset/myntra202305041052.csv` in ~14 s, standard library only.
- The CSV has no category or colour column, but each product URL does:
  `myntra.com/<type>/<brand>/<slug>/<id>` — type from the path; gender, colour
  and the search text from the slug.
- 5 categories: Western 340 · Accessories 260 · Footwear 170 · Ethnic 130 ·
  Sports 100. Beauty dropped (nothing in an outfit photo maps to it, and with it
  the wardrobe's consumable/refill demo line).
- Per type: most-rated first, rating ≥ 3.5 and ≥ 10 ratings, max 2 per brand,
  alternating men/women, no kids' items, re-listed duplicates removed.
- Real price, MRP, discount, rating and photo (Myntra CDN, 360×480). 169 SKUs
  have no colour anywhere in their URL or name and say "Not specified".
- Outputs `backend/app/data/myntra_catalogue.json` (the backend's source of
  truth) and `frontend/catalogue.js` (for a file:// page). The backend also
  serves `/catalogue.js` from the JSON, so the page and backend always agree.
- Backend pins it: replaces the SQLite table on startup when the file changes;
  `/api/catalogue/sync` from the browser is now a no-op.

**Shop a Look: image once → text → semantic match.**
1. Page shrinks the photo to 768 px JPEG; backend enforces the same bound.
2. ONE Gemini vision call (`gemini-3.5-flash-lite`) with a response schema:
   per item slot, catalogue article type, colour, pattern, listing-style
   details, worn_by and a one-line product-title description. Prompt walks
   wrists/hands/neck/ears/face/waist so small accessories are not missed.
   Measured: ~1,600–1,700 in / 270–500 out tokens, 0 thinking tokens, ~3.5 s.
3. Cached by image + prompt hash: the same photo is never sent twice.
4. Matching in Python, no chat model: hard filters (slot, audience from the
   garment's cut), then 45% embeddings (`gemini-embedding-001`, 768-d) +
   20% BM25 + 15% same article type + 15% same/related colour + 5% audience.
   Catalogue embedded once (10 batch calls, cached in `var/cache/`); each look
   is ONE embedding request for all its items.
5. "As worn / Men / Women" re-matches via `POST /api/look/match` from the text
   only — zero image tokens.
- Verified: jeans photo → the exact SKU ranked #1; t-shirt photo → exact SKU #1
  plus cap, track pants and sneakers found; kurta photo → earrings, bangles,
  clutch found (the kurta itself read as "ethnic dress").
- Each call writes an audit file to `logs/` (tokens, latency, cached, semantic
  model); the image is never logged.

**Page (v2):** real price / MRP / discount / ★ rating on cards; "Recommended"
now sorts by rating × review count; HuggingFace copy removed; Shop a Look panel
shows what the AI saw, the cost line and the matches. `stylemate-room.js`
rewritten for the new flow (falls back to the colour-only matcher if the
backend is down).

**Launcher:** frontend assets are now copied into `app/static` when they
*differ*, not only when missing, so edits to `stylemate-room.js` reach the server.
Two more launcher changes (both copies of `start_stylemate.command`):
- New step 2/5 **Catalogue**: if `backend/app/data/myntra_catalogue.json` is
  built, it says so and does nothing; if missing or unreadable, it builds it from
  the CSV (~15 s); if the CSV is gone too, it says exactly what to restore.
  Recreates `frontend/catalogue.js` from the JSON if only that is missing.
- The page served is the **highest version number** (`v15_gemini_v2` >
  `v15_gemini_v1`, `v16_*` > `v15_*`), not the newest file date.
- Tested: built → skipped; JSON missing → rebuilt with identical rows; JSON and
  CSV missing → clear message, no crash; catalogue.js missing → recreated.

**The Myntra CSV is not needed at runtime.** Only `build_myntra_catalogue.py`
reads it. `archive (1).zip` (118 MB) holds the identical CSV, so the 1.3 GB
`myntra dataset/` folder can go as long as the zip is kept for rebuilds.

---

## `StyleMate_frontend_v15_gemini_v1.html` — 28 Oct 2026 — FIRST GEMINI VERSION

**The key never touches the browser.** The page used to call Ollama directly
from JavaScript. A Gemini key cannot live there — anyone who opens the page can
read it. So:

- New backend endpoint **`POST /api/llm/chat`** relays one model call. The
  server holds the key and picks the provider; the page never learns which.
- The page's `llmChat()` now posts there. That one function underpins the whole
  pipeline — query parsing, reranking, the colour studio's photo reading — so
  all of it moved to Gemini in a single change.
- `transport: 'auto'` → backend when served over http(s), direct Ollama when
  opened as a `file://` page, so the standalone page still works.

**Models** (ids verified against the Gemini docs, 28 Oct 2026):
`SM_GEMINI_TEXT_MODEL=gemini-3.1-flash-lite` — cheapest current-gen model that
still reasons, and the only one defaulting to *minimal* thinking, so reasoning
is opt-in rather than billed by default. `SM_GEMINI_VISION_MODEL=gemini-3.5-flash-lite`
— one call per photo, so a better model costs almost nothing there. Both are
listed with image input on the pricing page.

**Fixed while testing:** `base64.b64decode` ignores characters outside the
base64 alphabet by default, so a corrupt image decoded to `b""` and reached the
model as an empty picture with a 200 response. Now `validate=True`, and empty
images are rejected.

**Not done, deliberately:** `/api/llm/chat` is an unauthenticated relay to a
paid API. Fine on localhost. Before this is exposed to the internet it needs
auth and a rate limit, or anyone who finds the URL spends the key's quota.

---

## `stylemate/` — StyleMate v15 + Ollama v8 — 28 Oct 2026  ⚑ FINAL OLLAMA VERSION

The project moves into the `stylemate/` folder: a FastAPI backend that serves
the page, the 3D fitting room (three.js, OrbitControls, stylemate-room.js), and
an `/api/*` layer with its own Gemini/Ollama router.

**Checked first:** v15 already contains our Ollama work **through v8** — the
two-stage pipeline, the vision colour studio, the balanced-brace JSON parser and
the palette badge are all in it. Nothing needed porting. The page still calls
Ollama directly from the browser; the backend's `/api/*` routes are available
but unused by the page today.

**Page:** `frontend/StyleMate_frontend_v15_ollama_v8.html` is now the source of
truth. The launcher copies it to `backend/app/static/index.html` when it differs,
so the version lives in the filename without breaking the server's static mount.

**`.env` — and a gap worth knowing about.** `backend/.env.example` says "copy to
.env", but nothing in the code read a .env file and `python-dotenv` is not a
dependency: a .env would have sat there being silently ignored. Added a
dependency-free loader to `config.py` (KEY=VALUE, `#` comments, optional
`export`, optional quotes). **A value already in the shell wins** — the launcher
and the shell are more specific than a file in the project.

**The page gets its settings from .env** through a new `GET /api/config`, which
publishes the non-secret half: Ollama host, text and vision model, num_ctx,
timeout, results, log sink. `GEMINI_API_KEY` is deliberately NOT in it — only
whether a key is present. The page adopts these at boot, and anything the
shopper changed by hand in Agent settings still wins over them.

**One launcher:** `start_stylemate.command`. Loads .env, restarts Ollama with
`OLLAMA_ORIGINS=*`, `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_MAX_LOADED_MODELS=2`,
checks both models (`--pull` to fetch), starts the log sink, creates the venv
and installs requirements on first run, starts uvicorn, verifies the 3D assets
are in `app/static`, prints the live config and opens the browser. Ctrl-C stops
the backend and sink; Ollama is left up deliberately.

`.env` defaults set here: `SM_VISION_MODEL=qwen3-vl:8b` (the one pulled and
working; the project example names `qwen2.5vl:7b`), `SM_NUM_CTX=32768` and
`SM_LLM_TIMEOUT=300`.

---

## `stylemate_v10_featurebar_mysize_ollama_v8.html` — 28 Oct 2026

**Prompted by:** "send the saved palette and its recommended colours with the AI
query, and tag matching products with something visually distinct from the
existing tags."

**The palette now travels with the request.** When the Colour Studio has been
used, both model calls carry it:
- Stage A (understand) gets the palette name, depth and its colours.
- Stage C (rank) gets them again, where they actually change the order.

Sent as a **soft preference, stated twice**: "this is a PREFERENCE, not a
requirement… never make a colour a hard constraint because of this list". A
shopper who asks for a black shirt gets a black shirt whether or not black is in
their palette. The palette orders results; it never filters them. With no
palette saved, nothing is added to the prompt — no empty header.

**New badge: ✦ SUITS YOUR PALETTE**, deep berry `#6e3b5a` with white text.
- 8.6:1 contrast on white, above the 4.5:1 AA threshold.
- 156° from the wardrobe green, 112° from the "similar" blue-grey, 76° from the
  refill amber — distinct from all three at a glance.
- Orange was the suggestion, but the refill badge is already dark amber and the
  whole page sits on a warm rust-and-paper palette, so an orange badge would
  have read as a variant of an existing tag rather than a new kind of thing.

Ribbons now **stack** in a flex column, so an item can be both "in your
wardrobe" and "suits your palette" instead of one hiding the other. The card's
footnote line explains the match in words: "Maroon is in the warm palette you
saved in the Colour Studio."

The badge shows whenever a palette is saved, not only after an AI search — it
reflects the saved preference, which is true while browsing too. Switching
palette re-badges everything on the next render; the colour set is cached by
palette+depth and invalidates on change.

The agent trace says when the palette was sent and that it ordered rather than
filtered.

---

## `stylemate_v10_featurebar_mysize_ollama_v7.html` — 28 Oct 2026

**Prompted by:** "AI READING UNAVAILABLE — the model replied, but not with
usable JSON. Diagnose why."

**Cause: the JSON parser, not the model.** `extractJson` took everything between
the first `{` and the last `}`. Tested against nine replies a reasoning model
really produces, **five failed** — and qwen3-vl reasons before it answers:
- an unclosed `<think>` block when the token budget runs out mid-thought
- braces inside that reasoning, which the first-to-last span swallowed
- the reply arriving in `message.thinking` with `content` empty
- JSON truncated by `num_predict`
- two objects in one reply, the wrong one picked

**Fixes**
- Parser rewritten: scans for *balanced* objects with string-awareness, and
  callers pass the keys their answer should have, so the right object wins when
  there is more than one. 9 of 9 now behave correctly.
- `think:false` sent on the vision call so the model answers instead of
  reasoning into its budget; a 400 retries without the field for models that
  do not accept it.
- `message.thinking` is read when `content` comes back empty.
- Vision `num_predict` 400 → 900; one automatic retry at 1,400 with a blunt
  "raw JSON only" instruction.
- When it still fails, the panel **shows the raw reply**, the token count and
  how much of it was reasoning. "Not usable JSON" with the reply hidden is an
  error nobody can act on.
- Log records gained `thinking_chars` and `content_was_empty`.

---

## `stylemate_v10_featurebar_mysize_ollama_v6.html` — 28 Oct 2026

**Prompted by:** "run qwen3-vl:8b too — send the Colour Studio photo to the
vision model, ask for undertone and depth, explain what they mean, say it is an
AI response, and if there is no person in the image say so."

**A second model, for the Colour Studio.**
- `qwen3-vl:8b` is called on capture or upload. The photo is re-encoded to
  768px JPEG, sent as base64 in `messages[].images` on Ollama's native
  `/api/chat`, with `num_ctx 4096` — one photo and one question need nothing
  like 32k, and the two models share the same memory.
- Returns `person_detected`, `skin_visible`, `undertone`, `depth`, `confidence`,
  `observation`, `caveat`. Undertone and depth are applied to the selectors only
  when the value is one of the allowed ones; `"bronze"` is ignored.
- The panel shows the reading, the model's confidence, what it saw, and any
  caveat, labelled as a local AI estimate the shopper overrides with one tap.
- Definitions of undertone and depth are the **page's** fixed words, not the
  model's. A definition that changes per call is not a definition.

**No person in the photo.** The model is told to say so rather than read a skin
tone off a sofa. Critically, "no person" is treated as an **answer**, not a
failure: the pixel-average fallback does *not* then run. Getting this wrong
would have had the old estimator guess a skin tone from a dog photo — which is
precisely the nonsense the vision model was added to prevent. The pixel
estimate now runs only when the model is genuinely unavailable.

**Honesty fix.** The studio used to say "Nothing is uploaded, stored or sent
anywhere." The photo now goes to Ollama, so it does leave the page even though
it never leaves the machine. New wording: "read on this computer… goes to the
model running at localhost and nowhere else."

**Log hygiene.** The base64 photo is stripped from the audit record — ~100 KB
per call, and no reason to write a picture of someone's face to disk. The
prompt is logged, the pixels are not. Records now carry `has_image` and the
model that actually ran.

**Running two models.** `runall.sh` sets `OLLAMA_MAX_LOADED_MODELS=2` so Ollama
holds both instead of evicting one on each switch, checks whether the vision
model is pulled, offers `--pull-vision`, and reports total VRAM with a note that
a 7B plus an 8B on ~12 GB is tight — Ollama may swap one out and reload on
demand. Nothing breaks either way; the first call after a swap is just slower.

---

## `stylemate_v10_featurebar_mysize_ollama_v5.html` — 28 Oct 2026

**Prompted by:** "logs are getting downloaded every time I send a query — I just
want them in my folder", and the upload of `stylemate_v10.html`.

**Ported v5 onto the v10 base.** v10 is v8 plus ~40 lines, so the v8→v10 delta
was applied to the v5 file rather than re-applying 25 Ollama edits onto v10 —
far fewer ways to go wrong. 10 of 13 regions merged automatically; three were
touched by both sides and were merged by hand:
- `card()` — v10's apparel size picker plus v5's "similar to one you own" ribbon.
- Settings modal — v10's provider/API-key fields plus v5's pipeline switch.
- A duplicated "My size" feature-bar button, left behind by the move.

Gained from v10: per-item S/M/L/XL picker with a size-chart modal, a model
provider dropdown and API-key field (UI only, not wired), sidebar relabelled
"Agent model".

**Logs no longer download.** `logFallbackDownload` now defaults to **false**, so
nothing lands in Downloads. Files are written only by the sink, into `logs/`.

**Why the sink was never running:** macOS ships a `/usr/bin/python3` that is a
stub — it opens the Xcode command-line-tools dialog and exits. That is what
`sink.log` contained, so no log file was ever written, which is why the
browser-download fallback was firing on every search.
- Added `serve_with_logs.js`, a Node version of the sink, same endpoints and
  same path-traversal guard.
- `runall.sh` now probes for a runtime that actually *runs* (`python3 -c 'print(1)'`,
  then homebrew pythons, then `node`) and reports the exact fix if none works:
  `xcode-select --install` or `brew install node`.

---

## `stylemate_v8_featurebar_mysize_ollama_v5.html` — 28 Oct 2026

**Prompted by:** ChatGPT's two notes on architecture (use the model as a query
interpreter, not as catalogue memory; handle vague queries by relevance rather
than by inventing filters), plus "what do we do when the query is vague?"

**The change: a two-stage pipeline, now the default.**

| | v4 and earlier | v5 |
|---|---|---|
| Model's job | read ~430 product rows and pick | read one sentence, return conditions |
| First call | ~15,500 tokens | ~430 tokens (**97% smaller**) |
| Product rows in call 1 | ~430 | none |
| Calls for a precise query | 1 | 1 |
| Calls for a vague query | 1 | 2 (understand, then rank) |
| Price enforcement | model | code |

- **Stage A — understand.** One small call: the sentence plus the catalogue's
  *vocabulary* (category ids, article types, colours, usages, price range). No
  product rows. Returns hard constraints, soft preferences and a `query_type`.
- **Stage B — search.** Ordinary code over every SKU. Hard constraints are
  enforced here. A price cap is a number comparison, not something to reason about.
- **Stage C — rank.** A second call, only when it will change the answer: a
  vague request, or many candidates with soft preferences to order by. A precise
  request with a short shortlist returns after one call.

**Vague and empty queries.**
- `precise` → filter, usually no second call.
- `vague` → never invent a hard constraint; if the filters match nothing, take an
  even spread across all categories and let the ranking call choose. This is the
  one case where the second call is clearly worth the time.
- `insufficient` ("hi", "show me stuff") → ask one short question with category
  buttons. Nothing is searched, because guessing would fill the page at random.

**Other fixes in v5**
- A guessed category is no longer applied as a *hard* filter on a vague request.
  "Casual dinner" was quietly becoming `categories: ['ethnic','western']`.
- Prices are parsed from the sentence in code and override the model's number.
  Tested: model says `max_price: 12000` for "under ₹1,200", code wins.
- A failed ranking call keeps the filtered results instead of losing them.
- Settings has a **Search pipeline** switch; `full-catalogue` keeps the old
  single-call path so the two can be measured against each other.

---

## `stylemate_v8_featurebar_mysize_ollama_v4.html` — baseline

The state everything above builds on.

- Search bar is an ordinary keyword filter. AI runs only from "Ask StyleMate
  anything" → **Find my match**.
- Prompt fitted to the context ceiling: Ollama accepts at most half of `num_ctx`
  and silently keeps only the tail past that. Rows are selected by relevance to
  the request, ~430 of 1,200 at `num_ctx 32768`.
- Measured: these rows cost **2.07 characters per token**, not 3.6.
- The request is repeated before the rows and in the task tail, because
  truncation eats the head first.
- Off-brief guard: an answer made entirely of a different product kind than the
  request is rejected and retried.
- Failure ladder: full → repair → facets-only → keyword rules.
- Wardrobe check distinguishes owned / similar / refill, with card tags.
- Audit logging to `logs/*.json`, no UI. `keep_alive: 30m`, `num_predict: 1200`,
  max 24 SKUs returned.
- Text only to the model: no images, paths or base64, ever.

### Known open items
- `sink.log` shows the log sink failing to start on macOS (`xcode-select`
  prompt). Fix with `xcode-select --install`, else no `logs/` files are written.
- A reported "T-shirts under ₹1,200 → 300 s → no results" has not been
  reproduced: the keyword fallback returns 38 results for that query in testing.
  The 300 s is the timeout. Needs the log file from that search to close out.
- Not built yet: local embeddings for semantic retrieval (ChatGPT's Solution 2),
  and catalogue enrichment with occasion/style tags.
