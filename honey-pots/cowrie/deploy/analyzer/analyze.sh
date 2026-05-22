#!/bin/bash

WATCH_DIR="/downloads"
LOG_FILE="/logs/malware-analysis.json"
RULES_INDEX="/etc/yara/rules/index.yar"
SEEN_FILE="/logs/.seen-hashes"
COWRIE_LOG="/logs/cowrie/cowrie.json"

mkdir -p /logs

_catalog_push() {
    local filepath="$1" sha256="$2" filename="$3"
    [ -z "${CATALOG_URL:-}" ] && return 0

    local src_ip="unknown" url="" orig_filename="$filename"
    if [ -f "$COWRIE_LOG" ]; then
        local match
        match=$(grep "\"$sha256\"" "$COWRIE_LOG" | tail -1 2>/dev/null || true)
        if [ -n "$match" ]; then
            src_ip=$(echo "$match" | jq -r '.src_ip // "unknown"')
            url=$(echo "$match"    | jq -r '.url    // ""')
            local url_name
            url_name=$(echo "$url" | sed 's|.*/||' | tr -dc '[:print:]' | cut -c1-256)
            orig_filename="${url_name:-$filename}"
        fi
    fi

    curl -sf -X POST "${CATALOG_URL}/samples" \
        -F "file=@${filepath};type=application/octet-stream" \
        -F "honeypot=${HONEYPOT_HOSTNAME:-cowrie-honeypot}" \
        -F "src_ip=${src_ip}" \
        -F "url=${url}" \
        -F "filename=${orig_filename}" \
        > /dev/null \
        && echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] pushed ${filename} to catalog (src=${src_ip})" \
        || echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] WARNING: failed to push ${filename} to catalog" >&2
}

analyze_file() {
    local filepath="$1"
    local filename
    filename=$(basename "$filepath")

    local sha256
    sha256=$(sha256sum "$filepath" | awk '{print $1}')

    # Push to catalog on every download — catalog deduplicates by sha256 but
    # records each submission separately for provenance (src_ip, url, honeypot).
    _catalog_push "$filepath" "$sha256" "$filename"

    if grep -qF "$sha256" "$SEEN_FILE" 2>/dev/null; then
        return
    fi
    echo "$sha256" >> "$SEEN_FILE"

    local file_type size yara_matches strings_hits
    file_type=$(file -b "$filepath" 2>/dev/null || echo "unknown")
    size=$(stat -c%s "$filepath" 2>/dev/null || echo 0)

    if [ -f "$RULES_INDEX" ]; then
        yara_matches=$(yara "$RULES_INDEX" "$filepath" 2>/dev/null \
            | awk '{print $1}' | tr '\n' ',' | sed 's/,$//' || true)
    fi
    yara_matches="${yara_matches:-}"

    strings_hits=$(grep -a -o '[[:print:]]\{6,\}' "$filepath" 2>/dev/null \
        | grep -E '(https?://|/bin/sh|/tmp/|chmod|wget|curl|bash -i|/etc/passwd|stratum\+)' \
        | head -20 \
        | tr '\n' '|' | sed 's/|$//' || true)
    strings_hits="${strings_hits:-}"

    jq -cn \
        --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
        --arg file "$filename" \
        --arg sha256 "$sha256" \
        --argjson size "$size" \
        --arg type "$file_type" \
        --arg yara "${yara_matches}" \
        --arg strings "${strings_hits}" \
        '{timestamp:$ts,filename:$file,sha256:$sha256,size:$size,file_type:$type,yara_matches:$yara,strings_hits:$strings}' \
        >> "$LOG_FILE"

    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] analyzed $filename sha256=${sha256:0:12} yara=${yara_matches:-none}"
}

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] analyzer starting, watching $WATCH_DIR"

# Analyze files already present at startup (catches anything downloaded while container was down)
find "$WATCH_DIR" -maxdepth 1 -type f 2>/dev/null | while read -r f; do
    analyze_file "$f"
done

# Watch for new arrivals
inotifywait -m -e close_write -e moved_to "$WATCH_DIR" --format '%f' |
while read -r filename; do
    fp="$WATCH_DIR/$filename"
    [ -f "$fp" ] && analyze_file "$fp"
done
