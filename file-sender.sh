#!/usr/bin/env bash
# ─────────────────────────────────────────────
#  file-transfer / sender.sh
#  Send a file to a waiting receiver over TCP
# ─────────────────────────────────────────────

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
YELLOW='\033[1;33m'; BOLD='\033[1m'; RESET='\033[0m'

banner() {
    echo -e "${CYAN}${BOLD}"
    echo "  ╔══════════════════════════════╗"
    echo "  ║    FILE TRANSFER — SENDER    ║"
    echo "  ╚══════════════════════════════╝"
    echo -e "${RESET}"
}

die() { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }
info() { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()   { echo -e "${GREEN}[OK]${RESET}    $*"; }

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
read -rp "$(echo -e "${YELLOW}File path to send:${RESET} ")" FILE
[[ -z "$FILE" ]]      && die "No file specified."
[[ ! -f "$FILE" ]]    && die "File not found: $FILE"

read -rp "$(echo -e "${YELLOW}Receiver IP address:${RESET} ")" IP
[[ -z "$IP" ]]        && die "No IP address specified."

read -rp "$(echo -e "${YELLOW}Port [default 9001]:${RESET} ")" PORT
PORT="${PORT:-9001}"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "Port must be a number."
(( PORT >= 1 && PORT <= 65535 ))  || die "Port must be between 1 and 65535."

# ── summary ───────────────────────────────────
FILENAME=$(basename "$FILE")
FILESIZE=$(du -sh "$FILE" | cut -f1)

echo
echo -e "${BOLD}  Transfer summary${RESET}"
echo    "  ─────────────────────────────"
echo -e "  File     : ${GREEN}${FILENAME}${RESET} (${FILESIZE})"
echo -e "  Target   : ${GREEN}${IP}:${PORT}${RESET}"
echo    "  ─────────────────────────────"
echo

read -rp "$(echo -e "${YELLOW}Start transfer? [Y/n]:${RESET} ")" CONFIRM
[[ "${CONFIRM,,}" == "n" ]] && { echo "Aborted."; exit 0; }

# ── send: filename first, then data ──────────
info "Connecting to ${IP}:${PORT} …"

# Protocol: first line = filename, then raw file bytes
{
    printf '%s\n' "$FILENAME"
    pv "$FILE"
} | nc -q 1 "$IP" "$PORT" && ok "Transfer complete: ${FILENAME}" \
                           || die "Transfer failed — is the receiver listening?"
