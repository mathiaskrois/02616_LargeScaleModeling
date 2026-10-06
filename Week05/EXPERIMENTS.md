# Mandelbrot runtime experiments

Submit one allocation from Week05:

```sh
python3 run_experiments.py --dry-run
export EXPERIMENT_WORK_DIR="$PWD"
bsub < experiments_job.sh
```

The allocation reserves 32 slots across eight hosts, four slots per host,
1 GB per slot (about 32 GB total), for 12 hours on Xeon E5-2660 v3 CPUs.
The affinity request reserves cores; MPI explicitly binds each rank to one core.
Hosts remain shared, so other jobs can affect timings. All experiments use eight
ranks. The node sweep uses 2, 4 and 8 hosts, with 4, 2 and 1 rank per host.
The chunk and image sweeps always use the first two allocated hosts. Rank zero
stays on the first host. Preflight probes check the CPU model, rank order,
physical core binding and that ranks do not share a core on a host.

`experiments.yaml` uses JSON syntax (a subset of YAML), avoiding a PyYAML dependency
in the cluster modules. Plotting falls back to the existing `vendor/six.py`
when the cluster Matplotlib dependency is missing. It contains the selected grid, source filenames, seed,
modules and resource settings. If changing resource settings, update the batch
script's matching directives and modules too.

There are 80 configurations and three shuffled repetition rounds, 240 sequential
measurements in total. The shuffle uses seed 261605. Each implementation first
runs at 100×100 (smoke test) and 1000×1000 on the baseline placement. The eight
pilot timings are saved but excluded from medians. The suite estimate uses each
implementation's baseline runtime scaled by area (never below the baseline or
small pilot), with a factor of two allowance. This is an estimate: changes in
communication overhead and shared-host load can exceed it. The runner stops
before measurements if the estimate exceeds the remaining budget, reserving
five minutes for plotting. A per-command timeout also enforces that budget.

Runtime covers the complete `mpirun` launch through successful exit, including
imports, MPI startup, computation, communication and finalization. Queue waiting,
preflight, pilots and subsequent analysis are excluded. Limits remain
`-2.2:0.75`, `-1.3:1.3`; the implementations retain their hard-coded 100 iterations.
Algorithms and argument ordering are unchanged. Dynamic rank zero manages work;
a chunk of 125 rows does not imply equal work across eight ranks.

Each job saves `results/job_JOBID/` containing:

- `measurements.csv`: one immediately flushed record per measured attempt.
- `metadata.json`: allocation, CPU model, module/package versions, source hashes,
  configuration, seed, probes, pilot timings, estimate and launched commands.
- `sources/` and `experiments.yaml`: reproducible source and configuration snapshots.
- `logs/`: stdout and stderr for every probe, pilot and measurement.
- `figures/`: nodes, chunk size and actual image area, each as PNG and PDF.

The runner stops after a failed attempt and retains its record and logs. Analysis
requires exactly 240 successful records with the correct grid and three distinct
repetitions per group. It rejects incomplete, failed, duplicate and off-grid data.
To plot a saved suite independently with the matching Matplotlib module loaded:

```sh
python3 plot_experiments.py results/job_JOBID
```

Each figure uses the same 2×2 arrangement: blocking static, nonblocking static,
blocking dynamic, nonblocking dynamic. Axes share limits within each figure;
points show median complete runtime from three repetitions. Image targets span
10,000 to 4,000,000 pixels in ten equally spaced steps. Sides are rounded square
roots; both target and actual areas are saved, and actual area is plotted.

Run the local acceptance tests with `python3 -m unittest -v test_experiments`
from Week05. They check the grid, host and core guards, known medians, rejection
of invalid data, timeouts and all six plot exports using temporary synthetic data.
Real MPI probes and smoke tests run inside the batch allocation before measurement;
do not run MPI benchmarks on the login host. The node grid omits one host, so the
assignment's separate one-node versus multiple-node comparison still needs its
own agreed experiment.
