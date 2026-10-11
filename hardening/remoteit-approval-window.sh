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
  cat <<'EOF'
Usage:
  remoteit-approval-window.sh open  --minutes MINUTES [--reason TEXT]
  remoteit-approval-window.sh close [--reason TEXT]
  remoteit-approval-window.sh status
EOF
}

remoteit_units() {
  # Candidate unit names seen in remote.it installations.
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

  # Fallback: start known remote.it binaries if installed.
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

