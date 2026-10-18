#!/bin/bash
# Submit only this file from Week05: bsub < scaling_job.sh
#BSUB -J mandelbrot_scaling
#BSUB -q hpc
#BSUB -n 64
#BSUB -W 3:00
#BSUB -R "span[ptile=8]"
# hpc queue enforces same[type:model]; rank probes verify the exact model.
# To use the same CPU model as jobs 29706381/29710858, uncomment the next line
# (this may mean a longer wait in the queue):
##BSUB -R "select[model == XeonE5_2650v4]"
#BSUB -R "rusage[mem=1GB]"
#BSUB -R "affinity[core(1)]"
#BSUB -o mandelbrot_scaling_%J.out
#BSUB -e mandelbrot_scaling_%J.err
set -euo pipefail
export EXPERIMENT_BATCH_START=$(date +%s)
module purge
module load numpy/2.4.1-python-3.13.11-openblas-0.3.31
module load mpi4py/4.1.1-python-3.13.11-openmpi-5.0.10
module load matplotlib/3.10.8-numpy-2.4.1-python-3.13.11
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MPLBACKEND=Agg
cd "${EXPERIMENT_WORK_DIR:-${LS_SUBCWD:-${LSB_SUBCWD:-$PWD}}}"
RESULTS_DIR="$PWD/results/scaling_job_${LSB_JOBID}"
python3 -m unittest -v test_scaling
python3 run_scaling.py --dry-run
python3 run_scaling.py --results-dir "$RESULTS_DIR"
python3 analyse_scaling.py "$RESULTS_DIR"
# Results stay local; commit and push them yourself after checking SUMMARY.md.
