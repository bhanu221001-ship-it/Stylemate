#!/usr/bin/env python3
"""
StyleMate catalogue builder
===========================
Pulls real products from the HuggingFace fashion-product-images dataset and
writes a catalogue the StyleMate page loads, so every card's photo, name,
colour, category and gender come from the SAME record and finally agree.

RUN THIS ONCE. The output is static data; nothing about it changes between
runs unless you change --per-category. runall.sh calls it automatically when
catalogue.js is missing and skips it otherwise.

    pip install datasets pillow
    python3 build_catalogue.py

It writes, next to this script:
    images/<id>.jpg      one real photo per SKU
    catalogue.js         the SKU rows, ready for the page to load

Options:
    --per-category N     SKUs per StyleMate category (default 200)
    --force              rebuild even if catalogue.js already exists
    --local-images DIR   use full-resolution Kaggle originals from DIR

HOW MANY SKUs SHOULD YOU BUILD?
The page sends catalogue rows to Ollama with every search, and Ollama accepts
a prompt of at most half its context window. At num_ctx 32768 that is ~16,000
tokens, which is roughly 450 rows. Above that the page still works — it sends
the rows that best match the request and says so — but if you would rather the
model always see everything, build a smaller catalogue:

    python3 build_catalogue.py --per-category 70 --force     # ~420 SKUs, all sent

Changes from the first version of this script:
  * masterCategory is written out. The page reads it, and it was missing, so
    the specification line and the agent's category index were both short a field.
  * Products are sampled evenly across each category instead of taking the first
    200 rows. The dataset is ordered, so "first 200" meant one narrow slice —
    a few brands, a couple of article types — and the page then looked like it
    only sold flip-flops.
  * Metadata is read without decoding images, so the scan is much faster; images
    are decoded only for the rows actually chosen.
  * A NaN year no longer crashes the run.
"""
import argparse
import collections
import json
import os
import sys

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(OUT_DIR, "images")
DATASET = "ashraq/fashion-product-images-small"   # mirror of the Kaggle set
MAX_EDGE = 900
CATS = ["ethnic", "western", "footwear", "beauty", "accessories", "sports"]

ETHNIC_TYPES = {
    "Kurtas", "Kurta Sets", "Kurtis", "Sarees", "Sherwanis", "Sherwani", "Churidar",
    "Salwar", "Salwar and Dupatta", "Patiala", "Lehenga Choli", "Dupatta", "Dhotis",
    "Nehru Jackets", "Blouse", "Jackets-Ethnic",
}
GENDER = {"Men": "men", "Boys": "men", "Women": "women", "Girls": "women", "Unisex": "unisex"}


def bucket(row):
    master = (row.get("masterCategory") or "").strip()
    article = (row.get("articleType") or "").strip()
    usage = (row.get("usage") or "").strip()
    if master == "Footwear":      return "footwear"
    if master == "Personal Care": return "beauty"
    if master == "Accessories":   return "accessories"
    if master != "Apparel":       return None        # Free Items, Home, Sporting Goods
    if usage == "Ethnic" or article in ETHNIC_TYPES: return "ethnic"
    if usage == "Sports":         return "sports"
    return "western"


def safe_year(value):
    """The dataset stores year as a float, and missing ones as NaN.

    int(nan) raises, and NaN is truthy, so a plain `if row.get("year")` guard
    does not protect you.
    """
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return n if 1990 <= n <= 2100 else None


def evenly(indices, count):
    """Pick `count` items spread across `indices` rather than the first `count`.

    The dataset is ordered by id, which correlates with brand, article type and
    year, so taking a prefix gives a lopsided catalogue.
    """
    total = len(indices)
    if count >= total:
        return list(indices)
    step = total / float(count)
    return [indices[int(i * step)] for i in range(count)]


def scan_metadata(ds):
    """Category -> row indices, without decoding a single image.

    Iterating the dataset normally materialises the image column for every row,
    which is the slow part of this script. Dropping that column first turns a
    multi-minute scan into a quick one.
    """
    try:
        meta = ds.remove_columns(["image"])
    except Exception as exc:                      # column name differs: fall back
        print("  (could not drop the image column: %s — scanning the slow way)" % exc)
        meta = ds
    by_cat = collections.defaultdict(list)
    for i, row in enumerate(meta):
        cat = bucket(row)
        if not cat:
            continue
        if not (row.get("productDisplayName") or "").strip():
            continue
        if not (row.get("baseColour") or "").strip():
            continue
        by_cat[cat].append(i)
    return by_cat


