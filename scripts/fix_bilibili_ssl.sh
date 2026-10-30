#!/system/bin/sh
# fix_bilibili_ssl.sh
# Fixes Bilibili (tv.danmaku.bili) crash on Android 9 (32-bit armeabi-v7a):
#   dlopen failed: cannot locate symbol "EVP_hpke_aes_128_gcm" referenced by "libssl.so"
#
# Provides transactional patch application and restoration using:
#   1. sh fix_bilibili_ssl.sh apply PREPARED_DIR   (Apply host-checked ELF patch with atomic rollback)
#   2. sh fix_bilibili_ssl.sh restore [BACKUP_DIR] (Restore original unpatched libraries)
#   3. sh fix_bilibili_ssl.sh status               (Display current patch and transaction status)

set -eu

PACKAGE="tv.danmaku.bili"
STATE_DIR="${STATE_DIR:-/data/local/c10h-bili-state}"
ROOT="$STATE_DIR"
TX_FILE="$STATE_DIR/tx_state.txt"
LOCK_DIR="$STATE_DIR/lock"

MODE="${1:-}"

# Locate library directory
if [ -n "${MOCK_LIB_DIR:-}" ]; then
  LIB="$MOCK_LIB_DIR"
  APK=""
else
  APK=$(pm path "$PACKAGE" 2>/dev/null | sed -n 's/^package://p' | head -n 1)
  if [ -z "$APK" ] && [ "$MODE" != "status" ]; then
    echo "ERROR: Package $PACKAGE is not installed." >&2
    exit 1
  fi
  LIB="${APK%/*}/lib/arm"
fi

# 1. Read-only status command (does NOT acquire exclusive lock)
if [ "$MODE" = "status" ]; then
  echo "=== Bilibili BoringSSL Patch Status ==="
  echo "Target Package : $PACKAGE"
  echo "Library Dir    : ${LIB:-Not found}"
  echo "State Dir      : $STATE_DIR"
  if [ -d "$LIB" ] && { [ -f "$LIB/libbili_o.so" ] || [ -f "$LIB/libbsl.so" ]; }; then
    echo "Device Status  : Patched (libbili_o.so / libbsl.so present)"
  elif [ -d "$LIB" ]; then
    echo "Device Status  : Unpatched (original state)"
  else
    echo "Device Status  : Library directory not accessible"
  fi

  if [ -f "$TX_FILE" ]; then
    LAST_STATUS=$(grep '^STATUS:' "$TX_FILE" 2>/dev/null | tail -n 1 | cut -d: -f2- || true)
    LAST_BACKUP=$(grep '^BACKUP_DIR:' "$TX_FILE" 2>/dev/null | tail -n 1 | cut -d: -f2- || true)
    echo "Last Tx Status : ${LAST_STATUS:-None}"
    echo "Last Backup    : ${LAST_BACKUP:-None}"
  else
    echo "Last Tx Status : No transaction history"
  fi

  if [ -d "$LOCK_DIR" ]; then
    LPID=$(cat "$LOCK_DIR/pid" 2>/dev/null || true)
    if [ -n "$LPID" ] && kill -0 "$LPID" 2>/dev/null; then
      echo "Lock Status    : Held by active process (PID: $LPID)"
    else
      echo "Lock Status    : Stale lock present (PID: ${LPID:-unknown})"
    fi
  else
    echo "Lock Status    : Unlocked"
  fi
  exit 0
fi

# Root check (can be bypassed in mock tests via SKIP_ROOT_CHECK=1)
if [ "${SKIP_ROOT_CHECK:-0}" != "1" ] && [ "$(id -u)" != 0 ]; then
  echo "ERROR: Root required." >&2
  exit 1
fi

[ -d "$LIB" ] || { echo "ERROR: 32-bit library directory not found: $LIB" >&2; exit 1; }

umask 077
mkdir -p "$STATE_DIR"

