#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Passport India - Slot Watcher
# Reads results written by python3 check_slots.py (slots_result.json)
# and alerts with sound + notification when a wanted date appears.
#
# Run python3 check_slots.py in another terminal first.
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_DATES=(
    "08/06/2026" "09/06/2026" "10/06/2026"
    "12/06/2026" "13/06/2026" "14/06/2026"
    "15/06/2026" "16/06/2026" "17/06/2026"
    "18/06/2026" "19/06/2026" 
)

DIR="$(dirname "$0")"
RESULT_FILE="$DIR/slots_result.json"
CHECK_INTERVAL=0.5   # seconds between file reads

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

alert() {
    local date="$1"
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  ★★★  WANTED DATE FOUND: $date  ★★★  ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
    osascript -e "display notification \"Slot available: $date — Book NOW!\" with title \"Passport Slot FOUND!\" sound name \"Glass\"" 2>/dev/null
    # Repeat bell 5 times
    for i in {1..5}; do printf '\a'; sleep 0.3; done
}

echo ""
echo "══════════════════════════════════════════════════"
echo "  Passport India Slot Watcher"
echo "  Reading from: slots_result.json"
echo "  Watching for: ${REQUIRED_DATES[*]}"
echo "  Press Ctrl+C to stop"
echo "══════════════════════════════════════════════════"
echo ""

if [[ ! -f "$RESULT_FILE" ]]; then
    echo -e "${YELLOW}Waiting for python3 check_slots.py to start writing results...${NC}"
fi

last_attempt=0
last_earliest=""

while true; do
    if [[ ! -f "$RESULT_FILE" ]]; then
        sleep 1
        continue
    fi

    # Parse slots_result.json
    parsed=$(python3 -c "
import sys, json
try:
    with open('$RESULT_FILE') as f:
        d = json.load(f)
    dates = d.get('dates') or []
    print('attempt=' + str(d.get('attempt', 0)))
    print('ms=' + str(d.get('ms', 0)))
    print('earliest=' + str(d.get('earliest','')))
    print('count=' + str(len(dates)))
    for dt in sorted(dates):
        print('date=' + dt)
except Exception as e:
    print('error=' + str(e))
" 2>/dev/null)

    attempt=$(echo "$parsed" | grep '^attempt=' | cut -d= -f2)
    ms=$(echo "$parsed"      | grep '^ms='      | cut -d= -f2)
    earliest=$(echo "$parsed" | grep '^earliest=' | cut -d= -f2)
    count=$(echo "$parsed"   | grep '^count='   | cut -d= -f2)

    # Only print when attempt changes (new result from Python)
    if [[ "$attempt" != "$last_attempt" ]]; then
        last_attempt="$attempt"

        avail_dates=()
        while IFS= read -r line; do
            [[ "$line" == date=* ]] && avail_dates+=("${line#date=}")
        done <<< "$parsed"

        if (( count > 0 )); then
            wanted_found=""
            for d in "${avail_dates[@]}"; do
                for req in "${REQUIRED_DATES[@]}"; do
                    [[ "$d" == "$req" ]] && wanted_found="$d" && break 2
                done
            done

            if [[ -n "$wanted_found" ]]; then
                echo -e "[#$attempt] ${ms}ms | ${GREEN}$count slots — earliest: $earliest${NC}"
                for d in "${avail_dates[@]}"; do
                    marker=""; for req in "${REQUIRED_DATES[@]}"; do [[ "$d" == "$req" ]] && marker=" ← WANTED" && break; done
                    echo "    • $d$marker"
                done
                alert "$wanted_found"
            elif [[ "$earliest" != "$last_earliest" ]]; then
                last_earliest="$earliest"
                echo -e "[#$attempt] ${ms}ms | ${CYAN}$count slots — earliest: $earliest${NC} (none wanted)"
            else
                echo -e "[#$attempt] ${ms}ms | $count slots — earliest: $earliest"
            fi
        fi
    fi

    sleep "$CHECK_INTERVAL"
done
