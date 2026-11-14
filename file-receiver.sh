#!/usr/bin/env bash
# ─────────────────────────────────────────────
#  file-transfer / receiver.sh
#  Wait for a sender and receive a file over TCP
# ─────────────────────────────────────────────

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
YELLOW='\033[1;33m'; BOLD='\033[1m'; RESET='\033[0m'

banner() {
    echo -e "${CYAN}${BOLD}"
    echo "  ╔══════════════════════════════╗"
    echo "  ║   FILE TRANSFER — RECEIVER   ║"
    echo "  ╚══════════════════════════════╝"
    echo -e "${RESET}"
}

die()  { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }
info() { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()   { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET}  $*"; }

# ── check dependencies ────────────────────────
for cmd in nc pv; do
    if ! command -v "$cmd" &>/dev/null; then
        case "$cmd" in
            nc)  die "'nc' (netcat) is required. Install: sudo apt install netcat-openbsd  OR  brew install netcat" ;;
            pv)  die "'pv' (pipe viewer) is required. Install: sudo apt install pv  OR  brew install pv" ;;
        esac
    fi
done

banner

# ── prompts ───────────────────────────────────
read -rp "$(echo -e "${YELLOW}Port to listen on [default 9001]:${RESET} ")" PORT
PORT="${PORT:-9001}"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "Port must be a number."
(( PORT >= 1 && PORT <= 65535 ))  || die "Port must be between 1 and 65535."

read -rp "$(echo -e "${YELLOW}Save files to directory [default: current dir]:${RESET} ")" OUTDIR
OUTDIR="${OUTDIR:-.}"
mkdir -p "$OUTDIR" || die "Cannot create output directory: $OUTDIR"

# ── show local IPs so sender knows where to connect ──
echo
echo -e "${BOLD}  Your IP addresses (share one with the sender)${RESET}"
echo    "  ─────────────────────────────────────────────"
ip -4 addr show 2>/dev/null \
    | awk '/inet /{print "  " $2}' \
    | grep -v '127\.0\.0' \
    || hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^$' | awk '{print "  "$1}'
echo    "  ─────────────────────────────────────────────"
echo

# ── listen loop ───────────────────────────────
info "Listening on port ${PORT} … (Ctrl-C to stop)"
echo

while true; do

    # netcat receives the stream; head -1 pulls the filename line;
    # the rest of the bytes are the file content piped into pv → file.
    TMPFIFO=$(mktemp -u /tmp/ft-fifo-XXXXXX)
    mkfifo "$TMPFIFO"
    trap 'rm -f "$TMPFIFO"' EXIT

    nc -l -p "$PORT" > "$TMPFIFO" &
    NC_PID=$!

    info "Waiting for connection on :${PORT} …"

    # Read filename from first line
    FILENAME=""
    while IFS= read -r line; do
        FILENAME="$line"
        break
    done < "$TMPFIFO"

    if [[ -z "$FILENAME" ]]; then
        warn "Received empty filename — skipping."
        kill "$NC_PID" 2>/dev/null || true
        rm -f "$TMPFIFO"
        continue
    fi

    # Sanitise: strip any path components to prevent path traversal
    SAFE_NAME=$(basename "$FILENAME")
    OUTPATH="${OUTDIR}/${SAFE_NAME}"

    # Avoid overwriting existing files
    if [[ -e "$OUTPATH" ]]; then
        TIMESTAMP=$(date +%Y%m%d_%H%M%S)
        OUTPATH="${OUTDIR}/${TIMESTAMP}_${SAFE_NAME}"
        warn "File exists — saving as: $(basename "$OUTPATH")"
    fi

    info "Receiving '${SAFE_NAME}' → ${OUTPATH}"

    # Pipe remaining bytes through pv for progress, into output file
    pv < "$TMPFIFO" > "$OUTPATH"

    wait "$NC_PID" 2>/dev/null || true
    rm -f "$TMPFIFO"
    trap - EXIT

    ok "Saved: ${OUTPATH} ($(du -sh "$OUTPATH" | cut -f1))"
    echo

    read -rp "$(echo -e "${YELLOW}Wait for another file? [Y/n]:${RESET} ")" AGAIN
    [[ "${AGAIN,,}" == "n" ]] && { echo "Done."; break; }
    echo
done
