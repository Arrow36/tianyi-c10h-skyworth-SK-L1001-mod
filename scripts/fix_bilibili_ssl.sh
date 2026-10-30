#!/system/bin/sh
# fix_bilibili_ssl.sh
# Fixes Bilibili (tv.danmaku.bili) crash on Android 9 (32-bit armeabi-v7a):
#   dlopen failed: cannot locate symbol "EVP_hpke_aes_128_gcm" referenced by "libssl.so"
# Cause: Android 9 Zygote preloads /system/lib/libcrypto.so and /system/lib/libssl.so into
# the global namespace, shadowing Bilibili's bundled BoringSSL libraries.
# Solution: Rename SONAME/DT_NEEDED references from libcrypto.so -> libbili_o.so (12 chars)
# and libssl.so -> libbsl.so (9 chars).

BILI_LIB_DIR=$(ls -d /data/app/tv.danmaku.bili-*/lib/arm 2>/dev/null | head -n 1)
if [ -z "$BILI_LIB_DIR" ]; then
    echo "[-] tv.danmaku.bili lib/arm directory not found!"
    exit 1
fi

cd "$BILI_LIB_DIR" || exit 1
echo "[*] Patching ELF dynamic references in $BILI_LIB_DIR ..."
sed -i 's/libcrypto\.so/libbili_o.so/g' *.so
sed -i 's/libssl\.so/libbsl.so/g' *.so
cp -f libcrypto.so libbili_o.so
cp -f libssl.so libbsl.so
chmod 755 *.so
chown system:system *.so
am force-stop tv.danmaku.bili
echo "[+] Fixed! Launching Bilibili..."
am start -n tv.danmaku.bili/.MainActivityV2
