#!/bin/bash
# Submit only this file. No nested batch submissions.
#BSUB -J mandelbrot_followup
#BSUB -q hpc
#BSUB -n 16
#BSUB -W 12:00
#BSUB -R "span[ptile=8]"
# hpc queue enforces same[type:model]; rank probes verify the exact model.
#BSUB -R "rusage[mem=1GB]"
#BSUB -R "affinity[core(1)]"
#BSUB -o mandelbrot_followup_%J.out
#BSUB -e mandelbrot_followup_%J.err
set -euo pipefail
export EXPERIMENT_BATCH_START=$(date +%s)
module purge
module load numpy/2.4.1-python-3.13.11-openblas-0.3.31
module load mpi4py/4.1.1-python-3.13.11-openmpi-5.0.10
module load matplotlib/3.10.8-numpy-2.4.1-python-3.13.11
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MPLBACKEND=Agg
cd "${EXPERIMENT_WORK_DIR:-${LS_SUBCWD:-${LSB_SUBCWD:-$PWD}}}"
RESULTS_DIR="$PWD/results/followup_job_${LSB_JOBID}"
python3 -m unittest -v test_experiments test_followup
python3 run_followup.py --dry-run
python3 run_followup.py --results-dir "$RESULTS_DIR"
python3 analyse_followup.py "$RESULTS_DIR"
python3 publish_results.py "$RESULTS_DIR"
