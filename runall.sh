#!/bin/bash
# runall.sh — start everything StyleMate needs, with one command.
#
#   bash runall.sh
#
# What it does, in order:
#   1. restarts Ollama with the settings this page needs
#   2. checks the model named in the page is actually pulled
#   3. starts the log sink, which serves the page AND writes logs/*.json
#   4. opens the page in your browser
#
# Stop everything with Ctrl-C.
#
# Flags:
#   --no-restart   leave a running Ollama alone
#   --no-open      don't open the browser
#   --page NAME    serve a specific .html (default: the newest ollama_v1 one)
#   --model NAME   check for this model instead of the page's default
#   --pull-vision  download the vision model if it is missing (one-off, several GB)

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PORT="${PORT:-8765}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"
CTX="${OLLAMA_CONTEXT_LENGTH:-32768}"
RESTART=1; OPEN=1; PAGE=""; MODEL=""; PULL_VISION=0

while [ $# -gt 0 ]; do
  case "$1" in
    --no-restart) RESTART=0 ;;
    --no-open)    OPEN=0 ;;
    --pull-vision) PULL_VISION=1 ;;
    --page)       PAGE="${2:-}"; shift ;;
    --model)      MODEL="${2:-}"; shift ;;
    -h|--help)    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $1 (try --help)"; exit 2 ;;
  esac
  shift
done

STEPS=5
say()  { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }

PIDS=()
cleanup() {
  echo
  say "Stopping"
  for pid in ${PIDS+"${PIDS[@]}"}; do
    kill "$pid" 2>/dev/null && ok "stopped pid $pid"
  done
  # Ollama is left running on purpose: it is slow to load a model, and you
  # usually want it up for the next run. Stop it with: pkill -f 'ollama serve'
  exit 0
}
trap cleanup INT TERM

ollama_up() { curl -fsS --max-time 2 "http://127.0.0.1:${OLLAMA_PORT}/api/tags" >/dev/null 2>&1; }

# ------------------------------------------------------------- 0. catalogue
# The catalogue is static data, already built. This only checks it is there;
# it never rebuilds. If you ever need to rebuild it:
#     python3 build_catalogue.py --force
say "1/${STEPS}  Catalogue"
if [ -f "$HERE/catalogue.js" ]; then
  ok "catalogue.js present ($(wc -c < "$HERE/catalogue.js" | tr -d ' ') bytes)"
  [ -d "$HERE/images" ] && ok "images/ present ($(ls "$HERE/images" 2>/dev/null | wc -l | tr -d ' ') files)" \
                        || warn "images/ is missing, so cards fall back to drawn swatches"
else
  warn "catalogue.js is not here, so the page uses its built-in generated catalogue."
  warn "To build the real one once:  python3 build_catalogue.py"
fi

# ---------------------------------------------------------------- 1. Ollama
say "2/${STEPS}  Ollama"
if ! command -v ollama >/dev/null 2>&1; then
  bad "ollama is not on PATH. Install it from https://ollama.com/download, then re-run."
  bad "Skipping Ollama; the page will fall back to keyword matching."
