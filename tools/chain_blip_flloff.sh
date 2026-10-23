#!/bin/sh
# Wait for the FIX_LOW_LEVEL ON arm to finish, then launch the OFF arm, so the machine is never idle
# between them (owner's standing rule) and the two arms stay as close together in time as possible.
#
# IT WATCHES THE IDENTITY LINE, NOT THE ARITHMETIC ONE. `procs.py` prints both: "distinct harness runs"
# (how many) and "queue files being run" (which). A gap BETWEEN two races of the same queue reads as zero
# races while the queue is very much still going - that is exactly how tonight's CSP-log roller quit at
# 02:19, one race early. The queue-file line stays populated across that gap. Four consecutive readings of
# "none", 20 s apart, is then ~60-80 s of genuinely nothing, well past any inter-race gap.
V="$(cd "$(dirname "$0")/.." && pwd)"   # derived, never written down
Q="tools/harness_results/batch_20261023_pc1_blip_flloff.txt"
LOG="$V/tools/harness_results/chain_blip_flloff.log"
echo "=== chain armed $(date '+%H:%M:%S'), waiting for the ON arm to end" >> "$LOG"
gone=0
i=0
while [ "$i" -lt 240 ]; do
  i=$((i + 1))
  q=$(python "$V/tools/procs.py" 2>/dev/null | awk '/queue files being run/{print $5}')
  case "$q" in
    none|"") gone=$((gone + 1)) ;;
    *)       gone=0 ;;
  esac
  if [ "$gone" -ge 4 ]; then
    echo "=== ON arm ended; four consecutive 'none' by $(date '+%H:%M:%S'). Launching the OFF arm." >> "$LOG"
    cd "$V" || exit 1
    nohup python tools/batch.py "$Q" >> "$V/tools/harness_results/batch_20261023_pc1_blip_flloff.log" 2>&1 &
    echo "=== OFF arm launched $(date '+%H:%M:%S') (pid $!)" >> "$LOG"
    exit 0
  fi
  sleep 20
done
echo "=== chain GAVE UP at $(date '+%H:%M:%S') without launching: the ON arm was still going after 80 min" >> "$LOG"
