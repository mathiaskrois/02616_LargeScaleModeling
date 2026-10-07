#!/usr/bin/env python3
"""Report rank placement and physical cores for the experiment preflight."""
import json
import os
from pathlib import Path
import socket
from mpi4py import MPI

cpu_info = {}
for block in Path('/proc/cpuinfo').read_text().strip().split('\n\n'):
    fields = dict(line.split(':', 1) for line in block.splitlines() if ':' in line)
    fields = {k.strip(): v.strip() for k, v in fields.items()}
    if 'processor' in fields:
        cpu_info[int(fields['processor'])] = fields
cpus = sorted(os.sched_getaffinity(0))
cores = sorted({(cpu_info[cpu]['physical id'], cpu_info[cpu]['core id']) for cpu in cpus})
record = dict(rank=MPI.COMM_WORLD.rank, host=socket.gethostname(), affinity=cpus,
              physical_cores=cores, cpu_model=cpu_info[cpus[0]]['model name'],
              mpi_library_version=MPI.Get_library_version().rstrip('\x00\n'))
records = MPI.COMM_WORLD.gather(record, root=0)
if MPI.COMM_WORLD.rank == 0:
    print(json.dumps(records))
