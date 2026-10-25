#!/usr/bin/env bash
# Clean-clone check (build-plan task 20, plan check M): three questions in sample mode, no credentials.
#
#   scripts/clean_clone_check.sh            # from the repository root, with the venv active
#
# Every run gets an empty environment apart from PATH, HOME and SAMPLE_MODE=true, so nothing from the
# shell or a .env leaks in (the app never reads .env itself). The questions:
#   (a) the Day 1 question with --loop simple          -> must succeed (plan check C's result check)
#   (b) the plan check J question with the default loop -> must succeed (plan check J's run check)
#   (c) a question with no recorded answer               -> must return the structured cache_miss error
# Prints one line per question (question, status or error code, determinable, top cause) and exits 1
# if (a) or (b) fails or (c) does not give the structured error. Each command has a timeout
# (CLEAN_CLONE_TIMEOUT_SECONDS, default 300 s per run); `timeout`, `gtimeout` or perl enforces it.

set -u
cd "$(dirname "$0")/.." || exit 2

PY="${PYTHON:-python}"
LIMIT="${CLEAN_CLONE_TIMEOUT_SECONDS:-300}"
OUT="$(mktemp -d "${TMPDIR:-/tmp}/clean-clone-check.XXXXXX")" || exit 2
trap 'rm -rf "$OUT"' EXIT

with_timeout() {  # with_timeout SECONDS COMMAND...: run COMMAND, kill it after SECONDS
  local seconds="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$seconds" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$seconds" "$@"
  else  # macOS without coreutils: SIGALRM survives exec
    perl -e 'alarm shift @ARGV; exec @ARGV or exit 127' "$seconds" "$@"
  fi
}

# Prefix for every command: an empty environment with sample mode on.
CLEAN_ENV=(env -i PATH="$PATH" HOME="${HOME:-/tmp}" PYTHONUTF8=1 SAMPLE_MODE=true)

# macOS: decide the CPU from the hardware, never from this process. This shell may itself run as x86_64
# (an Intel bash first in PATH, under Rosetta), and a universal2 Python started from it comes up as
# x86_64 too, while the venv's wheels are arm64. On Apple Silicon (`sysctl -n hw.optional.arm64` is 1,
# also under Rosetta) every command runs as `arch -arm64 env -i ... ARCHPREFERENCE=arm64 arch -arm64`.
# Elsewhere (Intel Mac, no answer, Linux) there is no prefix.
if [ "$(uname -s)" = Darwin ]; then
  HW_ARM64="$( (sysctl -n hw.optional.arm64 || /usr/sbin/sysctl -n hw.optional.arm64) 2>/dev/null)"
  if [ "$HW_ARM64" = 1 ]; then
    CLEAN_ENV=(arch -arm64 env -i PATH="$PATH" HOME="${HOME:-/tmp}" PYTHONUTF8=1 SAMPLE_MODE=true
      ARCHPREFERENCE=arm64 arch -arm64)
  fi
fi
if [ "${CLEAN_CLONE_PRINT_PREFIX:-}" = 1 ]; then  # for tests: print the prefix, one word per line
  printf '%s\n' "${CLEAN_ENV[@]}"
  exit 0
fi

# summarise QUESTION RESULT.json EXIT_CODE EXPECT CHECKER_EXIT: print the line, exit 0 if it meets EXPECT
summarise() {
  with_timeout 60 "${CLEAN_ENV[@]}" "$PY" - "$@" <<'EOF'
import json
import sys

question, path, code, expect, checker = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], int(sys.argv[5])
try:
    with open(path, encoding="utf-8") as handle:
        result = json.load(handle)
except (OSError, ValueError) as exc:
    result = {"status": "error", "error": {"code": f"no result JSON ({type(exc).__name__})"}}
error = (result.get("error") or {}).get("code")
status = result.get("status", "?") if error is None else f"error {error}"
causes = result.get("causes") or []
top = causes[0].get("type", "?") if causes else "none"
determinable = str(result.get("determinable", "?")).lower()
if expect == "success":
    ok = code == 0 and checker == 0 and result.get("status") == "success" and result.get("sample_mode") is True
else:
    message = (result.get("error") or {}).get("message", "")
    ok = (code == 1 and result.get("status") == "error" and error == "cache_miss" and "needs a model key" in message
          and result.get("sample_mode") is True and not causes)
tag = "PASS" if ok else "FAIL"
extra = "" if code in (0, 1) else f" (exit {code}{', timed out' if code in (124, 142) else ''})"
print(f"[{tag}] {question} | {status} | determinable={determinable} | top cause={top}{extra}")
sys.exit(0 if ok else 1)
EOF
}

# check NAME EXPECT QUESTION [run.py args...]
check() {
  local name="$1" expect="$2" question="$3"
  shift 3
  local result="$OUT/$name.json" code checker=0
  with_timeout "$LIMIT" "${CLEAN_ENV[@]}" "$PY" run.py "$question" --run-id "clean-clone-$name" "$@" >"$result" 2>"$OUT/$name.err"
  code=$?
  if [ "$expect" = success ] && [ "$code" = 0 ]; then
    if [ "$name" = day1 ]; then
      with_timeout 60 "${CLEAN_ENV[@]}" "$PY" scripts/check_result.py "$result" >"$OUT/$name.check" 2>&1 || checker=$?
    else
      with_timeout 60 "${CLEAN_ENV[@]}" "$PY" scripts/check_markovian_run.py "$result" --max-seconds 600 >"$OUT/$name.check" 2>&1 \
        || checker=$?
    fi
  fi
  if ! summarise "$question" "$result" "$code" "$expect" "$checker"; then
    echo "  --- stderr of ($name) ---"
    tail -n 20 "$OUT/$name.err"
    [ -f "$OUT/$name.check" ] && { echo "  --- check of ($name) ---"; tail -n 20 "$OUT/$name.check"; }
    return 1
  fi
}

failed=0
check day1 success "Why did order volume spike on 24 November 2017?" --loop simple || failed=1
check plan-j success "Why did delivery lateness spike for deliveries completed the week of 28 May 2018?" || failed=1
check unrecorded cache_miss "Why did review scores fall in March 2018?" || failed=1

if [ "$failed" = 0 ]; then
  echo "clean clone check: PASS (3 of 3)"
else
  echo "clean clone check: FAIL"
fi
exit "$failed"
