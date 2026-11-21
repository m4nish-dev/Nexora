#!/usr/bin/env bash
# End-to-end check of a running backend with REAL provider keys (local or deployed).
#   ./backend/scripts/smoke_test.sh http://localhost:8000
#   ./backend/scripts/smoke_test.sh https://your-backend.onrender.com
# Requires: curl, python3. ENABLE_FAILURE_SIMULATION=true on the target for the failover checks.
set -uo pipefail

BASE="${1:-http://localhost:8000}"
BASE="${BASE%/}"
RUN="smoke-$(date +%s)-$RANDOM"
PASS=0
FAIL=0

ok()   { PASS=$((PASS + 1)); printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '  \033[31mFAIL\033[0m %s\n     %s\n' "$1" "$2"; }
json() { python3 -c "import sys,json; d=json.load(sys.stdin); print(eval(sys.argv[1], {}, {'d': d}))" "$1"; }

# post <session> <message> [simulate-header]  -> sets STATUS and BODY
post() {
  local hdr=()
  [ -n "${3:-}" ] && hdr=(-H "X-Simulate-Failure: $3")
  local out
  out=$(curl -s -w $'\n%{http_code}' -X POST "$BASE/chat" -H 'Content-Type: application/json' "${hdr[@]}" \
    -d "{\"session_id\": \"$1\", \"message\": \"$2\"}")
  STATUS="${out##*$'\n'}"
  BODY="${out%$'\n'*}"
}

echo "Target: $BASE   (run id $RUN)"

echo "[health]"
H=$(curl -s -w $'\n%{http_code}' "$BASE/health")
[ "${H##*$'\n'}" = "200" ] && ok "GET /health 200 → ${H%$'\n'*}" || bad "GET /health" "$H"

echo "[live → cache]"
Q="In one short sentence, what is the capital of France? ($RUN)"
post "$RUN-a" "$Q"
if [ "$STATUS" = 200 ] && [ "$(echo "$BODY" | json "d['metadata']['resolution_source']")" = LIVE_INFERENCE ]; then
  ok "first call LIVE_INFERENCE ($(echo "$BODY" | json "d['metadata']['latency_ms']") ms, key $(echo "$BODY" | json "d['metadata']['key_id']"), tokens $(echo "$BODY" | json "(d['metadata']['input_tokens'], d['metadata']['output_tokens'])"))"
  LIVE_REPLY=$(echo "$BODY" | json "d['reply']")
  LIVE_MS=$(echo "$BODY" | json "d['metadata']['latency_ms']")
else bad "first call LIVE_INFERENCE" "$STATUS $BODY"; fi

post "$RUN-b" "$Q"
if [ "$STATUS" = 200 ] && [ "$(echo "$BODY" | json "d['metadata']['resolution_source']")" = LLM_CACHE ]; then
  ok "same first message, new session → LLM_CACHE ($(echo "$BODY" | json "d['metadata']['latency_ms']") ms, key_id $(echo "$BODY" | json "d['metadata']['key_id']"))"
  [ "$(echo "$BODY" | json "d['reply']")" = "${LIVE_REPLY:-}" ] && ok "cached reply identical" || bad "cached reply identical" "differs"
  [ "$(echo "$BODY" | json "d['metadata']['latency_ms']")" -lt "${LIVE_MS:-0}" ] && ok "cache hit faster than live" || bad "cache faster" "$BODY"
else bad "second call LLM_CACHE" "$STATUS $BODY"; fi

post "$RUN-c" "In one short sentence, what is the capital of Spain? ($RUN)"
[ "$(echo "$BODY" | json "d['metadata']['resolution_source']")" = LIVE_INFERENCE ] && ok "different message → LIVE_INFERENCE" || bad "different message live" "$BODY"

echo "[multi-turn]"
post "$RUN-m" "My favourite colour is teal. Reply with just OK."
post "$RUN-m" "What is my favourite colour? Answer in one word."
echo "$BODY" | json "d['reply'].lower()" | grep -q teal && ok "remembers earlier turn ($(echo "$BODY" | json "d['reply']"))" || bad "multi-turn memory" "$BODY"

echo "[failover hook]"
post "$RUN-f1" "Say hello in French. ($RUN)" "key_1=429"
[ "$STATUS" = 200 ] && [ "$(echo "$BODY" | json "d['metadata']['key_id']")" = key_2 ] && ok "key_1=429 → 200 via key_2 (fallback_attempts $(echo "$BODY" | json "d['metadata']['fallback_attempts']"))" || bad "key_1=429" "$STATUS $BODY"
post "$RUN-f2" "Say hello in German. ($RUN)" "key_1=500"
[ "$STATUS" = 200 ] && [ "$(echo "$BODY" | json "d['metadata']['key_id']")" = key_2 ] && ok "key_1=500 → 200 via key_2" || bad "key_1=500" "$STATUS $BODY"
post "$RUN-f3" "Say hello in Italian. ($RUN)" "*=429"
[ "$STATUS" = 503 ] && [ "$BODY" = '{"detail":"all providers unavailable"}' ] && ok "*=429 → 503 all providers unavailable" || bad "*=429" "$STATUS $BODY"
S=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/sessions/$RUN-f3/messages")
[ "$S" = 404 ] && ok "failed request not persisted" || bad "failed request persisted" "$S"

echo "[history & errors]"
HB=$(curl -s "$BASE/sessions/$RUN-m/messages")
[ "$(echo "$HB" | json "len(d['messages'])")" = 4 ] && ok "history has 4 messages oldest-first" || bad "history" "$HB"
S=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/sessions/does-not-exist-$RUN/messages")
[ "$S" = 404 ] && ok "unknown session → 404" || bad "unknown session" "$S"
post "$RUN-v" ""
[ "$STATUS" = 422 ] && ok "empty message → 422" || bad "empty message" "$STATUS $BODY"

echo
echo "Passed: $PASS   Failed: $FAIL"
[ "$FAIL" -eq 0 ]
