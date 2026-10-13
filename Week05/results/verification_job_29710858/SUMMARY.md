# Correctness and five-version benchmark

Job **29710858**, after full sweep **29706381**. CPU: Intel(R) Xeon(R) CPU E5-2650 v4 @ 2.20GHz.

## Correctness

All **72** implementation/image/chunk combinations passed. Each assembled image and each contiguous row chunk was compared with the original serial Mandelbrot.py using np.array_equal. Shape and dtype also match.
The checks cover all ten area-sweep sizes, the 3000×3000 baseline, and all seven heavy chunk sizes. Checks use eight MPI ranks on two hosts; the four/eight-host timing placements are not repeated here. Source hashes match the running full suite.
All fifteen benchmark outputs also passed exact image equality and 300 separate 10-row chunk comparisons. Compressed reference/output arrays, hashes, logs and per-case evidence are archived.

```python
assert np.array_equal(image, reference)
for start in range(0, image.shape[0], chunk_size):
    assert np.array_equal(image[start:start + chunk_size],
                          reference[start:start + chunk_size])
```

Exact equality is appropriate because these versions preserve the same per-pixel arithmetic, coordinates and 100-iteration limit. The original convention of leaving non-escaping pixels at zero is preserved.

## Compact benchmark overview

3000×3000 pixels, chunk 10, default limits, 100 iterations; serial uses one rank, MPI versions use eight ranks on the same two hosts. All fifteen runs execute sequentially with three shuffled repetition rounds, seed 261614.

<!-- overview-table:start -->
| Version | Ranks | Median (s) | Min–max (s) | Speedup | Exact image/chunks |
|---|---:|---:|---|---:|---|
| Original Mandelbrot.py | 1 | 310.794 | 301.691–329.171 | 1.00× | 3/3 passed |
| Blocking static | 8 | 39.964 | 38.814–48.274 | 7.78× | 3/3 passed |
| Nonblocking static | 8 | 38.667 | 38.414–42.916 | 8.04× | 3/3 passed |
| Blocking dynamic | 8 | 42.018 | 40.967–42.971 | 7.40× | 3/3 passed |
| Nonblocking dynamic | 8 | 42.419 | 41.521–42.770 | 7.33× | 3/3 passed |
<!-- overview-table:end -->

Median complete launch-to-exit runtimes include MPI/Python startup and final array export. Serial benchmark runs execute the original source statements through the end of calculation and omit its plotting-only section, matching the MPI programs. Reference-generation runs still execute the complete original script. Speedups compare complete calculation/export workflows, not isolated arithmetic kernels. Array comparison and compression happen after timing.
These are new matched benchmark measurements for all five versions; timings are not mixed across allocations with the 240-run sweep. Shared hosts can still introduce variation; min–max ranges are not confidence intervals.

## Full-image correctness evidence

