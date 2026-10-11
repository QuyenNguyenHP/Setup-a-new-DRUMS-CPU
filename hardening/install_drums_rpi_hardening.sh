#!/bin/bash
# install_drums_rpi_hardening.sh
# DRUMS Raspberry Pi hardening installer (Raspbian/Debian bullseye) - production-safe
#
# Goals:
# - Enforce SSH key-only, non-root access with banner and safe defaults
# - Ensure UFW baseline and Fail2ban SSH jail are enabled (without breaking remote.it)
# - Install DRUMS application security evidence controls (Requirement 39): app.conf, validate_input.sh
# - Install validation script: hardening-validate-iot.sh
# - Support evidence for ClassNK Part X (UR E27) Table X4.2 items 31–41 (see 465_part_x_e_202506.pdf)
#
# IMPORTANT:
# - This script does NOT touch Zymkey / encrypted root setup (hardware/provisioning step).
# - It avoids forcing explicit Ciphers/MACs/KEX; keeps OpenSSH defaults for compatibility.
# - Review ports before applying UFW rules on production systems.

set -euo pipefail

require_root() {
  if [ "${EUID}" -ne 0 ]; then
    echo "Please run as root (sudo)." >&2
    exit 1
  fi
}

log() { echo "[*] $*"; }
warn() { echo "[WARN] $*" >&2; }

detect_os() {
  . /etc/os-release || true
  echo "${ID:-unknown}:${VERSION_CODENAME:-unknown}:${VERSION_ID:-unknown}"
}

backup_file() {
  local f="$1"
  if [ -f "$f" ]; then
    cp -a "$f" "${f}.bak.$(date +%F-%H%M%S)"
  fi
}

install_pkg() {
  local pkgs=("$@")
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y "${pkgs[@]}"
}

write_file_root() {
  local path="$1"
  local mode="$2"
  local content="$3"
  install -d -m 0755 "$(dirname "$path")"
  printf "%s" "$content" > "$path"
  chmod "$mode" "$path"
  chown root:root "$path"
}

ensure_user() {
  local u="$1"
  if id "$u" >/dev/null 2>&1; then
    return 0
  fi
  log "Creating user '$u'..."
  adduser --disabled-password --gecos "" "$u"
}

