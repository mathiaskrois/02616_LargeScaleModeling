# Follow-up measurements

175 successful complete launches; 35 configurations; median of five repetitions.
The error bars show the full observed min–max range, not confidence intervals.

## Runtime comparisons

| Experiment | Implementation | Hosts | Chunk rows | Median s | Min s | Max s |
|---|---|---:|---:|---:|---:|---:|
| one_vs_two | Blocking dynamic | 1 | 10 | 36.313 | 35.910 | 36.811 |
| one_vs_two | Blocking dynamic | 2 | 10 | 36.080 | 35.838 | 37.438 |
| one_vs_two | Nonblocking dynamic | 1 | 10 | 36.113 | 35.915 | 36.964 |
| one_vs_two | Nonblocking dynamic | 2 | 10 | 36.640 | 36.037 | 37.131 |
| one_vs_two | Blocking static (profiled) | 1 | 10 | 63.993 | 62.690 | 65.595 |
| one_vs_two | Blocking static (profiled) | 2 | 10 | 64.212 | 63.509 | 64.828 |
| one_vs_two | Blocking static: interleaved rounds | 1 | 10 | 35.109 | 34.510 | 37.211 |
| one_vs_two | Blocking static: interleaved rounds | 2 | 10 | 35.185 | 34.484 | 35.327 |
| one_vs_two | Nonblocking static | 1 | 10 | 33.358 | 32.208 | 33.958 |
| one_vs_two | Nonblocking static | 2 | 10 | 33.529 | 32.573 | 34.021 |
| threshold | Blocking dynamic | 2 | 8 | 36.678 | 36.478 | 37.337 |
| threshold | Blocking dynamic | 2 | 9 | 36.485 | 36.038 | 36.683 |
| threshold | Blocking dynamic | 2 | 10 | 37.035 | 36.838 | 37.287 |
| threshold | Blocking dynamic | 2 | 11 | 36.785 | 36.287 | 37.088 |
| threshold | Blocking dynamic | 2 | 12 | 36.336 | 36.181 | 37.082 |
| threshold | Nonblocking dynamic | 2 | 8 | 36.639 | 36.335 | 36.734 |
| threshold | Nonblocking dynamic | 2 | 9 | 36.340 | 35.781 | 36.784 |
| threshold | Nonblocking dynamic | 2 | 10 | 36.486 | 35.933 | 37.694 |
| threshold | Nonblocking dynamic | 2 | 11 | 36.743 | 36.328 | 36.988 |
| threshold | Nonblocking dynamic | 2 | 12 | 37.040 | 36.833 | 37.243 |
| threshold | Blocking static (profiled) | 2 | 8 | 63.865 | 59.771 | 64.575 |
| threshold | Blocking static (profiled) | 2 | 9 | 63.571 | 61.511 | 64.886 |
| threshold | Blocking static (profiled) | 2 | 10 | 63.432 | 61.165 | 64.877 |
| threshold | Blocking static (profiled) | 2 | 11 | 246.602 | 243.602 | 248.329 |
| threshold | Blocking static (profiled) | 2 | 12 | 243.650 | 243.494 | 249.062 |
| threshold | Blocking static: interleaved rounds | 2 | 8 | 34.484 | 34.132 | 35.270 |
| threshold | Blocking static: interleaved rounds | 2 | 9 | 35.036 | 34.415 | 35.533 |
| threshold | Blocking static: interleaved rounds | 2 | 10 | 34.629 | 33.477 | 35.785 |
| threshold | Blocking static: interleaved rounds | 2 | 11 | 35.479 | 34.687 | 36.385 |
| threshold | Blocking static: interleaved rounds | 2 | 12 | 35.626 | 35.126 | 36.929 |
| threshold | Nonblocking static | 2 | 8 | 33.324 | 32.868 | 34.481 |
| threshold | Nonblocking static | 2 | 9 | 32.876 | 32.320 | 34.283 |
| threshold | Nonblocking static | 2 | 10 | 33.022 | 32.720 | 34.526 |
| threshold | Nonblocking static | 2 | 11 | 33.324 | 32.767 | 34.833 |
| threshold | Nonblocking static | 2 | 12 | 33.627 | 33.371 | 35.135 |

## Communication diagnostics

| Version | Chunk rows | Median of maximum worker Send time (s) |
|---|---:|---:|
| Blocking static (profiled) | 8 | 29.670 |
| Blocking static (profiled) | 9 | 30.142 |
| Blocking static (profiled) | 10 | 30.295 |
| Blocking static (profiled) | 11 | 215.199 |
| Blocking static (profiled) | 12 | 212.131 |
| Blocking static: interleaved rounds | 8 | 0.038 |
| Blocking static: interleaved rounds | 9 | 0.853 |
| Blocking static: interleaved rounds | 10 | 0.971 |
| Blocking static: interleaved rounds | 11 | 4.478 |
| Blocking static: interleaved rounds | 12 | 4.628 |

## Interpretation

The interleaved variant changes receive order and how often rank zero receives; row assignment and pixel arithmetic are unchanged.
- Chunk 8: original/interleaved runtime ratio **1.85×**.
- Chunk 9: original/interleaved runtime ratio **1.81×**.
- Chunk 10: original/interleaved runtime ratio **1.83×**.
- Chunk 11: original/interleaved runtime ratio **6.95×**.
- Chunk 12: original/interleaved runtime ratio **6.84×**.

The following ratios compare the same eight ranks and image size on one versus two hosts. A ratio above one means two hosts were faster:
- Blocking static (profiled): one-host/two-host ratio **1.00×**.
- Nonblocking static: one-host/two-host ratio **0.99×**.
- Blocking dynamic: one-host/two-host ratio **1.01×**.
- Nonblocking dynamic: one-host/two-host ratio **0.99×**.
- Blocking static: interleaved rounds: one-host/two-host ratio **1.00×**.

## Limits of interpretation

All runs use one allocation, one CPU model, explicit core binding and sequential launches. Hosts remain shared with other jobs. Five repetitions quantify observed spread but do not establish statistical significance.
Static blocking and its interleaved variant include timing instrumentation, a final barrier and profile output. The original four source files are preserved. Compare the variants within this suite; their complete runtimes are not identical measurement protocols to the historical suite.
Time inside MPI calls includes waiting and communication; it is not pure network transfer time. The stacked plot sums medians of separate phases and is illustrative, not the median total runtime.
A jump in Send time supports the receive-order explanation, but the specific MPI buffering/protocol threshold still requires MPI tracing.
Output was checked for exact equality with the serial course reference on three cases and both placements before measurement. Timing success alone is not a large-image output comparison.

## Figures

![threshold](figures/threshold.png)
[PDF](figures/threshold.pdf)

![one_vs_two](figures/one_vs_two.png)
[PDF](figures/one_vs_two.pdf)

![rank_timings](figures/rank_timings.png)
[PDF](figures/rank_timings.pdf)

