#!/system/bin/sh
# fix_bilibili_ssl.sh
# Fixes Bilibili (tv.danmaku.bili) crash on Android 9 (32-bit armeabi-v7a):
#   dlopen failed: cannot locate symbol "EVP_hpke_aes_128_gcm" referenced by "libssl.so"
# Supports:
#   1. sh fix_bilibili_ssl.sh                       (Direct device mode with safe backup)
#   2. sh fix_bilibili_ssl.sh apply PREPARED_DIR    (Host-checked ELF mode with SHA256 manifests)
#   3. sh fix_bilibili_ssl.sh restore BACKUP_DIR    (One-click rollback from backup)

set -eu
[ "$(id -u)" = 0 ] || { echo 'Root required.' >&2; exit 1; }

PACKAGE=tv.danmaku.bili
ROOT=/data/local/c10h-bili-backups

APK=$(pm path "$PACKAGE" | sed -n 's/^package://p' | head -n 1)
[ -n "$APK" ] || { echo 'Bilibili is not installed.' >&2; exit 1; }

LIB=${APK%/*}/lib/arm
[ -d "$LIB" ] || { echo '32-bit extracted libraries not found.' >&2; exit 1; }

umask 077
mkdir -p "$ROOT"
mkdir "$ROOT/lock" || { echo 'Another patch operation is running.' >&2; exit 1; }
trap 'rmdir "$ROOT/lock" 2>/dev/null || true' EXIT

MODE="${1:-auto}"

if [ "$MODE" = "restore" ]; then
  INPUT="${2:-}"
  [ -n "$INPUT" ] || { echo 'Usage: sh fix_bilibili_ssl.sh restore BACKUP_DIR' >&2; exit 1; }
  case "$INPUT" in "$ROOT"/*) ;; *) echo 'Invalid backup dir' >&2; exit 1;; esac
  [ "$(cat "$INPUT/lib.path" 2>/dev/null)" = "$LIB" ] || { echo 'App path changed; refusing restore.' >&2; exit 1; }
  am force-stop --user 0 "$PACKAGE" 2>/dev/null || true
  cp -p "$INPUT"/original/*.so "$LIB/"
  rm -f "$LIB/libbili_o.so" "$LIB/libbsl.so"
  restorecon -RF "$LIB"
  sync
  echo '[+] Original libraries restored. Backup retained.'
  exit 0
fi

if [ "$MODE" = "apply" ]; then
  INPUT="${2:-}"
  [ -n "$INPUT" ] || { echo 'Usage: sh fix_bilibili_ssl.sh apply PREPARED_DIR' >&2; exit 1; }
  INPUT=$(CDPATH= cd -- "$INPUT" && pwd)
  for MANIFEST in original.sha256 patched.sha256; do
    [ -s "$INPUT/$MANIFEST" ] || { echo "Missing $MANIFEST in $INPUT" >&2; exit 1; }
    if grep -Ev '^[0-9a-f]{64}  [A-Za-z0-9_.+-]+\.so$' "$INPUT/$MANIFEST"; then
      echo 'Invalid manifest.' >&2; exit 1
    fi
  done
  [ ! -e "$LIB/libbili_o.so" ] && [ ! -e "$LIB/libbsl.so" ] || { echo 'Already patched; restore first.' >&2; exit 1; }
  (cd "$INPUT" && sha256sum -c patched.sha256)
  (cd "$LIB" && sha256sum -c "$INPUT/original.sha256")
  BACKUP="$ROOT/$(date +%s)-$$"
  mkdir -p "$BACKUP/original"
  printf '%s\n' "$LIB" > "$BACKUP/lib.path"
  cp "$INPUT/original.sha256" "$BACKUP/original.sha256"
  cp "$INPUT/patched.sha256" "$BACKUP/patched.sha256"
  while read -r HASH NAME; do cp -p "$LIB/$NAME" "$BACKUP/original/$NAME"; done < "$INPUT/original.sha256"
  (cd "$BACKUP/original" && sha256sum -c ../original.sha256)
  sync
  am force-stop --user 0 "$PACKAGE" 2>/dev/null || true
  while read -r HASH NAME; do
    case "$NAME" in libbili_o.so) ORIGINAL=libcrypto.so;; libbsl.so) ORIGINAL=libssl.so;; *) ORIGINAL=$NAME;; esac
    cp -p "$LIB/$ORIGINAL" "$LIB/$NAME.c10h-new"
    cat "$INPUT/$NAME" > "$LIB/$NAME.c10h-new"
    mv "$LIB/$NAME.c10h-new" "$LIB/$NAME"
  done < "$INPUT/patched.sha256"
  (cd "$LIB" && sha256sum -c "$INPUT/patched.sha256")
  restorecon -RF "$LIB"
  sync
  echo "[+] Patched successfully. Backup saved at: $BACKUP"
  exit 0
fi

# Auto / Direct device mode with automatic snapshot backup
echo '[*] Running in direct device mode...'
if [ -e "$LIB/libbili_o.so" ] || [ -e "$LIB/libbsl.so" ]; then
  echo '[!] Already patched. To restore, use: sh fix_bilibili_ssl.sh restore <BACKUP_DIR>'
  exit 0
fi

BACKUP="$ROOT/$(date +%s)-$$"
mkdir -p "$BACKUP/original"
printf '%s\n' "$LIB" > "$BACKUP/lib.path"
cp -p "$LIB"/*.so "$BACKUP/original/"
sync

echo "[*] Backed up original libraries to: $BACKUP"
am force-stop --user 0 "$PACKAGE" 2>/dev/null || true

cd "$LIB"
sed -i 's/libcrypto\.so/libbili_o\.so/g' *.so
sed -i 's/libssl\.so/libbsl\.so/g' *.so
cp -f libcrypto.so libbili_o.so
cp -f libssl.so libbsl.so
chmod 755 *.so
chown system:system *.so 2>/dev/null || true
restorecon -RF "$LIB" 2>/dev/null || true
sync

echo "[+] Direct patch applied! You can revert anytime with:"
echo "    sh /data/local/tmp/fix_bilibili_ssl.sh restore $BACKUP"