# Concurrency lock management with stale lock reclamation
acquire_lock() {
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    # Lock directory exists. Check whether owner is alive or dead/rebooted
    local LOCK_PID=""
    local LOCK_BOOT=""
    if [ -f "$LOCK_DIR/pid" ]; then
      LOCK_PID=$(cat "$LOCK_DIR/pid" 2>/dev/null || true)
    fi
    if [ -f "$LOCK_DIR/boot_id" ]; then
      LOCK_BOOT=$(cat "$LOCK_DIR/boot_id" 2>/dev/null || true)
    fi
    local CURR_BOOT=""
    if [ -f /proc/sys/kernel/random/boot_id ]; then
      CURR_BOOT=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)
    fi

    local IS_STALE=0
    if [ -n "$LOCK_BOOT" ] && [ -n "$CURR_BOOT" ] && [ "$LOCK_BOOT" != "$CURR_BOOT" ]; then
      IS_STALE=1
    elif [ -n "$LOCK_PID" ]; then
      if ! kill -0 "$LOCK_PID" 2>/dev/null; then
        IS_STALE=1
      fi
    else
      IS_STALE=1
    fi

    if [ "$IS_STALE" = "1" ]; then
      echo "[!] WARNING: Detected stale lock from terminated process (PID: ${LOCK_PID:-unknown}). Reclaiming lock..." >&2
      rm -rf "$LOCK_DIR"
      if ! mkdir "$LOCK_DIR" 2>/dev/null; then
        echo "ERROR: Failed to acquire lock after clearing stale lock directory." >&2
        exit 1
      fi
    else
      echo "ERROR: Another patch operation is currently running (PID: $LOCK_PID)." >&2
      exit 1
    fi
  fi

  echo "$$" > "$LOCK_DIR/pid"
  if [ -f /proc/sys/kernel/random/boot_id ]; then
    cat /proc/sys/kernel/random/boot_id > "$LOCK_DIR/boot_id" 2>/dev/null || true
  fi
}

release_lock() {
  rm -rf "$LOCK_DIR" 2>/dev/null || true
}

SUCCESS=0
TRANSACTION_ACTIVE=0
ACTIVE_BACKUP=""
CLEANED_UP=0

