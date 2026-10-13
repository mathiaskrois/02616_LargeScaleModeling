# Why did we expect chunk size 1 to be slow?

The student's observation is reasonable: assigning one row per chunk creates many
small messages. For a 3000-row image, chunk 1 means 3000 chunks; chunk 375 means
only eight. More sends, receives and bookkeeping can make chunk 1 slower when
communication overhead is important.

But fewer messages is only one consideration. Small chunks also distribute the
unequal Mandelbrot row costs finely. Here each row contains 3000 pixels with up
to 100 iterations, so a one-row chunk still contains meaningful computation.
It is not guaranteed to be the slowest configuration.

## What the original heavy plot actually contains

The completed 3000×3000 sweep used **3, 11, 23, 46, 93, 187 and 375 rows**. Its first
point was chunk 3, not chunk 1. Blocking static took 70.26 s at chunk 3, jumped to
265.84 s at chunk 11 and returned to 80.79 s at chunk 375. This is a receive-order
problem, not evidence that sending larger messages is always slower.

In the original version rank zero computes all its chunks before receiving, then
receives all chunks from one worker before moving to the next. Workers can be
blocked in Send while they still have computation left. Small messages can hide
some of this through MPI buffering/progress; intermediate messages expose it.
At chunk 375 each static rank has just one chunk, so waiting to send cannot delay
any later chunk calculation. Unequal row costs still affect the final runtime.

The completed 3000×3000 diagnostic follow-up supports this explanation: at chunk
11 the original took 246.60 s, with a median maximum-worker Send duration of
215.20 s. Receiving after each cyclic round reduced the median to 35.48 s.
Those were profiled versions on Xeon Gold CPUs; they are supporting evidence,
not substituted data for the earlier Xeon E5 sweep.

## Fair comparison of the two versions

The new comparison runs both versions fresh, sequentially on the same two hosts,
with the same CPU model, software stack, image, limits and eight bound ranks.
Both use blocking Send/Recv and identical pixel arithmetic and cyclic assignment.
The change is when rank zero receives results. Neither version includes the timing
instrumentation used in the previous diagnostic follow-up.

- Original: `Mandelbrot_blocking_static_legacy.py`.
- Fixed receive order: `Mandelbrot_blocking_static.py`.
- Image: **3000×3000**, default limits, **100 iterations**.
- Chunk: **1 only**. No other chunk sizes are rerun.
- Five repetitions per version: **10 measured launches**.
- Five shuffled rounds, seed 261613; one allocation, no nested jobs.
- Exact serial-reference checks precede timing; all logs and sources are archived.

Chunk 1 is an explicit addition to the heavy grid to test the student's
expectation. Other points retain the completed heavier sweep's measurements. Historical
measurements and plots remain unchanged. No results from the discarded 1000×1000
chunk-1 retest are used.

The completed report will compare the original and fixed versions only at chunk 1,
show their ratio and min–max ranges, and retain the historical original curve as
context. This does not establish how chunk 1 compares with other chunks in the
fixed implementation; that would require measurements the student has not requested.

Submit only `heavy_chunks_job.sh` from Week05. It requests eight slots on two hosts,
four per host, for 12 hours. The CPU model is pinned to Xeon E5-2660 v3 to match the
original heavy suite; probes validate the model and unique physical cores. Open MPI
5.0.10 is used for both versions. Conservative pilots guard the remaining budget.
Analysis and GitHub publication run automatically after all ten measurements succeed.
