#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Re-running with sudo..."
  exec sudo "$0" "$@"
fi

auto_yes=0
case "${1:-}" in
  -y|--yes) auto_yes=1 ;;
  -h|--help)
    cat <<'EOF'
Usage: sudo rig-burn-cleanup [--yes]

Kills leftover/stuck local burn-test processes from rig stress testing:
  - full_burn / cpu_burn / ram_burn
  - stressapptest
  - gpu_burn from /opt/gpu-burn or gpu_burn -tc -m runs
  - stress-ng CPU/VM burn workers
  - old memtester wrappers/processes

Use this only when you intentionally want to stop local stress tests.
EOF
    exit 0
    ;;
  "") ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac

patterns=(
  '/usr/local/bin/full_burn'
  'bash /usr/local/bin/full_burn'
  '(^|[[:space:]])full_burn([[:space:]]|$)'
  '/usr/local/bin/cpu_burn'
  'bash /usr/local/bin/cpu_burn'
  '(^|[[:space:]])cpu_burn([[:space:]]|$)'
  '/usr/local/bin/ram_burn'
  'bash /usr/local/bin/ram_burn'
  '(^|[[:space:]])ram_burn([[:space:]]|$)'
  'stressapptest'
  '/opt/gpu-burn/gpu_burn'
  'gpu_burn -tc -m'
  'stress-ng .*--cpu'
  'stress-ng .*--vm'
  '/usr/sbin/memtester'
  '/sbin/memtester'
  '/usr/local/bin/memtester'
  'bash /usr/local/bin/memtester'
  'timeout .*memtester'
)

collect_pids() {
  ps -eo pid=,ppid=,stat=,comm=,args= | awk -v self="$$" -v parent="$PPID" '
    function match_burn(line) {
      return \
        line ~ /\/usr\/local\/bin\/full_burn/ || line ~ /bash \/usr\/local\/bin\/full_burn/ || line ~ /(^|[[:space:]])full_burn([[:space:]]|$)/ || \
        line ~ /\/usr\/local\/bin\/cpu_burn/  || line ~ /bash \/usr\/local\/bin\/cpu_burn/  || line ~ /(^|[[:space:]])cpu_burn([[:space:]]|$)/  || \
        line ~ /\/usr\/local\/bin\/ram_burn/  || line ~ /bash \/usr\/local\/bin\/ram_burn/  || line ~ /(^|[[:space:]])ram_burn([[:space:]]|$)/  || \
        line ~ /stressapptest/ || \
        line ~ /\/opt\/gpu-burn\/gpu_burn/ || line ~ /gpu_burn -tc -m/ || \
        line ~ /stress-ng .*--cpu/ || line ~ /stress-ng .*--vm/ || \
        line ~ /\/usr\/sbin\/memtester/ || line ~ /\/sbin\/memtester/ || line ~ /\/usr\/local\/bin\/memtester/ || line ~ /bash \/usr\/local\/bin\/memtester/ || line ~ /timeout .*memtester/
    }
    {
      pid=$1; ppid=$2; stat=$3; comm=$4;
      line=$0;
      if (pid == self || pid == parent) next;
      if (line ~ /rig-burn-cleanup/) next;
      if (match_burn(line)) print pid;
    }
  ' | sort -n -u
}

print_matches() {
  ps -eo pid,ppid,stat,etimes,rss,vsz,comm,args | awk '
    function match_burn(line) {
      return \
        line ~ /\/usr\/local\/bin\/full_burn/ || line ~ /bash \/usr\/local\/bin\/full_burn/ || line ~ /(^|[[:space:]])full_burn([[:space:]]|$)/ || \
        line ~ /\/usr\/local\/bin\/cpu_burn/  || line ~ /bash \/usr\/local\/bin\/cpu_burn/  || line ~ /(^|[[:space:]])cpu_burn([[:space:]]|$)/  || \
        line ~ /\/usr\/local\/bin\/ram_burn/  || line ~ /bash \/usr\/local\/bin\/ram_burn/  || line ~ /(^|[[:space:]])ram_burn([[:space:]]|$)/  || \
        line ~ /stressapptest/ || \
        line ~ /\/opt\/gpu-burn\/gpu_burn/ || line ~ /gpu_burn -tc -m/ || \
        line ~ /stress-ng .*--cpu/ || line ~ /stress-ng .*--vm/ || \
        line ~ /\/usr\/sbin\/memtester/ || line ~ /\/sbin\/memtester/ || line ~ /\/usr\/local\/bin\/memtester/ || line ~ /bash \/usr\/local\/bin\/memtester/ || line ~ /timeout .*memtester/
    }
    NR == 1 || (match_burn($0) && $0 !~ /rig-burn-cleanup/) { print }
  '
}

mapfile -t pids < <(collect_pids)
if (( ${#pids[@]} == 0 )); then
  echo "No burn/stress-test leftovers found."
  exit 0
fi

echo "Found burn/stress-test processes:"
print_matches

echo
if (( auto_yes == 0 )); then
  read -r -p "Type KILL BURNS to terminate these processes: " answer
  if [[ "$answer" != "KILL BURNS" ]]; then
    echo "Cancelled."
    exit 0
  fi
fi

echo "Sending TERM to: ${pids[*]}"
kill "${pids[@]}" 2>/dev/null || true
sleep 2
mapfile -t remaining < <(collect_pids)
if (( ${#remaining[@]} > 0 )); then
  echo "Still present; sending KILL to: ${remaining[*]}"
  kill -9 "${remaining[@]}" 2>/dev/null || true
  sleep 2
fi

mapfile -t final < <(collect_pids)
if (( ${#final[@]} > 0 )); then
  echo "WARNING: some processes still remain, possibly uninterruptible or zombie until parent exits:"
  print_matches
  exit 1
fi

echo "Burn/stress-test cleanup complete."
free -h || true