rollback_from_backup() {
  local BDIR="$1"
  if [ "$TRANSACTION_ACTIVE" -eq 0 ]; then
    return 0
  fi
  # Disarm subsequent trap invocations to prevent duplicate rollback
  TRANSACTION_ACTIVE=0

  echo "[*] Rolling back libraries to pre-patch state from $BDIR..." >&2
  echo "STATUS:ROLLING_BACK" >> "$TX_FILE"
  sync

  am force-stop --user 0 "$PACKAGE" 2>/dev/null || true

  # Restore original libraries with exact file permissions preserved
  if [ -f "$BDIR/original.sha256" ]; then
    while read -r HASH NAME; do
      if [ -f "$BDIR/original/$NAME" ]; then
        cp -p "$BDIR/original/$NAME" "$LIB/$NAME.c10h-tmp.$$"
        mv "$LIB/$NAME.c10h-tmp.$$" "$LIB/$NAME"
        restorecon -F "$LIB/$NAME" 2>/dev/null || true
      fi
    done < "$BDIR/original.sha256"
  fi

  # Clean up project-created patched artifacts and project temp files ONLY
  rm -f "$LIB/libbili_o.so" "$LIB/libbsl.so" "$LIB"/*.c10h-tmp.*

  sync

  # Verify restored state
  if [ -f "$BDIR/original.sha256" ] && (cd "$LIB" && sha256sum -c "$BDIR/original.sha256" >/dev/null 2>&1); then
    echo "[+] Rollback successful: original libraries verified and restored." >&2
    echo "STATUS:ROLLED_BACK" >> "$TX_FILE"
    sync
  else
    echo "FATAL: Rollback hash verification failed!" >&2
    echo "STATUS:ROLLBACK_FAILED" >> "$TX_FILE"
    sync
    return 1
  fi
}

cleanup() {
  EXIT_CODE=$?
  if [ "$CLEANED_UP" -eq 1 ]; then
    return
  fi
  CLEANED_UP=1
  # CRITICAL: Keep exclusive lock held throughout entire rollback process!
  if [ "$SUCCESS" -ne 1 ] && [ "$TRANSACTION_ACTIVE" -eq 1 ]; then
    echo "[!] Transaction interrupted or failed (exit code $EXIT_CODE). Initiating rollback..." >&2
    if [ -n "$ACTIVE_BACKUP" ] && [ -d "$ACTIVE_BACKUP/original" ]; then
      rollback_from_backup "$ACTIVE_BACKUP" || true
    fi
  fi
  # Release lock ONLY after rollback and state persistence have completely finished
  release_lock
}
trap cleanup EXIT INT TERM

# Obtain application version identity
get_app_version() {
  if [ -n "${MOCK_APP_VERSION:-}" ]; then
    echo "$MOCK_APP_VERSION"
  elif [ -n "${APK:-}" ]; then
    dumpsys package "$PACKAGE" 2>/dev/null | grep -E 'versionName|versionCode' | tr -d ' \r' | tr '\n' ';' || true
  else
    echo "none"
  fi
}

if [ "$MODE" = "restore" ]; then
  acquire_lock

  INPUT="${2:-}"
  if [ -z "$INPUT" ]; then
    if [ -f "$TX_FILE" ]; then
      INPUT=$(grep '^BACKUP_DIR:' "$TX_FILE" 2>/dev/null | tail -n 1 | cut -d: -f2- || true)
    fi
    if [ -z "$INPUT" ] || [ ! -d "$INPUT" ]; then
      for d in "$STATE_DIR"/backup-*; do
        if [ -d "$d" ]; then
          INPUT="$d"
        fi
      done
    fi
    if [ -z "$INPUT" ] || [ ! -d "$INPUT" ]; then
      echo "ERROR: No backup directory specified and no recorded backup found in $STATE_DIR." >&2
      exit 1
    fi
    echo "[*] Using recorded backup: $INPUT"
  fi

  REAL_STATE=$(CDPATH= cd -- "$STATE_DIR" 2>/dev/null && pwd || echo "$STATE_DIR")
  REAL_INPUT=$(CDPATH= cd -- "$INPUT" 2>/dev/null && pwd || echo "$INPUT")
  case "$REAL_INPUT" in "$REAL_STATE"/*) ;; *) echo "ERROR: Backup directory must reside within $STATE_DIR." >&2; exit 1;; esac
  INPUT="$REAL_INPUT"

  if [ ! -f "$INPUT/original.sha256" ] || [ ! -d "$INPUT/original" ]; then
    echo "ERROR: Invalid backup at $INPUT: missing original/ or original.sha256." >&2
    exit 1
  fi

  # Two-pass static pre-flight check on backup files
  echo "[*] Pre-flight verification: checking backup file integrity..."
  if ! (cd "$INPUT/original" && sha256sum -c "$INPUT/original.sha256" >/dev/null 2>&1); then
    echo "ERROR: Backup files corrupted! Hash verification failed for $INPUT/original." >&2
    echo "       Device state has NOT been altered. Refusing to restore corrupted backup." >&2
    exit 1
  fi

  # HARD GUARD: Cross-application version / path mismatch protection
  if [ -f "$INPUT/lib.path" ]; then
    REC_LIB=$(cat "$INPUT/lib.path" 2>/dev/null || true)
    if [ -n "$REC_LIB" ] && [ "$REC_LIB" != "$LIB" ]; then
      echo "ERROR: Target library path mismatch!" >&2
      echo "       Recorded in backup : $REC_LIB" >&2
      echo "       Current application: $LIB" >&2
      echo "Refusing to restore across different application installations/paths." >&2
      exit 1
    fi
  fi

  if [ -f "$INPUT/app_version.txt" ]; then
    REC_VER=$(cat "$INPUT/app_version.txt" 2>/dev/null || true)
    CURR_VER=$(get_app_version)
    if [ -n "$REC_VER" ] && [ -n "$CURR_VER" ] && [ "$REC_VER" != "VERSION:${CURR_VER}" ]; then
      echo "ERROR: Application version identity mismatch!" >&2
      echo "       Recorded in backup : $REC_VER" >&2
      echo "       Current installed  : VERSION:${CURR_VER}" >&2
      echo "Refusing to restore backup from a different application version to avoid ABI breakage." >&2
      exit 1
    fi
  fi

  echo "STATUS:RESTORING" >> "$TX_FILE"
  echo "RESTORED_FROM:$INPUT" >> "$TX_FILE"
  sync

  am force-stop --user 0 "$PACKAGE" 2>/dev/null || true

  # Restore libraries preserving exact file permissions
  while read -r HASH NAME; do
    cp -p "$INPUT/original/$NAME" "$LIB/$NAME.c10h-tmp.$$"
    mv "$LIB/$NAME.c10h-tmp.$$" "$LIB/$NAME"
    restorecon -F "$LIB/$NAME" 2>/dev/null || true
  done < "$INPUT/original.sha256"

  # Clean up project-created patched artifacts and temp files ONLY
  rm -f "$LIB/libbili_o.so" "$LIB/libbsl.so" "$LIB"/*.c10h-tmp.*
  sync

  echo "[*] Verifying restored libraries in $LIB..."
  if ! (cd "$LIB" && sha256sum -c "$INPUT/original.sha256" >/dev/null 2>&1); then
    echo "ERROR: Post-restore SHA-256 verification failed!" >&2
    echo "STATUS:RESTORE_FAILED" >> "$TX_FILE"
    sync
    exit 1
  fi

  echo "STATUS:RESTORED" >> "$TX_FILE"
  sync

  SUCCESS=1
  echo "[+] Original Bilibili libraries successfully restored and verified from $INPUT."
  exit 0
fi

if [ "$MODE" = "apply" ]; then
  acquire_lock

  INPUT="${2:-}"
  [ -n "$INPUT" ] || { echo "Usage: sh $0 apply PREPARED_DIR" >&2; exit 1; }
  [ -d "$INPUT" ] || { echo "ERROR: Directory $INPUT does not exist." >&2; exit 1; }
  INPUT=$(CDPATH= cd -- "$INPUT" && pwd)

  for MANIFEST in original.sha256 patched.sha256; do
    [ -s "$INPUT/$MANIFEST" ] || { echo "ERROR: Missing $MANIFEST in $INPUT" >&2; exit 1; }
    if [ "$(head -n 1 "$INPUT/$MANIFEST" | tr -d -c '\r')" != "" ]; then
      echo "ERROR: Manifest $MANIFEST contains carriage returns (CRLF)." >&2
      exit 1
    fi
    if grep -Ev '^[0-9a-f]{64}  [A-Za-z0-9_.+-]+\.so$' "$INPUT/$MANIFEST" >/dev/null 2>&1; then
      echo "ERROR: Invalid format in manifest $INPUT/$MANIFEST" >&2
      exit 1
    fi
  done

  # Transaction collision & interruption guard
  if [ -f "$TX_FILE" ]; then
    LAST_STATUS=$(grep '^STATUS:' "$TX_FILE" 2>/dev/null | tail -n 1 | cut -d: -f2 || true)
    if [ "$LAST_STATUS" = "APPLYING" ] || [ "$LAST_STATUS" = "ROLLING_BACK" ]; then
      echo "ERROR: An interrupted transaction was detected in $TX_FILE (Status: $LAST_STATUS)." >&2
      echo "       Device state may be inconsistent. Please run 'sh $0 restore' to recover original state." >&2
      exit 1
    fi
  fi

  # Existing patch guard
  if [ -e "$LIB/libbili_o.so" ] || [ -e "$LIB/libbsl.so" ]; then
    echo "ERROR: Target application is already patched (libbili_o.so / libbsl.so exist)." >&2
    echo "       Please run 'sh $0 restore' before re-applying." >&2
    exit 1
  fi

  # Pre-flight SHA-256 checks
  echo "[*] Pre-flight verification: checking prepared patch integrity..."
  if ! (cd "$INPUT" && sha256sum -c patched.sha256 >/dev/null 2>&1); then
    echo "ERROR: Prepared patch files in $INPUT failed SHA-256 validation!" >&2
    exit 1
  fi

  echo "[*] Pre-flight verification: checking target libraries on device..."
  if ! (cd "$LIB" && sha256sum -c "$INPUT/original.sha256" >/dev/null 2>&1); then
    echo "ERROR: Target libraries in $LIB do not match expected original.sha256!" >&2
    echo "       App version may differ or files were already modified. Aborting before making any changes." >&2
    exit 1
  fi

  # Create backup
  TIMESTAMP=$(date +%s)
  BACKUP_DIR="$STATE_DIR/backup-${TIMESTAMP}-$$"
  mkdir -p "$BACKUP_DIR/original"
  printf '%s\n' "$LIB" > "$BACKUP_DIR/lib.path"
  printf '%s\n' "${APK:-none}" > "$BACKUP_DIR/apk.path"
  echo "VERSION:$(get_app_version)" > "$BACKUP_DIR/app_version.txt"
  cp "$INPUT/original.sha256" "$BACKUP_DIR/original.sha256"
  cp "$INPUT/patched.sha256" "$BACKUP_DIR/patched.sha256"

  while read -r HASH NAME; do
    cp -p "$LIB/$NAME" "$BACKUP_DIR/original/$NAME"
  done < "$INPUT/original.sha256"

  if ! (cd "$BACKUP_DIR/original" && sha256sum -c ../original.sha256 >/dev/null 2>&1); then
    echo "ERROR: Backup integrity verification failed!" >&2
    rm -rf "$BACKUP_DIR"
    exit 1
  fi
  sync

  # Start transaction
  cat <<EOF > "$TX_FILE"
TIMESTAMP:$TIMESTAMP
LIB:$LIB
BACKUP_DIR:$BACKUP_DIR
STATUS:BACKED_UP
EOF
  sync

  ACTIVE_BACKUP="$BACKUP_DIR"
  TRANSACTION_ACTIVE=1

  echo "STATUS:APPLYING" >> "$TX_FILE"
  sync

  am force-stop --user 0 "$PACKAGE" 2>/dev/null || true

  # Atomic copy & rename into place preserving individual file permissions
  while read -r HASH NAME; do
    # Fault injection hook for automated testing
    if [ -n "${FAIL_ON_SO:-}" ] && [ "$NAME" = "$FAIL_ON_SO" ]; then
      echo "ERROR: Injected write failure on $NAME" >&2
      exit 1
    fi

    case "$NAME" in
      libbili_o.so) TEMPLATE="libcrypto.so" ;;
      libbsl.so)    TEMPLATE="libssl.so" ;;
      *)            TEMPLATE="$NAME" ;;
    esac

    TEMP_FILE="$LIB/$NAME.c10h-tmp.$$"
    ORIG_PERM=""
    if [ -f "$LIB/$TEMPLATE" ]; then
      cp -p "$LIB/$TEMPLATE" "$TEMP_FILE" 2>/dev/null || true
      ORIG_PERM=$(stat -c '%a' "$LIB/$TEMPLATE" 2>/dev/null || true)
    fi
    cat "$INPUT/$NAME" > "$TEMP_FILE"
    if [ -n "$ORIG_PERM" ]; then
      chmod "$ORIG_PERM" "$TEMP_FILE"
    else
      chmod 755 "$TEMP_FILE"
    fi
    mv "$TEMP_FILE" "$LIB/$NAME"
    restorecon -F "$LIB/$NAME" 2>/dev/null || true
  done < "$INPUT/patched.sha256"

  # Fault injection hook for post-check testing
  if [ "${FAIL_POST_CHECK:-0}" = "1" ]; then
    echo "CORRUPTED" >> "$LIB/libcrypto.so"
  fi

  # Post-flight verification
  echo "[*] Post-flight verification: checking applied libraries..."
  if ! (cd "$LIB" && sha256sum -c "$INPUT/patched.sha256" >/dev/null 2>&1); then
    echo "ERROR: Post-patch SHA-256 verification failed! Initiating rollback..." >&2
    exit 1
  fi

  sync

  echo "STATUS:COMPLETED" >> "$TX_FILE"
  sync

  SUCCESS=1
  TRANSACTION_ACTIVE=0
  echo "[+] Bilibili BoringSSL patch applied and verified successfully!"
  echo "[+] Backup preserved at: $BACKUP_DIR"
  echo "    To revert anytime, run: sh $0 restore $BACKUP_DIR"
  exit 0
fi

echo "Usage:" >&2
echo "  sh $0 apply PREPARED_DIR    Apply host-prepared ELF patch with transactional safety" >&2
echo "  sh $0 restore [BACKUP_DIR]  Restore original unpatched libraries" >&2
echo "  sh $0 status                Display current patch and transaction status" >&2
exit 1