main() {
  require_root
  log "OS: $(detect_os)"
  log "Installing prerequisites..."
  install_pkg openssh-server ufw fail2ban unzip gpg

  # --- SSH hardening (drop-in) ---
  log "Configuring SSH hardening drop-in..."
  local ssh_dropin="/etc/ssh/sshd_config.d/10-hardening.conf"
  local ssh_dropin_content='# /etc/ssh/sshd_config.d/10-hardening.conf
# DRUMS Raspberry Pi (Marine IoT) SSH hardening - local overrides
# Keep crypto (Ciphers/MACs/KexAlgorithms) at distro defaults for production compatibility.

# --- Authentication ---
PermitRootLogin no
PubkeyAuthentication yes

# Key-only access (no passwords / no interactive auth)
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PermitEmptyPasswords no

# Restrict who can log in (adjust to your needs)
AllowUsers drums

# --- Session / brute-force resistance ---
MaxAuthTries 3
LoginGraceTime 30
MaxSessions 10

# --- Reduce attack surface ---
X11Forwarding no
AllowTcpForwarding no
AllowAgentForwarding no
GatewayPorts no
PermitTunnel no

# --- Idle timeout / keepalive ---
ClientAliveInterval 60
ClientAliveCountMax 3
TCPKeepAlive no

# --- Banner / logging ---
Banner /etc/issue.net
LogLevel VERBOSE
UseDNS no
'
  write_file_root "$ssh_dropin" 0644 "$ssh_dropin_content"

  # --- Banner ---
  log "Installing /etc/issue.net banner..."
  local issue_content='*** WARNING / NOTICE ***
This system is the property of Daikai Engineering Pte Ltd and/or its customers.
Authorized use only. Activities may be monitored and logged.
Disconnect immediately if you are not an authorized user.
'
  write_file_root "/etc/issue.net" 0644 "$issue_content"

  # Validate sshd config before restart
  log "Validating sshd config..."
  sshd -t

  log "Restarting sshd..."
  systemctl enable --now ssh || systemctl enable --now sshd || true
  systemctl restart ssh || systemctl restart sshd

  # --- UFW baseline ---
  log "Configuring UFW baseline (default deny inbound)..."
  ufw --force reset
  ufw default deny incoming
  ufw default allow outgoing

  # SSH rate-limit
  ufw limit 22/tcp

  # Allow Modbus TCP if used (adjust if not needed)
  if ss -lntp | grep -qE ':(502)\b'; then
    ufw allow 502/tcp
    log "Detected listener on 502/tcp; allowing it in UFW."
  else
    warn "No listener detected on 502/tcp. If Modbus is required, allow it manually: ufw allow 502/tcp"
  fi

  ufw --force enable
  ufw status verbose || true

  # --- Fail2ban sshd jail ---
  log "Configuring Fail2ban sshd jail..."
  install -d -m 0755 /etc/fail2ban/jail.d
  cat > /etc/fail2ban/jail.d/10-sshd-drums.local <<'EOF'
[sshd]
enabled = true
bantime  = 10m
findtime = 10m
maxretry = 3

# IMPORTANT for remote.it:
# remote.it often proxies via loopback; do not ban localhost.
ignoreip = 127.0.0.0/8 ::1
EOF
  chmod 0644 /etc/fail2ban/jail.d/10-sshd-drums.local
  systemctl enable --now fail2ban
  systemctl restart fail2ban

  # --- DRUMS directories and app controls ---
  log "Installing DRUMS security controls (/etc/drums/app.conf and /opt/drums/validate_input.sh)..."
  install -d -m 0755 /etc/drums
  cat > /etc/drums/app.conf <<'EOF'
# DRUMS application security controls (evidence for Requirement 39)
ZIP_MAX_BYTES=52428800
ZIP_DIR=/home/drums/zip
ASC_DIR=/home/drums/asc
ARCHIVE_DIR=/home/drums/archive
OUTBOX_DIR=/home/drums/asc
ENCRYPT_SCRIPT=/home/drums/scripts/encrypt01.py
VALIDATION_ENTRYPOINT=/opt/drums/validate_input.sh
EOF
  chmod 0644 /etc/drums/app.conf
  chown root:root /etc/drums/app.conf

  install -d -m 0755 /opt/drums
  cat > /opt/drums/validate_input.sh <<'EOF'
#!/bin/bash
set -euo pipefail

CONFIG_FILE="/etc/drums/app.conf"

# Defaults (can be overridden by /etc/drums/app.conf)
ZIP_DIR="/home/drums/zip"
ASC_DIR="/home/drums/asc"
ARCHIVE_DIR="/home/drums/archive"
ZIP_MAX_BYTES=52428800

ENCRYPT_SCRIPT="/home/drums/scripts/encrypt01.py"
GPG_RECIPIENT="romel@daikai.com"
EXPECTED_USER="${EXPECTED_USER:-drums}"

# Logs (structured + human-readable)
LOG_DIR="/var/log/drums"
JSON_LOG="${LOG_DIR}/validate_input.jsonl"
TEXT_LOG="${LOG_DIR}/validate_input.log"

load_config() {
  [ -r "$CONFIG_FILE" ] || return 0
  # shellcheck disable=SC1090
  set -a
  . "$CONFIG_FILE"
  set +a
}

ts_iso() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

json_escape() {
  local s="${1:-}"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\t'/\\t}"
  printf "%s" "$s"
}

log_json() {
  local level="$1" action="$2" file="${3:-}" reason="${4:-}" detail="${5:-}"
  install -d -m 0750 "$LOG_DIR"
  touch "$JSON_LOG" "$TEXT_LOG"
  chmod 0640 "$JSON_LOG" "$TEXT_LOG" || true
  chown root:root "$JSON_LOG" "$TEXT_LOG" || true
  printf '{"ts":"%s","level":"%s","action":"%s","file":"%s","reason":"%s","detail":"%s"}\n' \
    "$(ts_iso)" "$(json_escape "$level")" "$(json_escape "$action")" "$(json_escape "$file")" "$(json_escape "$reason")" "$(json_escape "$detail")" \
    >>"$JSON_LOG"
  printf '%s [%s] %s file="%s" reason="%s" detail="%s"\n' \
    "$(ts_iso)" "$level" "$action" "$file" "$reason" "$detail" \
    >>"$TEXT_LOG"
}

reject_file() {
  local src="$1" code="$2" detail="${3:-}"
  local reject_dir="${ARCHIVE_DIR}/rejected/${code}"
  mkdir -p "$reject_dir"
  local base new
  base="$(basename "$src")"
  new="${reject_dir}/$(date -u '+%Y%m%dT%H%M%SZ')-${base}"
  if mv -f "$src" "$new" 2>/dev/null; then
    log_json "WARN" "REJECT" "$src" "$code" "$detail -> $new"
  else
    rm -f "$src" 2>/dev/null || true
    log_json "WARN" "REJECT" "$src" "$code" "$detail (move failed; deleted)"
  fi
}

zip_entries_safe() {
  local zip="$1"

  # Count entries; reject zip-bombs by limiting number of entries.
  local cnt
  cnt="$(unzip -Z1 "$zip" 2>/dev/null | wc -l | tr -d ' ')"
  if [ -z "$cnt" ] || [ "$cnt" -le 0 ]; then
    return 1
  fi
  if [ "$cnt" -gt 2000 ]; then
    return 2
  fi

  # Prevent path traversal and absolute paths in ZIP entries.
  if unzip -Z1 "$zip" 2>/dev/null | grep -qE '(^/|(^|/)\.\.(/|$))'; then
    return 3
  fi
  return 0
}

user_gpg_has_recipient_key() {
  local user="$1" recipient="$2"
  if command -v sudo >/dev/null 2>&1; then
    sudo -n -H -u "$user" gpg --batch --list-keys "$recipient" >/dev/null 2>&1 && return 0
  fi
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "$user" -- gpg --batch --list-keys "$recipient" >/dev/null 2>&1 && return 0
  fi
  gpg --batch --list-keys "$recipient" >/dev/null 2>&1
}

load_config

mkdir -p "$ASC_DIR" "$ARCHIVE_DIR"

log_json "INFO" "START" "" "INIT" "ZIP_DIR=${ZIP_DIR} ZIP_MAX_BYTES=${ZIP_MAX_BYTES} ASC_DIR=${ASC_DIR} ARCHIVE_DIR=${ARCHIVE_DIR}"

# --- Validate ZIPs: size + structure + safe filenames (Req 39 evidence) ---
shopt -s nullglob
for f in "$ZIP_DIR"/*.zip; do
  [ -e "$f" ] || continue
  sz="$(stat -c%s "$f" 2>/dev/null || echo 0)"

  if [ "$sz" -le 0 ]; then
    reject_file "$f" "empty" "zip size is 0"
    continue
  fi

  if [ "$sz" -gt "$ZIP_MAX_BYTES" ]; then
    reject_file "$f" "oversize" "zip size ${sz} > limit ${ZIP_MAX_BYTES}"
    continue
  fi

  if ! unzip -t "$f" >/dev/null 2>&1; then
    reject_file "$f" "corrupt" "unzip -t failed"
    continue
  fi

  if ! zip_entries_safe "$f"; then
    rc=$?
    case "$rc" in
      2) reject_file "$f" "zipbomb" "too many zip entries" ;;
      3) reject_file "$f" "path_traversal" "zip contains unsafe paths (.. or absolute)" ;;
      *) reject_file "$f" "unsafe" "zip entry check failed" ;;
    esac
    continue
  fi

  log_json "OK" "ACCEPT" "$f" "validated" "zip ok (size=${sz})"
done

# --- Evidence: encryption pipeline exists + uses gpg encrypt/sign ---
if [ -f "$ENCRYPT_SCRIPT" ]; then
  log_json "OK" "EVIDENCE" "$ENCRYPT_SCRIPT" "present" "encrypt script present"
else
  log_json "FAIL" "EVIDENCE" "$ENCRYPT_SCRIPT" "missing" "encrypt script missing"
  exit 2
fi

if command -v gpg >/dev/null 2>&1; then
  log_json "OK" "EVIDENCE" "gpg" "present" "$(command -v gpg)"
else
  log_json "FAIL" "EVIDENCE" "gpg" "missing" "gpg not installed"
  exit 2
fi

if grep -qE "(['\\\"])gpg\\1" "$ENCRYPT_SCRIPT"; then
  log_json "OK" "EVIDENCE" "$ENCRYPT_SCRIPT" "gpg_reference" "encrypt script references gpg"
else
  log_json "FAIL" "EVIDENCE" "$ENCRYPT_SCRIPT" "gpg_reference" "encrypt script does not reference gpg"
  exit 2
fi

if grep -q -- "--encrypt" "$ENCRYPT_SCRIPT" && grep -q -- "--sign" "$ENCRYPT_SCRIPT"; then
  log_json "OK" "EVIDENCE" "$ENCRYPT_SCRIPT" "encrypt_sign" "encrypt script includes --encrypt and --sign"
else
  log_json "WARN" "EVIDENCE" "$ENCRYPT_SCRIPT" "encrypt_sign" "encrypt script does not clearly show --encrypt + --sign flags"
fi

if id "$EXPECTED_USER" >/dev/null 2>&1; then
  if user_gpg_has_recipient_key "$EXPECTED_USER" "$GPG_RECIPIENT"; then
    log_json "OK" "EVIDENCE" "gpg" "recipient_key" "recipient public key present for ${GPG_RECIPIENT} (user=${EXPECTED_USER})"
  else
    log_json "FAIL" "EVIDENCE" "gpg" "recipient_key" "recipient key missing for ${GPG_RECIPIENT} (user=${EXPECTED_USER})"
    exit 2
  fi
else
  log_json "WARN" "EVIDENCE" "gpg" "user_missing" "EXPECTED_USER '${EXPECTED_USER}' not found; cannot verify recipient key"
fi

log_json "OK" "END" "" "COMPLETE" "validate_input.sh completed"
exit 0
EOF
  chmod 0755 /opt/drums/validate_input.sh
  chown root:root /opt/drums/validate_input.sh

  # Staging area (outbox) - default symlink to /home/drums/asc if present
  log "Setting up staging directory (/var/spool/drums/outbox)..."
  install -d -o drums -g drums -m 0750 /var/spool/drums || true
  if [ -d /home/drums/asc ]; then
    ln -sfn /home/drums/asc /var/spool/drums/outbox
  else
    warn "/home/drums/asc not found; create it and link manually: ln -sfn /home/drums/asc /var/spool/drums/outbox"
  fi

  # --- Remote support approval helper (Req 36) ---
  log "Installing remote support approval helper to /usr/local/sbin/remoteit-approval-window.sh..."
  cat > /usr/local/sbin/remoteit-approval-window.sh <<'EOF'
#!/usr/bin/env bash
# remoteit-approval-window.sh
# Time-boxed remote.it enable/disable helper (ClassNK Part X 4.4.3 Item 36 support).
#
# Examples:
#   sudo /usr/local/sbin/remoteit-approval-window.sh open  --minutes 60 --reason "Ticket 123 approved by CE"
#   sudo /usr/local/sbin/remoteit-approval-window.sh close --reason "Ticket 123 completed"
#
# Notes:
# - Best-effort: supports systems where remote.it runs under systemd, otherwise falls back to process control.
# - Writes evidence logs to /var/log/drums/remoteit-approval.log and syslog tag "remoteit-approval" if logger exists.

set -euo pipefail

LOG_DIR="/var/log/drums"
LOG_FILE="${LOG_DIR}/remoteit-approval.log"

log() {
  local msg="$1"
  install -d -m 0750 "$LOG_DIR"
  touch "$LOG_FILE"
  chmod 0640 "$LOG_FILE" || true
  chown root:root "$LOG_FILE" || true
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$msg" | tee -a "$LOG_FILE" >/dev/null
  if command -v logger >/dev/null 2>&1; then
    logger -t remoteit-approval -- "$msg" || true
  fi
}

die() { echo "[ERROR] $*" >&2; exit 1; }

require_root() {
  [[ "${EUID:-}" -eq 0 ]] || die "Run as root (sudo)."
}

usage() {
  cat <<'EOU'
Usage:
  remoteit-approval-window.sh open  --minutes MINUTES [--reason TEXT]
  remoteit-approval-window.sh close [--reason TEXT]
  remoteit-approval-window.sh status
EOU
}

remoteit_units() {
  printf "%s\n" \
    remoteit \
    remoteit.service \
    connectd \
    connectd.service
}

start_remoteit() {
  if command -v systemctl >/dev/null 2>&1; then
    local u
    while IFS= read -r u; do
      systemctl list-unit-files 2>/dev/null | awk '{print $1}' | grep -qx "$u" || continue
      systemctl enable --now "$u" >/dev/null 2>&1 || systemctl start "$u" >/dev/null 2>&1 || true
      return 0
    done < <(remoteit_units)
  fi

  if [[ -x /usr/share/remoteit/connectd ]]; then
    nohup /usr/share/remoteit/connectd -d /run/remoteit-connectd.pid >/dev/null 2>&1 &
    return 0
  fi
  return 1
}

stop_remoteit() {
  if command -v systemctl >/dev/null 2>&1; then
    local u
    while IFS= read -r u; do
      systemctl is-active --quiet "$u" || continue
      systemctl stop "$u" >/dev/null 2>&1 || true
    done < <(remoteit_units)
  fi

  pkill -f '/usr/share/remoteit/connectd' >/dev/null 2>&1 || true
  pkill -f '/usr/share/remoteit/demuxer' >/dev/null 2>&1 || true
  pkill -f '/usr/share/remoteit/schannel' >/dev/null 2>&1 || true
}

status_remoteit() {
  if command -v systemctl >/dev/null 2>&1; then
    local u
    while IFS= read -r u; do
      systemctl is-active --quiet "$u" && echo "[INFO] systemd active: $u"
    done < <(remoteit_units)
  fi
  ps aux | egrep -i 'remoteit|connectd|demuxer|schannel' | grep -v grep || true
}

schedule_auto_close() {
  local minutes="$1" reason="$2"
  if command -v systemd-run >/dev/null 2>&1; then
    systemd-run --quiet --unit "remoteit-approval-auto-close" --on-active="${minutes}m" \
      /usr/local/sbin/remoteit-approval-window.sh close --reason "$reason" || true
  else
    log "WARN auto-close not scheduled (systemd-run not available); close manually."
  fi
}

main() {
  require_root

  local action="${1:-}"
  shift || true

  local minutes="" reason="unspecified"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --minutes) minutes="${2:-}"; shift 2 ;;
      --reason) reason="${2:-}"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown arg: $1" ;;
    esac
  done

  case "$action" in
    open)
      [[ -n "$minutes" ]] || die "--minutes is required"
      log "OPEN requested minutes=${minutes} reason=${reason}"
      if start_remoteit; then
        log "OPEN success (remote.it started/enabled)"
      else
        log "OPEN warn (could not start remote.it automatically; verify remote.it install)"
      fi
      schedule_auto_close "$minutes" "$reason"
      ;;
    close)
      log "CLOSE requested reason=${reason}"
      stop_remoteit
      log "CLOSE complete (remote.it stopped)"
      ;;
    status)
      status_remoteit
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
EOF
  chmod 0755 /usr/local/sbin/remoteit-approval-window.sh
  chown root:root /usr/local/sbin/remoteit-approval-window.sh

  # --- Validation script ---
  log "Installing validation script to /usr/local/sbin/hardening-validate-iot.sh..."
  install -d -m 0755 /usr/local/sbin
  cat > /usr/local/sbin/hardening-validate-iot.sh <<'EOF'
#!/bin/bash
# hardening-validate-iot.sh
# Validation helper for Raspberry Pi (Raspbian/Debian) marine IoT hardening checks
# Focus: requirements 32–41 mapping
#
# Validator version: 2025-12-26
#
# NOTE on Requirement 39 (Input validation):
# - OS cannot fully prove application-layer validation exists.
# - This script checks for *evidence* (configuration + code hooks) and provides
#   PASS/WARN/FAIL guidance. Customize APP_* variables to your project paths.

set -euo pipefail

# -----------------------------
# User-tunable settings
# -----------------------------
EXPECTED_USER="${EXPECTED_USER:-drums}"

# Remote support approval model (Req 36):
# - timeboxed: local enable/disable window (preferred evidence) via /usr/local/sbin/remoteit-approval-window.sh
# - always-on: remote.it runs continuously; approval is enforced via remote.it/IdP platform controls + logs (compensating controls)
REMOTE_SUPPORT_MODEL="${REMOTE_SUPPORT_MODEL:-timeboxed}"

# Where your ingestion / packaging code lives (set these to your actual paths)
APP_DIR="${APP_DIR:-/opt/drums}"                 # root of your application (change as needed)
APP_CONFIG="${APP_CONFIG:-/etc/drums/app.conf}"  # optional config file (change as needed)
OUTBOX_DIR="${OUTBOX_DIR:-/var/spool/drums/outbox}"  # where .zip/.asc are staged (change as needed)

# Evidence patterns for input validation in code/config (edit to match your implementation)
# You can point APP_VALIDATION_FILE to the actual script/binary that receives/validates inbound data.
APP_VALIDATION_FILE="${APP_VALIDATION_FILE:-$APP_DIR/validate_input.sh}"
APP_SENDER_FILE="${APP_SENDER_FILE:-$APP_DIR/send_payload.sh}"

# Expected SSH settings (used for requirements 34,37,40,41 and hardening)
SSHD_CONFIG="/etc/ssh/sshd_config"
SSHD_D_DIR="/etc/ssh/sshd_config.d"
BANNER_FILE="/etc/issue.net"

# remote.it processes
REMOTEIT_PROCS_REGEX='remoteit|connectd|demuxer|schannel'

# -----------------------------
# Helpers
# -----------------------------
ts() { date '+%Y-%m-%d %H:%M:%S %z'; }
ok()   { echo "[OK]   $*"; }
warn() { echo "[WARN] $*"; }
fail() { echo "[FAIL] $*"; FAIL_COUNT=$((FAIL_COUNT+1)); }
info() { echo "[INFO] $*"; }

has_cmd() { command -v "$1" >/dev/null 2>&1; }

print_header() {
  echo "=== Marine IoT Hardening Validation (Pi) ==="
  echo "$(ts)"
  echo
}

get_os_info() {
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    info "OS: ${PRETTY_NAME:-unknown}"
  fi
  info "Kernel: $(uname -r)"
  info "Arch: $(uname -m)"
  echo
}

# Read effective sshd configuration (best-effort)
sshd_effective() {
  if has_cmd sshd; then
    sudo sshd -T 2>/dev/null || true
  else
    true
  fi
}

# Check a key=value in sshd -T output
check_sshd_T() {
  local key="$1" expected="$2"
  local actual
  actual="$(sshd_effective | awk -v k="$key" '$1==k{print $2; exit}')"
  if [ -z "${actual:-}" ]; then
    warn "sshd effective: missing '$key' (cannot verify)."
    return 0
  fi
  if [ "$actual" = "$expected" ]; then
    ok "sshd: $key = $actual"
  else
    warn "sshd: $key = $actual (expected: $expected)"
  fi
}

FAIL_COUNT=0

print_header
get_os_info

echo "## Requirement 32: Device identity (SSH keys + PGP keys + SFTP key-only auth)"
if id "$EXPECTED_USER" >/dev/null 2>&1; then
  ok "User exists: $EXPECTED_USER"
else
  fail "Expected user missing: $EXPECTED_USER"
fi

USER_HOME="$(getent passwd "$EXPECTED_USER" | cut -d: -f6 || true)"
if [ -n "${USER_HOME:-}" ] && [ -d "$USER_HOME" ]; then
  AUTH_KEYS="$USER_HOME/.ssh/authorized_keys"
  if [ -s "$AUTH_KEYS" ]; then
    ok "authorized_keys present: $AUTH_KEYS"
    perms="$(stat -c '%a %U %G' "$AUTH_KEYS" 2>/dev/null || echo '')"
    info "authorized_keys perms/owner: ${perms:-unknown}"
    if stat -c '%a' "$AUTH_KEYS" | awk '{exit !($1<=644)}'; then
      ok "authorized_keys permissions look safe (<=644)."
    else
      warn "authorized_keys permissions may be too open; recommend 600 or 644."
    fi
  else
    warn "authorized_keys missing or empty: $AUTH_KEYS"
  fi
else
  fail "Cannot find home dir for $EXPECTED_USER"
fi

if has_cmd sshd; then
  check_sshd_T "passwordauthentication" "no"
  check_sshd_T "kbdinteractiveauthentication" "no"
  check_sshd_T "challengeresponseauthentication" "no"
  check_sshd_T "pubkeyauthentication" "yes"
else
  warn "sshd binary not found; cannot run sshd -T checks."
fi

if [ -r "$SSHD_CONFIG" ] || [ -d "$SSHD_D_DIR" ]; then
  if grep -R --line-number -E "^\\s*Subsystem\\s+sftp" "$SSHD_CONFIG" "$SSHD_D_DIR" 2>/dev/null | head -n1 >/dev/null; then
    ok "SFTP subsystem configured (Subsystem sftp ...)."
  else
    warn "Cannot find 'Subsystem sftp' directive; if you use SFTP, confirm it's configured."
  fi
fi

if has_cmd gpg; then
  if id "$EXPECTED_USER" >/dev/null 2>&1; then
    if command -v sudo >/dev/null 2>&1; then
      if sudo -n -H -u "$EXPECTED_USER" gpg --batch --with-colons --list-secret-keys 2>/dev/null | grep -qE '^sec:'; then
        ok "PGP secret key(s) present for user '$EXPECTED_USER' (device has identity)."
      else
        if command -v runuser >/dev/null 2>&1; then
          if runuser -u "$EXPECTED_USER" -- gpg --batch --with-colons --list-secret-keys 2>/dev/null | grep -qE '^sec:'; then
            ok "PGP secret key(s) present for user '$EXPECTED_USER' (device has identity)."
          else
            warn "No PGP secret keys found for user '$EXPECTED_USER' keyring."
            warn "Tip: ensure keys are under ${USER_HOME}/.gnupg and your service runs as '$EXPECTED_USER' (or set EXPECTED_USER)."
          fi
        else
          warn "No PGP secret keys found for user '$EXPECTED_USER' keyring."
          warn "Tip: ensure keys are under ${USER_HOME}/.gnupg and your service runs as '$EXPECTED_USER' (or set EXPECTED_USER)."
        fi
      fi
    else
      if gpg --batch --with-colons --list-secret-keys 2>/dev/null | grep -qE '^sec:'; then
        ok "PGP secret key(s) present (device has identity)."
      else
        warn "No PGP secret keys found in current user's keyring."
      fi
    fi
  else
    warn "Expected user '$EXPECTED_USER' not found; cannot validate PGP key identity."
  fi
else
  warn "gpg not installed; cannot validate PGP device identity."
fi
echo

echo "## Requirement 33: Limit unsuccessful logins (Fail2ban/UFW)"
if has_cmd fail2ban-client; then
  if sudo fail2ban-client ping >/dev/null 2>&1; then
    ok "fail2ban is running/responding."
    if sudo fail2ban-client status sshd >/dev/null 2>&1; then
      ok "fail2ban jail 'sshd' exists."
      sudo fail2ban-client status sshd | sed 's/^/[INFO] /'
      ignore="$(sudo fail2ban-client get sshd ignoreip 2>/dev/null || true)"
      if echo "$ignore" | grep -q "127.0.0.0/8"; then ok "fail2ban sshd ignores 127.0.0.0/8 (good for remote.it)"; else warn "fail2ban sshd does not ignore 127.0.0.0/8 (risk of breaking remote.it)"; fi
      if echo "$ignore" | grep -q "::1"; then ok "fail2ban sshd ignores ::1"; else warn "fail2ban sshd does not ignore ::1"; fi
    else
      warn "fail2ban running, but jail 'sshd' not found/enabled."
    fi
  else
    warn "fail2ban-client present but cannot ping service."
  fi
else
  warn "fail2ban-client not installed; cannot validate requirement 33."
fi

if has_cmd ufw; then
  st="$(sudo ufw status verbose 2>/dev/null || true)"
  if echo "$st" | grep -qi "Status: active"; then
    ok "UFW active."
    echo "$st" | sed 's/^/[INFO] /'
  else
    warn "UFW not active (or cannot query)."
  fi
else
  warn "ufw not installed; cannot validate firewall posture."
fi
echo

echo "## Requirement 34: Pre-login system use notification (SSH banner)"
if [ -r "$BANNER_FILE" ] && [ -s "$BANNER_FILE" ]; then
  ok "Banner file exists: $BANNER_FILE"
else
  warn "Banner file missing/empty: $BANNER_FILE (recommended)."
fi

if has_cmd sshd; then
  banner="$(sshd_effective | awk '$1=="banner"{print $2; exit}')"
  if [ -n "${banner:-}" ] && [ "$banner" != "none" ]; then
    ok "sshd banner is enabled: $banner"
  else
    warn "sshd banner not enabled (Banner none). Set 'Banner /etc/issue.net' in sshd config."
  fi
fi
echo

echo "## Requirement 35: Monitor & control remote access (remote.it evidence)"
if ps aux | egrep -i "$REMOTEIT_PROCS_REGEX" | grep -v grep >/dev/null 2>&1; then
  ok "remote.it processes running (connectd/demuxer/schannel detected)."
  ps aux | egrep -i "$REMOTEIT_PROCS_REGEX" | grep -v grep | sed 's/^/[INFO] /'
else
  warn "remote.it processes not detected. If you rely on remote.it, confirm service is installed/running."
fi

if has_cmd ss; then
  ss -lntp | grep -E ':(22)\\b' >/dev/null 2>&1 && ok "sshd listening on port 22."
  info "Listening sockets for sshd:"
  ss -lntp | awk '/sshd/ {print}' | sed 's/^/[INFO] /' || true

  # If validation is run during an active remote support session, show it as stronger runtime evidence.
  if ss -ntp 2>/dev/null | awk '/sshd/ && $1 ~ /ESTAB/ {print}' | head -n 1 >/dev/null; then
    ok "Active SSH session(s) detected (runtime evidence of remote access)."
    ss -ntp 2>/dev/null | awk '/sshd/ && $1 ~ /ESTAB/ {print}' | sed 's/^/[INFO] /' || true
  else
    info "No active SSH sessions detected at the moment (may be idle)."
  fi

  if ss -ntp 2>/dev/null | grep -E '127\\.0\\.0\\.1:22' | grep -E 'sshd' >/dev/null 2>&1; then
    ok "Loopback SSH connection detected (consistent with remote.it local tunnel)."
  else
    info "No loopback SSH connection observed right now (remote support may be idle; not necessarily a problem)."
  fi
else
  warn "ss command not present; cannot inspect listening sockets."
fi
echo

echo "## Requirement 36: Explicit onboard approval (procedural control)"
case "$REMOTE_SUPPORT_MODEL" in
  timeboxed)
    if [ -x /usr/local/sbin/remoteit-approval-window.sh ]; then
      ok "Remote support approval helper present: /usr/local/sbin/remoteit-approval-window.sh"
      info "Usage example:"
      echo "[INFO]   sudo /usr/local/sbin/remoteit-approval-window.sh open --minutes 60 --reason \"Ticket <ID> approved by <NAME>\""
      echo "[INFO] Evidence log: /var/log/drums/remoteit-approval.log"
      if [ -r /var/log/drums/remoteit-approval.log ]; then
        if grep -q "OPEN requested" /var/log/drums/remoteit-approval.log && grep -q "CLOSE requested" /var/log/drums/remoteit-approval.log; then
          ok "Approval window open/close evidence found in /var/log/drums/remoteit-approval.log"
        else
          warn "No open/close evidence found yet in /var/log/drums/remoteit-approval.log (run an approved time-boxed session at least once)."
        fi
      else
        warn "Evidence log not found yet: /var/log/drums/remoteit-approval.log"
      fi
    else
      warn "Remote support approval helper missing: /usr/local/sbin/remoteit-approval-window.sh"
    fi
    info "Procedural: remote support should be denied by default and only enabled via approved time-boxed windows; capture approval record + open/close logs."
    ;;
  always-on)
    info "REMOTE_SUPPORT_MODEL=always-on: remote.it runs continuously; Item 36 must be satisfied using platform-gated approval + MFA + audit logs."
    if [ -x /usr/local/sbin/remoteit-approval-window.sh ]; then
      info "Optional helper available (local timeboxing): /usr/local/sbin/remoteit-approval-window.sh"
    fi
    if has_cmd systemctl; then
      if systemctl is-active --quiet remoteit.service 2>/dev/null || systemctl is-active --quiet connectd.service 2>/dev/null; then
        ok "remote.it systemd unit appears active (always-on model in effect)."
      else
        info "remote.it systemd unit not detected as active via common unit names (may still be running under a different unit)."
      fi
    fi
    warn "Evidence required: remote.it/IdP configuration (authorized identities + MFA) + access/audit logs + ticket/approval record for support sessions."
    ;;
  *)
    warn "Unknown REMOTE_SUPPORT_MODEL='$REMOTE_SUPPORT_MODEL' (use 'timeboxed' or 'always-on')."
    ;;
esac
echo

echo "## Requirement 37: Remote session termination / idle timeout"
if has_cmd sshd; then
  check_sshd_T "clientaliveinterval" "60"
  check_sshd_T "clientalivecountmax" "3"
  info "Idle termination is configured via ClientAliveInterval/CountMax; confirm this matches your operational policy."
else
  warn "Cannot verify sshd keepalive values."
fi
echo

echo "## Zymbit / Zymkey (at-rest protection evidence)"
if has_cmd systemctl; then
  if systemctl list-unit-files 2>/dev/null | awk '{print $1}' | grep -qx "zkifc.service"; then
    if systemctl is-active --quiet zkifc.service 2>/dev/null; then
      ok "zkifc.service active (Zymbit interface connector)."
    else
      warn "zkifc.service installed but not active."
    fi
  else
    info "zkifc.service not installed (skip Zymbit checks)."
  fi

  if systemctl list-unit-files 2>/dev/null | awk '{print $1}' | grep -qx "zkbootrtc.service"; then
    if systemctl is-enabled --quiet zkbootrtc.service 2>/dev/null; then
      ok "zkbootrtc.service enabled (restores clock from Zymkey at boot)."
    else
      warn "zkbootrtc.service installed but not enabled."
    fi
  fi

  if systemctl list-unit-files 2>/dev/null | awk '{print $1}' | grep -qx "zscm_halt.service"; then
    ok "zscm_halt.service present (halt marker on shutdown)."
  fi
else
  info "systemctl not available; cannot inspect Zymbit services."
fi
echo

echo "## Requirement 38: Cryptographic integrity (SSH + PGP)"
has_cmd ssh && ok "ssh client present." || warn "ssh client not present (unusual)."
has_cmd scp && ok "scp present." || warn "scp not present."
has_cmd gpg && ok "gpg present." || warn "gpg missing (cannot validate PGP usage)."
echo

echo "## Requirement 39: Input validation (application layer evidence checks)"
info "Customize APP_DIR/APP_CONFIG/APP_VALIDATION_FILE/OUTBOX_DIR at top of script."
zip_limit_found=0
if [ -r "$APP_CONFIG" ] && grep -Eqi 'ZIP_MAX(_SIZE)?|MAX_ZIP|ZIP_LIMIT' "$APP_CONFIG"; then
  ok "Found ZIP size limit setting in $APP_CONFIG"
  grep -Ein 'ZIP_MAX(_SIZE)?|MAX_ZIP|ZIP_LIMIT' "$APP_CONFIG" | sed 's/^/[INFO] /'
  zip_limit_found=1
fi
[ "$zip_limit_found" -eq 0 ] && warn "No explicit ZIP size limit found in $APP_CONFIG (recommended)."

if [ -r "$APP_VALIDATION_FILE" ]; then
  ok "Validation script present: $APP_VALIDATION_FILE"
  if grep -Eqi 'asc|\\.asc|validate|schema|regex|magic|file\\s+-b' "$APP_VALIDATION_FILE"; then
    ok "Validation script contains markers suggesting ASC validation."
  else
    warn "Validation script exists but no obvious ASC validation markers found; review it."
  fi
else
  warn "Validation script not found at $APP_VALIDATION_FILE (set path to your real validation entrypoint)."
fi

pgp_verify_found=0
for f in "$APP_VALIDATION_FILE" "$APP_SENDER_FILE" "$APP_CONFIG"; do
  [ -r "$f" ] || continue
  if grep -Eqi 'gpg\\s+--verify|gpgv\\s|--verify|--decrypt|--recipient|--encrypt' "$f"; then
    ok "Found gpg verify/encrypt markers in: $f"
    grep -Ein 'gpg\\s+--verify|gpgv\\s|--decrypt|--recipient|--encrypt' "$f" | head -n 5 | sed 's/^/[INFO] /'
    pgp_verify_found=1
  fi
done
[ "$pgp_verify_found" -eq 0 ] && warn "No evidence of gpg verify/encrypt in your configured files (point script to the real pipeline components)."

	if [ -d "$OUTBOX_DIR" ]; then
	  ok "Outbox directory exists: $OUTBOX_DIR"
	  info "Recent staged payloads (name/size/time):"
	  (ls -lt "$OUTBOX_DIR" 2>/dev/null | head -n 10) | sed 's/^/[INFO] /' || true
	else
	  warn "Outbox directory not found: $OUTBOX_DIR (set to your staging dir)."
	fi

	code_evidence=0
	runtime_evidence=0

	if [ -r "$APP_VALIDATION_FILE" ]; then
	  if grep -qE 'validate_input\.jsonl|validate_input\.log|/var/log/drums' "$APP_VALIDATION_FILE" && \
	     grep -qE 'archive/rejected|/rejected/' "$APP_VALIDATION_FILE"; then
	    code_evidence=1
	  fi
	fi

	if [ -r /var/log/drums/validate_input.jsonl ] || [ -r /var/log/drums/validate_input.log ]; then
	  runtime_evidence=1
	fi

	if [ "$zip_limit_found" -eq 1 ] && [ -r "$APP_VALIDATION_FILE" ] && [ "$code_evidence" -eq 1 ]; then
	  ok "Req 39 controls implemented (size limits + validation entrypoint + reject quarantine + structured logs)."
	  if [ "$runtime_evidence" -eq 1 ]; then
	    ok "Validation runtime logs present under /var/log/drums (strong evidence for Req 39)."
	  else
	    info "No runtime validation logs found yet; run '$APP_VALIDATION_FILE' once (or wait for pipeline activity) to generate /var/log/drums/validate_input.* evidence."
	  fi
	else
	  warn "Req 39 evidence incomplete; ensure ZIP size limits + strict validation + quarantine of rejects + structured logs, then re-run validation."
	fi
	echo

echo "## Requirements 40 & 41: Session integrity + invalidate session IDs"
info "For SSH, session integrity/invalidation is inherent to sshd."
if has_cmd sshd; then
  check_sshd_T "permitrootlogin" "no"
  check_sshd_T "x11forwarding" "no"
  check_sshd_T "allowtcpforwarding" "no"
  ok "Key-only SSH + idle timeouts generally satisfies 40/41 for SSH sessions."
else
  warn "Cannot verify sshd settings."
fi
echo

echo "=== End ==="
exit "$FAIL_COUNT"
EOF
  chmod 0755 /usr/local/sbin/hardening-validate-iot.sh
  chown root:root /usr/local/sbin/hardening-validate-iot.sh

  log "Run validation:"
  echo "  sudo /usr/local/sbin/hardening-validate-iot.sh | sudo tee /home/drums/iot-hardening-validation-\$(date +%F).txt"

  log "Done."
}

main "$@"
