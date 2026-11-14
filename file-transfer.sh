#!/usr/bin/env bash
# ─────────────────────────────────────────────
#  file-transfer.sh
#  Send or receive a file over TCP
#
#  USAGE
#    Receiver:  file-transfer.sh receive [-p PORT] [-o OUTDIR]
#    Sender:    file-transfer.sh send -f FILE -i IP [-p PORT]
#
#  OPTIONS
#    receive
#      -p, --port PORT       Port to listen on        (default: 9001)
#      -o, --outdir DIR      Directory to save files  (default: .)
#
#    send
#      -f, --file FILE       Path to the file to send (required)
#      -i, --ip   IP         Receiver IP address      (required)
#      -p, --port PORT       Port to connect to       (default: 9001)
#
#    -h, --help              Show this help and exit
# ─────────────────────────────────────────────

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
YELLOW='\033[1;33m'; BOLD='\033[1m'; RESET='\033[0m'

# ── helpers ───────────────────────────────────
die()  { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }
info() { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()   { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET}  $*"; }

banner_receiver() {
    echo -e "${CYAN}${BOLD}"
    echo "  ╔══════════════════════════════╗"
    echo "  ║   FILE TRANSFER — RECEIVER   ║"
    echo "  ╚══════════════════════════════╝"
    echo -e "${RESET}"
}

banner_sender() {
    echo -e "${CYAN}${BOLD}"
    echo "  ╔══════════════════════════════╗"
    echo "  ║    FILE TRANSFER — SENDER    ║"
    echo "  ╚══════════════════════════════╝"
    echo -e "${RESET}"
}

usage() {
    cat <<EOF
${BOLD}Usage:${RESET}
  $(basename "$0") receive [-p PORT] [-o OUTDIR]
  $(basename "$0") send -f FILE -i IP [-p PORT]
  $(basename "$0") -h | --help

${BOLD}Modes:${RESET}
  receive             Listen and save incoming files
  send                Send a file to a waiting receiver

${BOLD}Options (receive):${RESET}
  -p, --port PORT     Port to listen on        (default: 9001)
  -o, --outdir DIR    Directory to save files  (default: current dir)

${BOLD}Options (send):${RESET}
  -f, --file FILE     Path to the file to send (required)
  -i, --ip   IP       Receiver IP address      (required)
  -p, --port PORT     Port to connect to       (default: 9001)

${BOLD}Examples:${RESET}
  $(basename "$0") receive -p 9001 -o ~/downloads
  $(basename "$0") send -f report.pdf -i 192.168.1.42 -p 9001
EOF
}

# ── dependency check ──────────────────────────
check_deps() {
    for cmd in nc pv; do
        if ! command -v "$cmd" &>/dev/null; then
            case "$cmd" in
                nc)  die "'nc' (netcat) is required. Install: sudo apt install netcat-openbsd  OR  brew install netcat" ;;
                pv)  die "'pv' (pipe viewer) is required. Install: sudo apt install pv  OR  brew install pv" ;;
            esac
        fi
    done
}

# ── validate port ─────────────────────────────
validate_port() {
    local port="$1"
    [[ "$port" =~ ^[0-9]+$ ]] || die "Port must be a number."
    (( port >= 1 && port <= 65535 ))  || die "Port must be between 1 and 65535."
}

