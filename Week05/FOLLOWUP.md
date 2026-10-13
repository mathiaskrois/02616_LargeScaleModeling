# Diagnostic follow-up

This suite addresses three questions raised by completed job 29618553:

1. Does the blocking-static slowdown appear between chunks 8 and 12, and is time inside MPI Send responsible?
2. Does collecting blocking-static results after each round of chunks reduce the slowdown?
3. How do one and two physical hosts compare with the same eight ranks?

## Grid and allocation

| Experiment | Values | Fixed settings | Measured runs |
|---|---|---|---:|
| Threshold | Chunks 8, 9, 10, 11, 12 | 3000×3000; 8 ranks on 2 hosts | 125 |
| One versus two hosts | 1, 2 hosts | 3000×3000; 8 ranks; chunk 10 | 50 |

Five implementations and five repetitions per configuration yield **175 measurements**.
The original four source files are unchanged. Blocking static is measured through
`Mandelbrot_static_profiled.py`, preserving its arithmetic, cyclic row assignment,
blocking sends and original receive order while recording phase durations.
`Mandelbrot_blocking_static_interleaved.py` uses the same calculation and assignment,
but rank zero receives each round's chunks before computing the next round.
It uses blocking Send and Recv throughout. This changes synchronization and receive
order; it does not introduce dynamic scheduling or nonblocking communication.

All images use limits -2.2:0.75 and -1.3:1.3 and 100 iterations. A repetition round
contains every configuration once and is shuffled with recorded seed 261612.
Runs are sequential in one 12-hour allocation: **16 slots, eight each on two hosts**,
1 GB per slot. The hpc queue selects a common CPU model; rank probes verify exact
model equality and Open MPI 5.0.10. One-host tests use eight allocated physical
cores on the first host; two-host tests use four cores on each. Rank zero stays
on the first host. Shared hosts can introduce variation.

## Verification and timing

Before pilots, the batch runs unit/acceptance checks, probes both placements and
repeats the two-host launch ten times. It then compares six entry points (including
the uninstrumented blocking-static original) on both placements against the
unmodified course serial reference. Three cases cover partial final chunks,
idle ranks, chunks larger than the image, rectangular images and a >256 KiB chunk.
All **36 comparisons require exact image equality** before measurements begin.

Pilots cover all five versions, both placements, 100×100 and 3000×3000 images,
and chunks 8 and 12. The suite estimate uses the slower 3000×3000 pilot for each
implementation and placement, with a factor-of-two allowance. It stops before
measurements if this exceeds the remaining budget, reserving 15 minutes for
analysis and publication. Estimates are conservative guards, not guarantees.

Complete launch-to-exit runtime is measured with a monotonic clock. Every attempt
gets stdout/stderr logs; each measured row is flushed and synced immediately.
Failures stop the suite. Profiles are archived for both blocking-static versions:
computation, time inside Send and Recv, final barrier, computed rows and call counts
for every rank. MPI call durations include waiting and transfer, not pure network
time. The profiled versions include diagnostics and output overhead; comparison
with the historical uninstrumented suite must acknowledge this difference.

## Running and publication

From Week05:

```sh
python3 run_followup.py --dry-run
export EXPERIMENT_WORK_DIR="$PWD"
bsub < followup_job.sh
```

Only submit the batch entry point. Its runner uses mpirun within that allocation;
there are no nested jobs. Results go to `results/followup_job_JOBID/`.
`analyse_followup.py` validates all 175 rows and 70 profiles, then produces three
PNG/PDF figures and `SUMMARY.md` with timing tables, receive-order comparison,
rank diagnostics and one/two-host ratios. Error bars represent observed min–max,
not confidence intervals. Missing, duplicate or failed runs cannot produce a
completed report.

`publish_results.py` validates again, publishes the job directory, and embeds the
new figures and report links in the README while preserving the heavy-suite plots.
It uses an isolated checkout and never force-pushes. Authentication remains signed
in. The batch exits successfully only after publication succeeds. If publication
fails, saved measurements remain intact and the same publisher can be rerun.

```sh
python3 analyse_followup.py results/followup_job_JOBID
python3 publish_results.py results/followup_job_JOBID
```

## Report use

Read [RESULTS_ANALYSIS.md](RESULTS_ANALYSIS.md) for the established conclusions from
the completed heavy suite. The new job's SUMMARY.md supplies the follow-up evidence.
Do not claim a precise MPI buffering threshold without tracing. A reduction in
Send time and total runtime would support the receive-order explanation; no
reduction would require revisiting it. Distinguish fixed-rank host placement from
scaling with additional ranks. Interpret small performance differences together
with repetition ranges, not only which median is smallest.
