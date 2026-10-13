#!/bin/bash
#BSUB -J mandelbrot_chunk1
#BSUB -q hpc
#BSUB -n 8
#BSUB -W 00:30
#BSUB -R "span[ptile=4]"
#BSUB -R "select[model == XeonE5_2660v3]"
#BSUB -R "rusage[mem=1GB]"
#BSUB -R "affinity[core(1)]"
#BSUB -o mandelbrot_chunk1_%J.out
#BSUB -e mandelbrot_chunk1_%J.err
set -euo pipefail
module purge
module load numpy/2.4.1-python-3.13.11-openblas-0.3.31
module load mpi4py/4.1.1-python-3.13.11-openmpi-5.0.10
module load matplotlib/3.10.8-numpy-2.4.1-python-3.13.11
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MPLBACKEND=Agg
cd "${EXPERIMENT_WORK_DIR:-${LS_SUBCWD:-${LSB_SUBCWD:-$PWD}}}"
python3 -m unittest -v test_chunk1
python3 retest_chunk1.py
python3 publish_results.py "$PWD/results/chunk1_job_${LSB_JOBID}"
