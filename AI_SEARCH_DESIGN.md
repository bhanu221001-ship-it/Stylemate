# StyleMate — how the AI product search works

A single-page HTML storefront (~1,200 fashion SKUs) that answers a shopper's
plain-language request using a **local Qwen running on Ollama**. No server, no
retrieval index, no embeddings; the browser calls
`http://localhost:11434/api/chat` directly.

The model is used as an **interpreter for the sentence, not as memory holding
the catalogue**. It turns the request into search conditions; ordinary code
searches all 1,200 SKUs; a second call ranks the shortlist only when that will
change the answer.

This document describes the design as built, including its measured limits, so
it can be reviewed for latency and answer quality.

## 1. Two separate entry points

| Input | Behaviour |
|---|---|
| Header search bar | Ordinary keyword filter over the current category. No model. Instant. |
| "Ask StyleMate anything" → **Find my match** | The AI path described below. |

Only the second calls the model. This split is deliberate: a shopper typing one
word should not wait on a 7B model.

## 2. Stage A — understand the request (one small call)

Sent: the sentence, plus the catalogue's **vocabulary** — category ids, the
distinct article types, colours, usages, the price range, and the shopper's
wardrobe for duplicate-checking. **No product rows.** ~430 tokens.

The model must separate two kinds of thing, and is told never to invent the first:

* **Hard** — stated requirements. Category, article type, colour, audience,
  price limits. A product breaking one is excluded.
* **Soft** — preferences, occasions, moods. These only affect ordering.

It also classifies the request as `precise`, `vague` or `insufficient`.

```json
{"query_type":"precise","intent":"Men's t-shirts under Rs1,200",
 "hard":{"categories":["western"],"articleTypes":["Tshirts"],"colours":[],
         "audience":"men","max_price":1200,"min_price":null},
 "soft":{"keywords":[],"occasion":null,"styles":[]},
 "clarify":"","message":"Here are men's t-shirts under Rs1,200."}
```

## 3. Stage B — search in code

Hard constraints are enforced by code over every SKU, never by the model. Price
in particular is parsed from the sentence with a regex and **overrides** the
model's number: a model that returns `max_price: 12000` for "under ₹1,200" is
corrected rather than trusted. Soft preferences become a ranking score, never a
filter.

## 4. Stage C — rank the shortlist (second call, conditional)

Runs only when it will change the answer:

| Request | Behaviour |
|---|---|
| `precise`, short shortlist | no second call — returns after one |
| `precise` with soft preferences and >12 candidates | rank |
| `vague` | always rank; this is where judgement beats a lexical score |
| `insufficient` | no search at all; ask one short question with category buttons |

A vague request never gets an invented hard constraint. If its filters match
nothing, the code takes an **even spread across all categories** and has the
model choose from that, rather than showing an empty page. A failed ranking call
keeps the filtered results.

Sent for ranking: up to 60 candidate rows, text only —

```
western-1000|Fila Men Black Tshirts|Tshirts|Black|m|Casual
id|name|type|colour|audience(m/w/u)|usage
```

**No image data is ever sent** — no file paths, no URLs, no base64. Images stay
in the browser and are matched back to the model's answer by SKU id.

## 4b. The legacy path, kept for comparison

A setting switches back to the original design: one call carrying as many SKU
rows as the context allows (~430 rows, ~15,500 tokens), with the model doing the
searching. Both paths log latency and token counts, so the two can be measured
against each other. The constraint below is why that path is no longer default.

## 5. The hard constraint, measured

From Ollama's log on a real full-catalogue search:

```
msg="truncating input prompt" limit=16386 prompt=40713 keep=4 new=16386
```

* These rows cost **2.07 characters per token** (not the ~3.6 of prose).
* Ollama accepts a prompt of at most **half of `num_ctx`**; the rest is reserved
  for generation. At `num_ctx 32768` that is **16,386 tokens**.
* Over that it does not error — it silently keeps the first 4 tokens and the
  last 16,382.

So 1,200 SKUs (~40,700 tokens) would need `num_ctx` near 85,000, beyond an
11.8 GB machine. The page therefore sends ~430 rows (~14,000 tokens) per search
and states in the UI that it did so.

## 6. Failure ladder

A failed attempt is retried only when the reply is unusable, never on a network
error or timeout:

1. Full selected catalogue.
2. **Repair** — the model's own bad reply is fed back with a correction naming
   the specific mistake.
3. **Facets only** (~1,400 tokens: category names, brands, colours, no rows) —
   the model returns filters and the storefront executes them.
4. **Keyword rules** in the browser. No model. Always returns something.

Every attempt is written to `logs/<timestamp>_<query>.json` with the full
request body, raw reply, `prompt_eval_count`, `eval_count`, latency and outcome.

## 7. Current numbers

| | |
|---|---|
| Catalogue | ~1,200 SKUs, 6 categories (HuggingFace fashion-product-images) |
| Stage A prompt | ~430 tokens, no product rows |
| Stage C prompt | up to 60 rows, only when needed |
| Legacy single-call path | ~430 rows, ~15,500 tokens |
| Model | qwen2.5:7b via Ollama, Apple Silicon, 11.8 GB unified memory |
| Observed latency | pre-two-stage build: tens of seconds up to the 300 s timeout |
| Generation budget | 1,200 tokens, max 24 SKU ids returned |

## 8. Where review would help

1. **Latency.** Stage A is now ~430 tokens, so prefill is no longer the
   bottleneck; generation is. Would a smaller model, a tighter grammar or a
   lower `num_predict` help more than further prompt work? Does the Stage C
   call earn its seconds often enough to keep?
2. **Retrieval.** Scoring is lexical. Would local embeddings (e.g.
   `nomic-embed-text`) over ~1,200 short product strings be cheaper end to end
   than sending rows as text, given the embedding pass is one-off?
3. **Model size.** Is a 7B the right choice for "pick ids from a list", or would
   a 1.5–3B with a tighter grammar do it faster at equal quality?
4. **Structured output.** `format: "json"` constrains syntax but not schema.
   Would a GBNF grammar restricting `skus` to literal ids from this request's
   row set remove invented ids and shorten generation?
5. **Fine-tuning.** Is a LoRA on (query → chosen SKU) pairs worthwhile here, or
   is prompt and retrieval work the better return?
6. **Quality measurement.** What is a defensible offline metric for "did the
   model pick the right products", given no click data and a synthetic catalogue?