else
  if ollama_up && [ "$RESTART" = "1" ]; then
    warn "already running — stopping it, because OLLAMA_CONTEXT_LENGTH only takes"
    warn "effect for a server started with it set, and the page needs ${CTX}."
    # The macOS app and a bare `ollama serve` both answer on 11434; kill either.
    pkill -f 'Ollama.app' 2>/dev/null
    pkill -f 'ollama serve' 2>/dev/null
    osascript -e 'quit app "Ollama"' >/dev/null 2>&1
    for _ in $(seq 1 20); do ollama_up || break; sleep 0.5; done
    ollama_up && warn "something is still answering on ${OLLAMA_PORT}; continuing anyway" \
              || ok "stopped"
  elif ollama_up; then
    ok "already running (--no-restart given, leaving it as it is)"
  fi

  if ! ollama_up; then
    say "      starting: OLLAMA_ORIGINS=* OLLAMA_CONTEXT_LENGTH=${CTX} ollama serve"
    # Two models are in play: the text model for search and the vision model
    # for the colour studio. MAX_LOADED_MODELS=2 lets Ollama hold both rather
    # than evicting one to load the other on every switch.
    OLLAMA_ORIGINS="*" OLLAMA_CONTEXT_LENGTH="${CTX}" OLLAMA_MAX_LOADED_MODELS=2 \
      nohup ollama serve > "$HERE/ollama.log" 2>&1 &
    PIDS+=($!)
    for _ in $(seq 1 40); do ollama_up && break; sleep 0.5; done
    if ollama_up; then
      ok "listening on ${OLLAMA_PORT} (log: ollama.log)"
      ok "OLLAMA_ORIGINS=*  so the browser is allowed to call it"
      ok "OLLAMA_CONTEXT_LENGTH=${CTX}  so a full-catalogue prompt is not truncated"
    else
      bad "did not come up within 20s — see ollama.log"
    fi
  fi

  # -------------------------------------------------------------- 2. model
  say "3/${STEPS}  Model"
  if ollama_up; then
    if [ -z "$MODEL" ] && [ -f "${PAGE:-}" ]; then
      MODEL="$(grep -o "model:'[^']*'" "$PAGE" 2>/dev/null | head -1 | sed "s/model:'//;s/'//")"
    fi
    [ -z "$MODEL" ] && MODEL="$(grep -ho "model:'[^']*'" ./*.html 2>/dev/null | head -1 | sed "s/model:'//;s/'//")"
    [ -z "$MODEL" ] && MODEL="qwen2.5:7b"
    HAVE="$(curl -fsS "http://127.0.0.1:${OLLAMA_PORT}/api/tags" | tr ',' '\n' | grep -o '"name":"[^"]*"' | sed 's/"name":"//;s/"//')"
    if [ -z "$HAVE" ]; then
      warn "no models pulled yet.  ollama pull ${MODEL}"
    elif printf '%s\n' "$HAVE" | grep -qx "$MODEL"; then
      ok "${MODEL} is pulled"
    else
      warn "the page asks for '${MODEL}', which is NOT pulled. You have:"
      printf '%s\n' "$HAVE" | sed 's/^/        /'
      warn "either  ollama pull ${MODEL}"
      warn "or open the page's Agent settings and paste one of the names above."
    fi

    # The colour studio needs a model that can see. qwen2.5 cannot.
    VMODEL="${VISION_MODEL:-}"
    if [ -z "$VMODEL" ]; then
      VMODEL="$(grep -ho "visionModel:'[^']*'" ./*.html 2>/dev/null | head -1 | sed "s/visionModel:'//;s/'//")"
    fi
    [ -z "$VMODEL" ] && VMODEL="qwen3-vl:8b"
    if printf '%s\n' "$HAVE" | grep -qx "$VMODEL"; then
      ok "${VMODEL} is pulled (colour studio photo reading)"
    else
      warn "vision model '${VMODEL}' is NOT pulled — the colour studio will fall"
      warn "back to its pixel estimate until it is."
      if [ "$PULL_VISION" = "1" ]; then
        warn "pulling it now; this is a one-off download of several GB."
        ollama pull "$VMODEL" && ok "${VMODEL} pulled" || bad "pull failed"
      else
        warn "to fetch it:  ollama pull ${VMODEL}"
        warn "or re-run:    bash runall.sh --pull-vision"
      fi
    fi

    # Both models loaded at once is roughly 5 GB + 6 GB plus KV cache. On a
    # machine with ~12 GB that is tight: Ollama will unload one if it has to,
    # costing a reload the next time that model is used. Nothing breaks either
    # way, so this is a note, not an error.
    VRAM="$(grep -o 'total_vram="[^"]*"' "$HERE/ollama.log" 2>/dev/null | tail -1 | sed 's/.*="//;s/"//')"
    [ -n "$VRAM" ] && warn "memory: ${VRAM} total. Holding a 7B text model and an 8B vision model"
    [ -n "$VRAM" ] && warn "together is tight; Ollama may swap one out and reload it on demand."
  else
    warn "skipped — Ollama is not answering"
  fi
fi

# ------------------------------------------------------------- 3. log sink
say "4/${STEPS}  Log sink and web server"
if [ ! -f "$HERE/serve_with_logs.py" ] && [ ! -f "$HERE/serve_with_logs.js" ]; then
  bad "no sink script in this folder; the page will keep logs in the tab only."
else
  if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/ping" >/dev/null 2>&1; then
    warn "something already answers on ${PORT}; reusing it"
  else
    # macOS ships a /usr/bin/python3 that is only a stub: it pops the Xcode
    # command-line-tools dialog and exits, which is why the sink never started
    # before. So probe for a runtime that actually runs, Python or Node.
    RUNNER=""; RUNNER_NAME=""
    for c in python3 python3.12 python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
      if command -v "$c" >/dev/null 2>&1 && "$c" -c 'print(1)' >/dev/null 2>&1; then
        if [ -f "$HERE/serve_with_logs.py" ]; then
          RUNNER="$c \"$HERE/serve_with_logs.py\""; RUNNER_NAME="$c"; break
        fi
      fi
    done
    if [ -z "$RUNNER" ] && command -v node >/dev/null 2>&1 && [ -f "$HERE/serve_with_logs.js" ]; then
      RUNNER="node \"$HERE/serve_with_logs.js\""; RUNNER_NAME="node"
    fi

    if [ -z "$RUNNER" ]; then
      bad "no working Python or Node found, so no log sink."
      warn "Python here is the macOS stub that only opens the Xcode installer."
      warn "Fix either one:   xcode-select --install     (then Python works)"
      warn "             or:  brew install node          (then Node works)"
      warn "Until then the page keeps logs in the tab; styleMateSaveLogs() in the"
      warn "browser console writes the whole session out as one file."
    else
      ok "using $RUNNER_NAME"
      eval "PORT=\"$PORT\" nohup $RUNNER > \"$HERE/sink.log\" 2>&1 &"
      PIDS+=($!)
      for _ in $(seq 1 30); do
        curl -fsS --max-time 1 "http://127.0.0.1:${PORT}/ping" >/dev/null 2>&1 && break
        sleep 0.3
      done
    fi
  fi
  if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/ping" >/dev/null 2>&1; then
    ok "http://localhost:${PORT}  (serving this folder)"
    ok "audit logs -> $HERE/logs/   (written silently, nothing downloads)"
  else
    [ -n "${RUNNER:-}" ] && bad "sink did not come up — see sink.log"
  fi
fi

# ----------------------------------------------------------------- 4. page
say "5/${STEPS}  Page"
if [ -z "$PAGE" ]; then
  PAGE="$(ls -t ./*ollama_v*.html 2>/dev/null | head -1)"
  [ -z "$PAGE" ] && PAGE="$(ls -t ./*.html 2>/dev/null | head -1)"
fi
PAGE="$(basename "${PAGE:-}")"

if [ -z "$PAGE" ]; then
  bad "no .html file in $HERE"
fi

URL="http://localhost:${PORT}/${PAGE}"
if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/ping" >/dev/null 2>&1; then
  ok "$URL"
  [ "$OPEN" = "1" ] && { open "$URL" 2>/dev/null || xdg-open "$URL" 2>/dev/null || true; }
else
  warn "serving it over http failed, so open the file directly instead:"
  warn "file://$HERE/$PAGE"
  [ "$OPEN" = "1" ] && { open "$HERE/$PAGE" 2>/dev/null || xdg-open "$HERE/$PAGE" 2>/dev/null || true; }
fi

echo
say "Running. Ctrl-C to stop."
echo "  Ollama      http://localhost:${OLLAMA_PORT}   (log: ollama.log)"
echo "  Page/logs   http://localhost:${PORT}          (log: sink.log)"
echo "  Audit logs  $HERE/logs/"
echo
echo "A JSON file appears in logs/ for every call the page makes to Ollama."
echo "Watch them arrive with:   tail -f \"$HERE/sink.log\""
echo

# Idle until Ctrl-C. `wait` would return as soon as any one child exits.
while true; do sleep 3600; done
