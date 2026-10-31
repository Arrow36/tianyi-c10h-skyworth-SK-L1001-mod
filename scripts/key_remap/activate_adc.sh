#!/system/bin/sh
# activate_adc.sh - Compatibility wrapper (managed by supervisor.sh in activate.sh)
BASE=/data/local/codex-screen-toggle
exec /system/bin/sh "$BASE/activate.sh"
