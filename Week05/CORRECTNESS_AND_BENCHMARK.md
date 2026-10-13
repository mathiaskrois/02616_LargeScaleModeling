# Correctness evidence and the five-version overview

## Checks already passed in the current full suite

Job 29706381 compared all four final MPI images against the original serial
`Mandelbrot.py` with `np.array_equal` before measuring performance. All 12 checks
passed: four implementations on these three cases:

| Image | Chunk | Purpose |
|---|---:|---|
| 53×47 | 1 | Uneven final rank round and rectangular image |
| 19×23 | 125 | Oversized chunk and idle ranks |
| 67×1100 | 31 | Partial last chunk and a worker result larger than 256 KiB |

The reference is the original source, executed through `runpy`; the wrapper
exports rank zero's final image. No alternative Mandelbrot formula is used.
The assembled image is compared in its native array orientation, before plotting.
The serial convention of leaving non-escaping pixels at zero is preserved.

## Full-grid correctness coverage

The follow-on job depends on successful completion of the full suite. It validates
18 distinct image/chunk settings, each with four implementations: **72 checks**.
These cover all ten image-area sizes, the 3000×3000 baseline at chunk 10, and all
seven heavier chunk sizes. Each uses eight ranks on two hosts. The timing suite's
four/eight-host placements are not rerun for numerical validation.

For each setting it first executes the original serial source and retains the
reference array. The serial reference is reused only for the same dimensions;
its chunk argument is unused in the original computation. Then every implementation
must pass both final-image and contiguous row-chunk checks:

```python
assert np.array_equal(image, reference)
for start in range(0, image.shape[0], chunk_size):
    assert np.array_equal(image[start:start + chunk_size],
                          reference[start:start + chunk_size])
```

Shape and dtype must also match. Equality is exact, without a numerical tolerance,
because the implementations use the same coordinates and per-pixel arithmetic.
Checking the final image detects incorrect chunk assembly; checking slices records
explicit evidence for every chunk, including a partial final chunk.

Source hashes must match the archived source of job 29706381. Individual outcomes,
chunk counts, array hashes, compressed reference/output arrays and process logs
are saved. A failure stops the job and cannot produce a completed benchmark table.

## Compact five-version benchmark

After validation, benchmark all five versions on the same reserved two hosts,
using the CPU model and module versions of the current suite:

- Original serial Mandelbrot.py: one rank.
- Blocking static, nonblocking static, blocking dynamic, nonblocking dynamic:
  eight ranks, four per host.
- 3000×3000 pixels, chunk 10, default limits, 100 iterations.
- Three shuffled repetition rounds, seed 261614: **15 measured launches**.

Each benchmark output is again compared with the serial reference, including all
300 row chunks. The overview reports median complete runtime, observed min–max,
serial-relative speedup, rank count and 3/3 correctness status.

All versions run through the same image-export wrapper. Timings include MPI/Python
startup and NumPy-array export. During serial benchmark runs only, the wrapper executes the original source
statements through calculation and omits its plotting-only section, matching the
MPI programs. Reference generation still executes the complete serial program.
The table compares complete calculation/export workflows, not isolated numerical kernels. Array comparisons
and compression take place after the timed process exits.

The table uses fresh matched measurements for all five versions; it does not mix
serial timings from one allocation with parallel timings from the earlier sweep.
Hosts are shared with other jobs, and ranges are not statistical confidence intervals.

## Automatic execution and publication

Submit only `verify_benchmark_job.sh`, with optional `PARENT_RESULTS_DIR` pointing at the
completed full-suite directory. If the scheduler drops that environment variable,
the script defaults to the saved `results/job_29706381` directory in this checkout. Its LSF dependency waits for job 29706381, preventing
these benchmarks from overlapping the current suite. The job reserves eight slots
on two Xeon E5-2650 v4 hosts for six hours, with 2 GB per reserved slot
for large reference arrays and serial plotting. It runs sequentially, without nested jobs.

The completed results include SUMMARY.md, a five-row table, correctness evidence,
and a PNG/PDF overview figure. The publisher embeds the table in the root README
while preserving the full-suite plots, and pushes everything automatically.
