#!/bin/sh
# Submit with: bsub < mandelbrot_nonblocking_dynamic_job.sh
#BSUB -J mandelbrot_nonblocking
#BSUB -q hpc
#BSUB -W 00:10
#BSUB -n 4
#BSUB -R "span[ptile=4]"
#BSUB -R "rusage[mem=1GB]"
#BSUB -o mandelbrot_nonblocking_%J.out
#BSUB -e mandelbrot_nonblocking_%J.err

module load numpy/2.3.1-python-3.12.11-openblas-0.3.30
module load mpi4py/4.0.3-python-3.12.11-openmpi-5.0.8

cd ${EXPERIMENT_WORK_DIR:-${LS_SUBCWD:-${LSB_SUBCWD:-$PWD}}} || exit 1

# 10 rows per assignment, 1000 by 1000 pixels; default Mandelbrot limits.
mpirun -np 4 python3 Mandelbrot_nonblocking_dynamic.py 10 1000x1000
