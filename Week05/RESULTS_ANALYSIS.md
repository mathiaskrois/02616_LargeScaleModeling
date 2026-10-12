# Mandelbrot runtime analysis

## Data and method

Completed job **29618553** contains 240 successful measurements: four implementations, **80 distinct configurations** across three sweeps, and three repetitions per configuration. All comparisons below use medians of complete mpirun launches, including Python startup and MPI initialization/finalization. Queue time, plotting and publication are excluded.

CPU: **Intel(R) Xeon(R) CPU E5-2660 v3 @ 2.60GHz**; Open MPI 5.0.10; mpi4py 4.1.1; NumPy 2.4.1. Eight total ranks were bound to separate physical cores. Runs were sequential and shuffled within each repetition round on one allocation with seed 261605. Hosts were shared with other jobs.

All plots below have observed min–max error bars. These are ranges of three samples, not confidence intervals. The original figures are archived alongside the revised plots; raw measurements and source snapshots are unchanged.

## Main result: blocking static develops a pronounced slowdown

At 6000×6000, blocking static takes **1052.08 s**, compared with **152.76 s** for nonblocking static, **148.52 s** for blocking dynamic, and **147.08 s** for nonblocking dynamic. The fastest observed median is 7.15× faster than blocking static. Differences among the other three versions are much smaller and do not establish a reliable universal winner.

The most striking transition is between 2963×2963 and 3559×3559: blocking static increases from **66.55 to 386.46 s** (5.81×), while pixel area increases by only 44.3%. Nonblocking static increases from 35.88 to 52.29 s. This abrupt jump cannot be explained by pixel count alone.

In blocking static, rank zero computes all its assigned chunks before receiving. It then collects all chunks from worker one, then worker two, and so on. Workers call blocking Send after every chunk; delayed receiving can stop a worker from computing its next chunk. Nonblocking static posts sends and retains their buffers, allowing its computation loop to continue.

The jump is consistent with a message-buffering/protocol transition that exposes this receive order. At 3000 columns, a full 10-row float64 result is 240,000 bytes; 11 rows is 264,000 bytes. In the area sweep at chunk 10, 2963 columns gives 237,040 bytes and 3559 gives 284,720 bytes. The two observed slowdowns bracket similar message sizes. This is a hypothesis supported by patterns and source code, not a measured protocol threshold.

