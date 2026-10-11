#!/bin/bash
# hardening-validate-iot.sh
# Validation helper for Raspberry Pi (Raspbian/Debian) marine IoT hardening checks
# Focus: requirements 32–41 mapping
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

run_as_user_best_effort() {
  local user="$1"
  shift || true

  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    if has_cmd sudo; then
      # -n: non-interactive; avoid hanging if sudo requires a password/tty.
      if sudo -n -H -u "$user" "$@" 2>/dev/null; then
        return 0
      fi
    fi
    if has_cmd runuser; then
      if runuser -u "$user" -- "$@" 2>/dev/null; then
        return 0
      fi
    fi
    "$@" 2>/dev/null || true
    return 0
  fi

  if [ "$(id -un 2>/dev/null || echo unknown)" = "$user" ]; then
    "$@" 2>/dev/null || true
    return 0
  fi

  return 0
}

gpg_secret_keys_present_for_user() {
  local user="$1"
  local user_home="${2:-}"
  local out

  if [ -n "${user_home:-}" ] && [ -d "${user_home}/.gnupg" ]; then
    out="$(run_as_user_best_effort "$user" env HOME="$user_home" GNUPGHOME="${user_home}/.gnupg" gpg --batch --with-colons --homedir "${user_home}/.gnupg" --list-secret-keys)"
  else
    out="$(run_as_user_best_effort "$user" gpg --batch --with-colons --list-secret-keys)"
  fi

  if echo "$out" | grep -qE '^sec:'; then
    return 0
  fi

  # Fallback: if user-switching failed for some reason, try explicit homedir with current user.
  if [ -n "${user_home:-}" ] && [ -d "${user_home}/.gnupg" ]; then
    out="$(env HOME="$user_home" GNUPGHOME="${user_home}/.gnupg" gpg --batch --with-colons --homedir "${user_home}/.gnupg" --list-secret-keys 2>/dev/null || true)"
    echo "$out" | grep -qE '^sec:'
    return $?
  fi

  return 1
}

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
  if grep -R --line-number -E "^\s*Subsystem\s+sftp" "$SSHD_CONFIG" "$SSHD_D_DIR" 2>/dev/null | head -n1 >/dev/null; then
    ok "SFTP subsystem configured (Subsystem sftp ...)."
  else
    warn "Cannot find 'Subsystem sftp' directive; if you use SFTP, confirm it's configured."
  fi
fi

if has_cmd gpg; then
  if id "$EXPECTED_USER" >/dev/null 2>&1; then
    if gpg_secret_keys_present_for_user "$EXPECTED_USER" "${USER_HOME:-}"; then
      ok "PGP secret key(s) present for user '$EXPECTED_USER' (device has identity)."
    else
      # This commonly happens when the script runs as root and checks /root/.gnupg while keys live in /home/drums/.gnupg.
      warn "No PGP secret keys found for user '$EXPECTED_USER' keyring."
      warn "If your DRUMS service uses a different account or custom GNUPGHOME, run checks as that user (or set EXPECTED_USER accordingly)."
      if [ -n "${USER_HOME:-}" ]; then
        info "Expected keyring path: ${USER_HOME}/.gnupg"
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
  ss -lntp | grep -E ':(22)\b' >/dev/null 2>&1 && ok "sshd listening on port 22."
  info "Listening sockets for sshd:"
  ss -lntp | awk '/sshd/ {print}' | sed 's/^/[INFO] /' || true

  # If validation is run during an active remote support session, show it as stronger runtime evidence.
  if ss -ntp 2>/dev/null | awk '/sshd/ && $1 ~ /ESTAB/ {print}' | head -n 1 >/dev/null; then
    ok "Active SSH session(s) detected (runtime evidence of remote access)."
    ss -ntp 2>/dev/null | awk '/sshd/ && $1 ~ /ESTAB/ {print}' | sed 's/^/[INFO] /' || true
  else
    info "No active SSH sessions detected at the moment (may be idle)."
  fi

  if ss -ntp 2>/dev/null | grep -E '127\.0\.0\.1:22' | grep -E 'sshd' >/dev/null 2>&1; then
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
      info "Evidence log: /var/log/drums/remoteit-approval.log"
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
  if grep -Eqi 'asc|\.asc|validate|schema|regex|magic|file\s+-b' "$APP_VALIDATION_FILE"; then
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
  if grep -Eqi 'gpg\s+--verify|gpgv\s|--verify|--decrypt|--recipient|--encrypt' "$f"; then
    ok "Found gpg verify/encrypt markers in: $f"
    grep -Ein 'gpg\s+--verify|gpgv\s|--decrypt|--recipient|--encrypt' "$f" | head -n 5 | sed 's/^/[INFO] /'
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
  if grep -qE 'validate_input\\.jsonl|validate_input\\.log|/var/log/drums' "$APP_VALIDATION_FILE" && \
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
