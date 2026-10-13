#!/bin/bash
#BSUB -J mandelbrot_correctness_overview
#BSUB -q hpc
#BSUB -n 8
#BSUB -W 06:00
#BSUB -w "done(29706381)"
#BSUB -R "span[ptile=4]"
#BSUB -R "select[model == XeonE5_2650v4]"
#BSUB -R "rusage[mem=1GB]"
#BSUB -R "affinity[core(1)]"
#BSUB -o mandelbrot_verification_%J.out
#BSUB -e mandelbrot_verification_%J.err
set -euo pipefail
export EXPERIMENT_BATCH_START=$(date +%s)
module purge
module load numpy/2.4.1-python-3.13.11-openblas-0.3.31
module load mpi4py/4.1.1-python-3.13.11-openmpi-5.0.10
module load matplotlib/3.10.8-numpy-2.4.1-python-3.13.11
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MPLBACKEND=Agg
cd "${EXPERIMENT_WORK_DIR:-${LS_SUBCWD:-${LSB_SUBCWD:-$PWD}}}"
python3 -m unittest -v test_five_versions
RESULTS_DIR="$PWD/results/verification_job_${LSB_JOBID}"
python3 verify_and_benchmark.py --results-dir "$RESULTS_DIR" --parent-results "$PARENT_RESULTS_DIR"
python3 publish_results.py "$RESULTS_DIR"