The MPI standard permits standard sends to block until a matching receive starts when buffering is unavailable. [MPI communication semantics](https://www.mpi-forum.org/docs/mpi-5.0/mpi50-report/node70.htm). Time-resolved MPI diagnostics are needed to establish the mechanism in this run.

## Host placement at fixed rank count

With 3000×3000 images and 10-row chunks, spreading eight ranks across more hosts gives no consistent benefit. Nonblocking static grows from 35.52 s on two hosts to 39.88 s on eight (+12.3%); dynamic blocking changes from 39.38 to 38.63 s (−1.9%); dynamic nonblocking changes from 37.80 to 38.12 s (+0.9%). Blocking static improves by 4.5%, but its ranges are wide.

These are **placement tests**, not processor-count scaling: every run has eight ranks. Additional hosts do not add computing ranks. The initial sweep does not include a single host; the diagnostic follow-up supplies that assignment requirement.

## Chunk size and load balance

For nonblocking static and both dynamic versions, chunks from 3 to 46 rows give roughly 36–40 s. At 187 rows the medians rise to 46–49 s; at 375 rows they reach 77–79 s. Nonblocking static has its smallest median at 46 rows (36.22 s), but several small chunks are close enough that the experiment does not identify a precise optimum.

A 3000-row image with 375-row chunks contains only eight chunks. Mandelbrot rows have different computational cost, so coarse partitioning limits load balancing. Static scheduling assigns one chunk per rank; dynamic scheduling has seven computing workers and eight chunks. Both can finish with workers idle while expensive chunks remain.

Blocking static is non-monotonic: 3-row chunks take 70.26 s, intermediate chunks 11–187 take 208–272 s, and 375-row chunks take 80.79 s. At the largest chunk there is only one chunk per static rank, so workers cannot lose progress on later chunks while their first Send waits. This receive-order explanation remains to be tested with profiling.

## Blocking versus nonblocking dynamic communication

The dynamic implementations perform similarly. The nonblocking version immediately waits for many requests, including individual work sends and result receives, so using Isend/Irecv does not automatically create extensive overlap. The rank-zero manager also means dynamic runs have seven computing workers, while static runs have eight. Comparisons combine scheduling and communication differences.

## Variability and limitations

The median observed min–max range across the 80 configurations is **3.87% of the configuration median**; the largest is 29.90%. With only three repetitions, small median differences should not be treated as statistical significance. The sevenfold large-image slowdown and repeated threshold-like transitions are much more substantial than typical variation.

The original suite confirms successful execution and placement, but did not compare complete output arrays against the serial reference for every large image. The follow-up adds exact equality checks on representative small, rectangular and large-message cases before measurements.

Earlier job 29611697 used smaller images and a different software stack. Treat it as historical context; cross-job changes cannot be attributed solely to image size.

## Focused follow-up

[FOLLOWUP.md](FOLLOWUP.md) defines 175 measurements with five repetitions: chunks 8–12 on two hosts, plus one versus two hosts at chunk 10, using five implementations. Two blocking-static variants record per-rank computation, Send/Recv and final-barrier durations. The interleaved variant receives after each round of cyclic chunks and preserves blocking communication and arithmetic. Its result report will state observed ratios and timing diagnostics without assuming the proposed improvement succeeds.

## Complete median and range tables

### Nodes

| Physical hosts | Implementation | Median s | Min s | Max s |
|---:|---|---:|---:|---:|
| 2 | Blocking dynamic | 39.38 | 38.87 | 40.07 |
| 2 | Nonblocking dynamic | 37.80 | 37.32 | 38.57 |
| 2 | Blocking static | 67.23 | 66.82 | 69.67 |
| 2 | Nonblocking static | 35.52 | 35.32 | 36.54 |
| 4 | Blocking dynamic | 39.43 | 38.48 | 41.38 |
| 4 | Nonblocking dynamic | 39.43 | 38.62 | 40.14 |
| 4 | Blocking static | 65.95 | 61.97 | 66.40 |
| 4 | Nonblocking static | 37.97 | 37.06 | 42.09 |
| 8 | Blocking dynamic | 38.63 | 38.08 | 39.13 |
| 8 | Nonblocking dynamic | 38.12 | 37.58 | 38.52 |
| 8 | Blocking static | 64.18 | 60.57 | 74.08 |
| 8 | Nonblocking static | 39.88 | 36.73 | 40.33 |

![nodes median and ranges](results/job_29618553/figures/nodes.png)

### Chunk Size

| Chunk rows | Implementation | Median s | Min s | Max s |
|---:|---|---:|---:|---:|
| 3 | Blocking dynamic | 38.03 | 37.98 | 39.05 |
| 3 | Nonblocking dynamic | 38.62 | 37.63 | 39.77 |
| 3 | Blocking static | 70.26 | 68.22 | 70.90 |
| 3 | Nonblocking static | 37.59 | 36.52 | 38.47 |
| 11 | Blocking dynamic | 38.18 | 37.56 | 38.63 |
| 11 | Nonblocking dynamic | 37.92 | 37.83 | 38.66 |
| 11 | Blocking static | 265.84 | 258.38 | 268.39 |
| 11 | Nonblocking static | 37.02 | 34.92 | 37.92 |
| 23 | Blocking dynamic | 38.14 | 37.13 | 39.39 |
| 23 | Nonblocking dynamic | 37.98 | 37.18 | 38.05 |
| 23 | Blocking static | 267.32 | 260.35 | 271.91 |
| 23 | Nonblocking static | 36.42 | 36.27 | 36.99 |
| 46 | Blocking dynamic | 40.28 | 38.36 | 40.73 |
| 46 | Nonblocking dynamic | 39.64 | 38.63 | 42.73 |
| 46 | Blocking static | 272.01 | 260.24 | 279.77 |
| 46 | Nonblocking static | 36.22 | 36.02 | 39.93 |
| 93 | Blocking dynamic | 41.11 | 40.93 | 41.79 |
| 93 | Nonblocking dynamic | 41.28 | 40.06 | 46.13 |
| 93 | Blocking static | 248.85 | 243.09 | 277.58 |
| 93 | Nonblocking static | 37.99 | 37.80 | 38.58 |
| 187 | Blocking dynamic | 48.83 | 46.17 | 49.04 |
| 187 | Nonblocking dynamic | 47.44 | 47.08 | 48.40 |
| 187 | Blocking static | 207.82 | 207.13 | 212.61 |
| 187 | Nonblocking static | 45.93 | 44.54 | 52.24 |
| 375 | Blocking dynamic | 77.05 | 76.24 | 82.69 |
| 375 | Nonblocking dynamic | 78.13 | 77.47 | 79.44 |
| 375 | Blocking static | 80.80 | 78.10 | 102.26 |
| 375 | Nonblocking static | 79.20 | 78.45 | 83.74 |

![chunk_size median and ranges](results/job_29618553/figures/chunk_size.png)

### Image Area

| Image side (actual area is side²) | Implementation | Median s | Min s | Max s |
|---:|---|---:|---:|---:|
| 1000 | Blocking dynamic | 5.12 | 5.08 | 5.18 |
| 1000 | Nonblocking dynamic | 5.18 | 5.12 | 5.33 |
| 1000 | Blocking static | 5.97 | 5.93 | 5.98 |
| 1000 | Nonblocking static | 5.18 | 5.13 | 5.27 |
| 2211 | Blocking dynamic | 21.20 | 21.15 | 21.35 |
| 2211 | Nonblocking dynamic | 21.19 | 21.15 | 21.65 |
| 2211 | Blocking static | 38.57 | 38.24 | 40.74 |
| 2211 | Nonblocking static | 20.60 | 19.40 | 21.30 |
| 2963 | Blocking dynamic | 37.22 | 36.93 | 37.26 |
| 2963 | Nonblocking dynamic | 36.59 | 36.37 | 37.97 |
| 2963 | Blocking static | 66.55 | 64.58 | 67.78 |
| 2963 | Nonblocking static | 35.88 | 35.73 | 36.87 |
| 3559 | Blocking dynamic | 53.99 | 52.40 | 54.97 |
| 3559 | Nonblocking dynamic | 52.40 | 51.55 | 54.55 |
| 3559 | Blocking static | 386.46 | 366.43 | 389.90 |
| 3559 | Nonblocking static | 52.29 | 51.45 | 57.68 |
| 4069 | Blocking dynamic | 69.76 | 69.44 | 69.88 |
| 4069 | Nonblocking dynamic | 69.63 | 68.80 | 69.88 |
| 4069 | Blocking static | 484.27 | 479.19 | 497.41 |
| 4069 | Nonblocking static | 64.21 | 63.28 | 71.34 |
| 4522 | Blocking dynamic | 86.89 | 82.49 | 87.45 |
| 4522 | Nonblocking dynamic | 86.00 | 84.28 | 86.05 |
| 4522 | Blocking static | 597.33 | 588.92 | 599.17 |
| 4522 | Nonblocking static | 87.46 | 82.37 | 87.54 |
| 4933 | Blocking dynamic | 100.12 | 99.62 | 100.26 |
| 4933 | Nonblocking dynamic | 100.73 | 99.76 | 101.55 |
| 4933 | Blocking static | 717.71 | 716.96 | 724.97 |
| 4933 | Nonblocking static | 99.74 | 99.04 | 103.97 |
| 5312 | Blocking dynamic | 115.06 | 113.15 | 115.98 |
| 5312 | Nonblocking dynamic | 119.97 | 117.89 | 121.90 |
| 5312 | Blocking static | 837.63 | 815.18 | 846.07 |
| 5312 | Nonblocking static | 114.08 | 110.65 | 118.34 |
| 5667 | Blocking dynamic | 133.72 | 131.15 | 133.81 |
| 5667 | Nonblocking dynamic | 141.43 | 135.77 | 141.49 |
| 5667 | Blocking static | 953.03 | 912.68 | 958.22 |
| 5667 | Nonblocking static | 127.36 | 125.40 | 137.51 |
| 6000 | Blocking dynamic | 148.52 | 148.44 | 149.13 |
| 6000 | Nonblocking dynamic | 147.08 | 146.56 | 149.64 |
| 6000 | Blocking static | 1052.08 | 1047.60 | 1055.07 |
| 6000 | Nonblocking static | 152.76 | 141.98 | 153.63 |

![image_area median and ranges](results/job_29618553/figures/image_area.png)