# ── mode: receive ─────────────────────────────
mode_receive() {
    local PORT=9001
    local OUTDIR="."

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -p|--port)   PORT="${2:?'--port requires a value'}";   shift 2 ;;
            -o|--outdir) OUTDIR="${2:?'--outdir requires a value'}"; shift 2 ;;
            *) die "Unknown receive option: $1. Run with --help for usage." ;;
        esac
    done

    validate_port "$PORT"
    mkdir -p "$OUTDIR" || die "Cannot create output directory: $OUTDIR"

    check_deps
    banner_receiver

    # Show local IPs so sender knows where to connect
    echo -e "${BOLD}  Your IP addresses (share one with the sender)${RESET}"
    echo    "  ─────────────────────────────────────────────"
    ip -4 addr show 2>/dev/null \
        | awk '/inet /{print "  " $2}' \
        | grep -v '127\.0\.0' \
        || hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^$' | awk '{print "  "$1}'
    echo    "  ─────────────────────────────────────────────"
    echo

    info "Listening on port ${PORT} … (Ctrl-C to stop)"
    echo

    while true; do
        TMPFILE=$(mktemp /tmp/ft-recv-XXXXXX)
        trap 'rm -f "$TMPFILE"' EXIT

        info "Waiting for connection on :${PORT} …"

        # Receive the full stream into a temp file first, then split
        nc -l -p "$PORT" > "$TMPFILE"

        if [[ ! -s "$TMPFILE" ]]; then
            warn "Received empty stream — skipping."
            rm -f "$TMPFILE"
            continue
        fi

        # First line = filename; rest = file content
        FILENAME=$(head -1 "$TMPFILE")

        if [[ -z "$FILENAME" ]]; then
            warn "Received empty filename — skipping."
            rm -f "$TMPFILE"
            continue
        fi

        # Sanitise: strip path components to prevent path traversal
        SAFE_NAME=$(basename "$FILENAME")
        OUTPATH="${OUTDIR}/${SAFE_NAME}"

        # Avoid overwriting existing files
        if [[ -e "$OUTPATH" ]]; then
            TIMESTAMP=$(date +%Y%m%d_%H%M%S)
            OUTPATH="${OUTDIR}/${TIMESTAMP}_${SAFE_NAME}"
            warn "File exists — saving as: $(basename "$OUTPATH")"
        fi

        info "Receiving '${SAFE_NAME}' → ${OUTPATH}"

        # Skip the first line (filename header) and pipe the rest through pv
        tail -c +$(( ${#FILENAME} + 2 )) "$TMPFILE" | pv > "$OUTPATH"

        rm -f "$TMPFILE"
        trap - EXIT

        ok "Saved: ${OUTPATH} ($(du -sh "$OUTPATH" | cut -f1))"
        echo

        read -rp "$(echo -e "${YELLOW}Wait for another file? [Y/n]:${RESET} ")" AGAIN
        [[ "${AGAIN,,}" == "n" ]] && { echo "Done."; break; }
        echo
    done
}

# ── mode: send ────────────────────────────────
mode_send() {
    local FILE=""
    local IP=""
    local PORT=9001

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -f|--file) FILE="${2:?'--file requires a value'}";  shift 2 ;;
            -i|--ip)   IP="${2:?'--ip requires a value'}";      shift 2 ;;
            -p|--port) PORT="${2:?'--port requires a value'}";  shift 2 ;;
            *) die "Unknown send option: $1. Run with --help for usage." ;;
        esac
    done

    [[ -z "$FILE" ]] && die "--file is required for send mode."
    [[ -z "$IP"   ]] && die "--ip is required for send mode."
    [[ ! -f "$FILE" ]] && die "File not found: $FILE"
    validate_port "$PORT"

    check_deps
    banner_sender

    FILENAME=$(basename "$FILE")
    FILESIZE=$(du -sh "$FILE" | cut -f1)

    echo -e "${BOLD}  Transfer summary${RESET}"
    echo    "  ─────────────────────────────"
    echo -e "  File     : ${GREEN}${FILENAME}${RESET} (${FILESIZE})"
    echo -e "  Target   : ${GREEN}${IP}:${PORT}${RESET}"
    echo    "  ─────────────────────────────"
    echo

    read -rp "$(echo -e "${YELLOW}Start transfer? [Y/n]:${RESET} ")" CONFIRM
    [[ "${CONFIRM,,}" == "n" ]] && { echo "Aborted."; exit 0; }

    info "Connecting to ${IP}:${PORT} …"

    # Protocol: first line = filename, then raw file bytes
    {
        printf '%s\n' "$FILENAME"
        pv "$FILE"
    } | nc -q 1 "$IP" "$PORT" \
        && ok "Transfer complete: ${FILENAME}" \
        || die "Transfer failed — is the receiver listening?"
}

# ── entry point ───────────────────────────────
[[ $# -eq 0 ]] && { usage; exit 0; }

case "$1" in
    receive) shift; mode_receive "$@" ;;
    send)    shift; mode_send    "$@" ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown mode: '$1'. Use 'send', 'receive', or --help." ;;
esac