| Implementation | Image | Chunk rows | Image equal | Chunks checked |
|---|---|---:|---|---:|
| Blocking static | 1000×1000 | 10 | True | 100 |
| Nonblocking static | 1000×1000 | 10 | True | 100 |
| Blocking dynamic | 1000×1000 | 10 | True | 100 |
| Nonblocking dynamic | 1000×1000 | 10 | True | 100 |
| Blocking static | 2211×2211 | 10 | True | 222 |
| Nonblocking static | 2211×2211 | 10 | True | 222 |
| Blocking dynamic | 2211×2211 | 10 | True | 222 |
| Nonblocking dynamic | 2211×2211 | 10 | True | 222 |
| Blocking static | 2963×2963 | 10 | True | 297 |
| Nonblocking static | 2963×2963 | 10 | True | 297 |
| Blocking dynamic | 2963×2963 | 10 | True | 297 |
| Nonblocking dynamic | 2963×2963 | 10 | True | 297 |
| Blocking static | 3000×3000 | 3 | True | 1000 |
| Nonblocking static | 3000×3000 | 3 | True | 1000 |
| Blocking dynamic | 3000×3000 | 3 | True | 1000 |
| Nonblocking dynamic | 3000×3000 | 3 | True | 1000 |
| Blocking static | 3000×3000 | 10 | True | 300 |
| Nonblocking static | 3000×3000 | 10 | True | 300 |
| Blocking dynamic | 3000×3000 | 10 | True | 300 |
| Nonblocking dynamic | 3000×3000 | 10 | True | 300 |
| Blocking static | 3000×3000 | 11 | True | 273 |
| Nonblocking static | 3000×3000 | 11 | True | 273 |
| Blocking dynamic | 3000×3000 | 11 | True | 273 |
| Nonblocking dynamic | 3000×3000 | 11 | True | 273 |
| Blocking static | 3000×3000 | 23 | True | 131 |
| Nonblocking static | 3000×3000 | 23 | True | 131 |
| Blocking dynamic | 3000×3000 | 23 | True | 131 |
| Nonblocking dynamic | 3000×3000 | 23 | True | 131 |
| Blocking static | 3000×3000 | 46 | True | 66 |
| Nonblocking static | 3000×3000 | 46 | True | 66 |
| Blocking dynamic | 3000×3000 | 46 | True | 66 |
| Nonblocking dynamic | 3000×3000 | 46 | True | 66 |
| Blocking static | 3000×3000 | 93 | True | 33 |
| Nonblocking static | 3000×3000 | 93 | True | 33 |
| Blocking dynamic | 3000×3000 | 93 | True | 33 |
| Nonblocking dynamic | 3000×3000 | 93 | True | 33 |
| Blocking static | 3000×3000 | 187 | True | 17 |
| Nonblocking static | 3000×3000 | 187 | True | 17 |
| Blocking dynamic | 3000×3000 | 187 | True | 17 |
| Nonblocking dynamic | 3000×3000 | 187 | True | 17 |
| Blocking static | 3000×3000 | 375 | True | 8 |
| Nonblocking static | 3000×3000 | 375 | True | 8 |
| Blocking dynamic | 3000×3000 | 375 | True | 8 |
| Nonblocking dynamic | 3000×3000 | 375 | True | 8 |
| Blocking static | 3559×3559 | 10 | True | 356 |
| Nonblocking static | 3559×3559 | 10 | True | 356 |
| Blocking dynamic | 3559×3559 | 10 | True | 356 |
| Nonblocking dynamic | 3559×3559 | 10 | True | 356 |
| Blocking static | 4069×4069 | 10 | True | 407 |
| Nonblocking static | 4069×4069 | 10 | True | 407 |
| Blocking dynamic | 4069×4069 | 10 | True | 407 |
| Nonblocking dynamic | 4069×4069 | 10 | True | 407 |
| Blocking static | 4522×4522 | 10 | True | 453 |
| Nonblocking static | 4522×4522 | 10 | True | 453 |
| Blocking dynamic | 4522×4522 | 10 | True | 453 |
| Nonblocking dynamic | 4522×4522 | 10 | True | 453 |
| Blocking static | 4933×4933 | 10 | True | 494 |
| Nonblocking static | 4933×4933 | 10 | True | 494 |
| Blocking dynamic | 4933×4933 | 10 | True | 494 |
| Nonblocking dynamic | 4933×4933 | 10 | True | 494 |
| Blocking static | 5312×5312 | 10 | True | 532 |
| Nonblocking static | 5312×5312 | 10 | True | 532 |
| Blocking dynamic | 5312×5312 | 10 | True | 532 |
| Nonblocking dynamic | 5312×5312 | 10 | True | 532 |
| Blocking static | 5667×5667 | 10 | True | 567 |
| Nonblocking static | 5667×5667 | 10 | True | 567 |
| Blocking dynamic | 5667×5667 | 10 | True | 567 |
| Nonblocking dynamic | 5667×5667 | 10 | True | 567 |
| Blocking static | 6000×6000 | 10 | True | 600 |
| Nonblocking static | 6000×6000 | 10 | True | 600 |
| Blocking dynamic | 6000×6000 | 10 | True | 600 |
| Nonblocking dynamic | 6000×6000 | 10 | True | 600 |