def main():
    ap = argparse.ArgumentParser(description="Build catalogue.js for StyleMate.")
    ap.add_argument("--per-category", type=int, default=200,
                    help="SKUs per category (default 200)")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even if catalogue.js exists")
    ap.add_argument("--local-images", default="",
                    help="folder of full-resolution Kaggle originals")
    args = ap.parse_args()

    out = os.path.join(OUT_DIR, "catalogue.js")
    if os.path.exists(out) and not args.force:
        size = os.path.getsize(out)
        print("catalogue.js already exists (%s KB) — nothing to do." % format(size // 1024, ","))
        print("This script only needs to run once. Use --force to rebuild.")
        return 0

    try:
        from datasets import load_dataset
    except ImportError:
        sys.exit("Install the loader first:  pip install datasets pillow")

    print("Loading %s (first run downloads ~500 MB, later runs are cached)..." % DATASET)
    ds = load_dataset(DATASET, split="train")
    print("  %d rows available" % len(ds))

    print("Scanning metadata...")
    by_cat = scan_metadata(ds)
    for c in CATS:
        print("  %-12s %5d candidates" % (c, len(by_cat.get(c, []))))

    os.makedirs(IMG_DIR, exist_ok=True)
    picked = collections.defaultdict(list)
    saved, skipped = 0, 0

    for cat in CATS:
        wanted = evenly(by_cat.get(cat, []), args.per_category)
        if not wanted:
            print("  %s: no rows matched this category" % cat)
            continue
        print("Fetching %d %s images..." % (len(wanted), cat))
        for idx in wanted:
            row = ds[idx]
            sid = row.get("id")
            path = os.path.join(IMG_DIR, "%s.jpg" % sid)
            try:
                src = row.get("image")
                hi = os.path.join(args.local_images, "%s.jpg" % sid) if args.local_images else ""
                if hi and os.path.exists(hi):          # full-resolution original wins
                    from PIL import Image
                    src = Image.open(hi)
                if src is None:
                    skipped += 1
                    continue
                src = src.convert("RGB")
                if max(src.size) > MAX_EDGE:
                    from PIL import Image as _I
                    r = MAX_EDGE / float(max(src.size))
                    src = src.resize((int(src.width * r), int(src.height * r)), _I.LANCZOS)
                src.save(path, "JPEG", quality=92)
            except Exception as exc:
                print("  skipped %s (%s)" % (sid, exc))
                skipped += 1
                continue
            saved += 1
            picked[cat].append({
                "id":     "%s-%s" % (cat, sid),
                "sku":    str(sid),
                "cat":    cat,
                "name":   (row.get("productDisplayName") or "").strip(),
                "colour": (row.get("baseColour") or "").strip(),
                "articleType":    (row.get("articleType") or "").strip(),
                "subCategory":    (row.get("subCategory") or "").strip(),
                # The page reads masterCategory for the specification line and for
                # the agent's word-to-category index. The old build never wrote it.
                "masterCategory": (row.get("masterCategory") or "").strip(),
                "usage":  (row.get("usage") or "").strip() or "Casual",
                "season": (row.get("season") or "").strip() or "All season",
                "year":   safe_year(row.get("year")),
                "audience": GENDER.get((row.get("gender") or "").strip(), "unisex"),
                "photo":  "images/%s.jpg" % sid,
            })

    rows = [r for c in CATS for r in picked[c]]
    if not rows:
        sys.exit("No rows matched. The dataset columns may differ from the expected schema.")

    with open(out, "w", encoding="utf-8") as f:
        f.write("/* Generated by build_catalogue.py from %s - do not edit by hand. */\n" % DATASET)
        f.write("window.STYLEMATE_CATALOGUE=")
        json.dump({"source": DATASET, "perCategory": args.per_category, "rows": rows},
                  f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")

    print("\nWrote %s" % out)
    print("Wrote %d images to %s%s" % (saved, IMG_DIR, (" (%d skipped)" % skipped) if skipped else ""))
    for c in CATS:
        print("  %-12s %4d SKUs" % (c, len(picked[c])))

    types = sorted({r["articleType"] for r in rows if r["articleType"]})
    colours = sorted({r["colour"] for r in rows})
    print("\n%d distinct article types, %d distinct colours" % (len(types), len(colours)))

    # What this costs the agent, in the only units that matter at search time.
    row_chars = sum(len("|".join([r["id"], r["name"], r["articleType"], r["colour"],
                                  r["audience"], r["usage"]])) + 1 for r in rows)
    tokens = int(row_chars / 2.07)          # measured rate for these rows
    print("\nAs an Ollama prompt these rows are about %s tokens." % format(tokens, ","))
    print("Ollama accepts half of num_ctx as prompt, so num_ctx 32768 fits ~16,000.")
    if tokens > 16000:
        fits = int(len(rows) * 16000.0 / tokens)
        print("  -> the page will send the ~%d best-matching rows per search, not all %d."
              % (fits, len(rows)))
        print("  -> to have every row sent every time:")
        print("     python3 %s --per-category %d --force"
              % (os.path.basename(__file__), max(20, int(args.per_category * 16000.0 / tokens))))
    else:
        print("  -> every row fits, so the model sees the whole catalogue each search.")

    print("\nImage source: %s" % ("full-resolution originals from %s" % args.local_images
                                  if args.local_images else
                                  "60x80 dataset thumbnails - pass --local-images for sharper photos"))
    print("catalogue.js and images/ are beside the page. Reload it; the sidebar")
    print("will say 'Real catalogue' when it picks them up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
