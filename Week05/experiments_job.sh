#!/bin/bash
# Submit this script only: bsub < experiments_job.sh
#BSUB -J mandelbrot_experiments
#BSUB -q hpc
#BSUB -n 32
#BSUB -W 12:00
#BSUB -R "span[ptile=4]"
# The hpc queue enforces same[type:model]; probes verify the exact CPU model.
#BSUB -R "rusage[mem=1GB]"
#BSUB -R "affinity[core(1)]"
#BSUB -o mandelbrot_experiments_%J.out
#BSUB -e mandelbrot_experiments_%J.err
set -euo pipefail
export EXPERIMENT_BATCH_START=$(date +%s)
module purge
module load numpy/2.4.1-python-3.13.11-openblas-0.3.31
module load mpi4py/4.1.1-python-3.13.11-openmpi-5.0.10
module load matplotlib/3.10.8-numpy-2.4.1-python-3.13.11
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MPLBACKEND=Agg
cd "${EXPERIMENT_WORK_DIR:-${LS_SUBCWD:-${LSB_SUBCWD:-$PWD}}}"
RESULTS_DIR="$PWD/results/job_${LSB_JOBID}"
python3 -m unittest -v test_experiments
python3 run_experiments.py --dry-run > /dev/null
python3 run_experiments.py --results-dir "$RESULTS_DIR"
python3 plot_experiments.py "$RESULTS_DIR"
