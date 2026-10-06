# Mandelbrot runtime experiments

The current configuration is the heavier follow-up suite. The completed initial
run remains in `results/job_29611697/` with its original configuration, sources,
240 measurements and figures. The follow-up must be pushed to GitHub before
submitting a new HPC job. Local acceptance checks do not launch measurements.

## Current grid

| Experiment | Values | Fixed settings |
|---|---|---|
| Physical nodes | 2, 4, 8 | 8 ranks; 3000×3000 pixels; chunk size 10 |
| Chunk size (rows) | 3, 11, 23, 46, 93, 187, 375 | 8 ranks on the first 2 hosts; 3000×3000 pixels |
| Image side (pixels) | 1000, 2211, 2963, 3559, 4069, 4522, 4933, 5312, 5667, 6000 | 8 ranks on the first 2 hosts; chunk size 10 |

The node/chunk image has 9,000,000 pixels, nine times the initial 1000×1000 image.
The largest area image has 36,000,000 pixels, nine times the initial 2000×2000
maximum. Limits remain `-2.2:0.75` and `-1.3:1.3`, with 100 iterations. Each of
four implementations runs every configuration three times, giving 240 measured
runs. Configurations are shuffled in each repetition round using seed 261605.

Chunk sizes follow `max(1, floor(N / (8*x)))`, with `N = 3000` and
`x = [125, 32, 16, 8, 4, 2, 1]`. The maximum chunk is 375 rows. Dynamic rank zero
manages work; this does not imply equal work across all eight ranks.

Image target areas are `1,000,000 + i*(36,000,000 - 1,000,000)/9`, for `i = 0..9`.
Sides are rounded square roots. Target and actual areas are saved; actual area
is plotted. Increasing images makes computation heavier and reduces startup's
fraction of complete runtime, but does not guarantee larger performance gaps.

## Allocation and submission

After pushing the updated project, submit one job from Week05:

```sh
python3 -m unittest -v test_experiments
python3 run_experiments.py --dry-run
export EXPERIMENT_WORK_DIR="$PWD"
bsub < experiments_job.sh
```

The batch script reserves 32 slots across eight hosts of one CPU model, four slots
per host and 1 GB per slot (about 32 GB total), for 12 hours on `hpc`. It loads
NumPy 2.3.1/Python 3.12.11, mpi4py 4.0.3/OpenMPI 5.0.8 and matching Matplotlib.
`OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, `MPLBACKEND=Agg`.

The affinity request reserves cores and MPI binds each rank to one core. Hosts
remain shared, so other jobs can affect timings. Node tests use 4, 2 and 1 rank
per host on the first 2, 4 and 8 hosts. Rank zero stays on the first host. Chunk
and image tests use the same first two hosts. Preflight probes verify CPU models,
rank placement, core binding and that ranks do not share a physical core.
The `hpc` queue enforces `same[type:model]`; the script imposes no fixed CPU
model. DTU’s submission filter rejects user `same[...]` resource directives, so
the script uses the existing queue policy and verifies it with probes. LSF chooses
the model; probes require exact equality across all eight hosts and across all
three placements. Every test runs consecutively in the same allocation, with
explicit hostfiles and a saved host list/model. Mixed-model allocations stop
before pilots or measurements. The selected model may differ from the initial
E5-2660 v3 suite, so cross-suite changes can reflect both image size and CPU.
No nested batch jobs are submitted; MPI commands execute sequentially.

## Pilots and timing

Each implementation runs at 100×100 (smoke test) and 3000×3000 (current baseline)
before measurements. The eight pilot timings are saved but excluded from medians.
The estimator fits a nonnegative startup cost and a nonnegative cost per pixel
from these two sizes, predicts complete runtimes for the grid, and multiplies
the total by two. Predictions never fall below the small-pilot timing.

The runner stops before measurements if this estimate exceeds the remaining
12-hour budget, reserving five minutes for analysis. This is an estimate:
communication overhead, load imbalance and shared-host load may change timings.
Per-command timeouts also enforce the budget.

Complete runtime covers `mpirun` launch through exit, including imports, MPI
startup, computation, communication and finalization. Queue waiting, preflight,
pilots and subsequent plotting are excluded. Algorithms and argument ordering
are unchanged.

## Saved data and analysis

Each new job writes `results/job_JOBID/` with `measurements.csv`, `metadata.json`,
`experiments.yaml`, source snapshots, placement files, stdout/stderr logs and
figures. Every measured attempt is written and flushed immediately. Metadata
records allocation, CPU model, versions, hashes, configuration, seed, pilots,
duration estimate and launched commands. Failures are saved and stop the runner.

Plot independently with the matching Matplotlib environment:

```sh
python3 plot_experiments.py results/job_JOBID
```

The plotter reads the configuration saved with that job. It requires 240
successful on-grid records and three distinct repetitions per group, rejecting
failed, incomplete and duplicate records. It creates nodes, chunk-size and
actual-area figures as PNG and PDF, each using the same 2×2 order: blocking
static, nonblocking static, blocking dynamic, nonblocking dynamic. Axes share
limits within each figure. Markers show medians, connected by lines; captions
state that run's fixed settings and repetition count.

Ten acceptance tests cover the grid, placement guards, known medians, invalid
data, pilot estimates, failure persistence, plot exports and compatibility with
the initial saved results. They also reject mixed CPU models and model changes
between placement probes. `experiments.yaml` uses JSON syntax, a subset of YAML,
avoiding a PyYAML dependency. Plotting can fall back to the existing `vendor/six.py`
for the missing dependency in the cluster Matplotlib module.

Successful completion is `metadata.json` with `"status": "complete"`, 240
successful records and six figure exports. `bjobs JOBID` eventually reports `DONE`.
The node sweep still omits one host; the assignment's one-node versus multiple-node
comparison remains a separate agreed experiment.
