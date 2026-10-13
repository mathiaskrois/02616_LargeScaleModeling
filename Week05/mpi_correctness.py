#!/usr/bin/env python3
"""Run an implementation and save rank zero's image for serial-reference checking."""
import os
from pathlib import Path
import runpy
import sys
from mpi4py import MPI
import numpy as np

program = Path(sys.argv.pop(1)).resolve()
output = Path(os.environ['MANDELBROT_IMAGE_PATH']).resolve()
sys.argv[0] = str(program)
# Serial plotting writes Figure_1.png; keep it inside this job's correctness folder.
os.chdir(output.parent)
if os.environ.get('MANDELBROT_SERIAL_CALCULATION_ONLY') == '1':
    if program.name != 'Mandelbrot.py':
        raise ValueError('Plot-free calculation mode is only for the original serial source')
    from verify_and_benchmark import serial_calculation_namespace
    namespace = serial_calculation_namespace(program)
else:
    namespace = runpy.run_path(str(program), run_name='__main__')
if MPI.COMM_WORLD.rank == 0:
    image = namespace.get('image')
    if image is None:
        # The interleaved entry point calls a function defined in the shared module.
        image = namespace['main'].__globals__['image']
    np.save(output, image)
