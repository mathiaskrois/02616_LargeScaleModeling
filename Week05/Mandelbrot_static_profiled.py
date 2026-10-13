#!/usr/bin/env python3
"""Original cyclic blocking static algorithm, with per-rank timing diagnostics.

The interleaved mode receives one round of chunks before starting the next round.
The arithmetic and row assignment match Mandelbrot_blocking_static.py.
"""
import json
import os
import sys
import time
from pathlib import Path
import numpy as np
from mpi4py import MPI


def compute_chunk(start, stop, size, xlim, ylim, xconst, yconst):
    result = np.zeros((stop - start, size[1]))
    for x in range(start, stop):
        cx = complex(xlim[0] + x * xconst, 0)
        for y in range(size[1]):
            c = cx + complex(0, ylim[0] + y * yconst)
            z = 0
            for i in range(100):
                z = z*z + c
                if np.abs(z) > 2:
                    result[x-start, y] = i
                    break
    return result


def chunks_for(rank, rows, chunk, ranks):
    return [(start, min(start + chunk, rows))
            for start in range(rank * chunk, rows, ranks * chunk)]


def main(mode='original'):
    global image
    args = sys.argv[1:]
    chunk = int(args[0]) if args else 10
    size = tuple(map(int, args[1].split('x'))) if len(args) > 1 else (1000, 1000)
    xlim = tuple(map(float, args[2].split(':'))) if len(args) > 2 else (-2.2, .75)
    ylim = tuple(map(float, args[3].split(':'))) if len(args) > 3 else (-1.3, 1.3)
    if chunk < 1 or min(size) < 1:
        raise ValueError('Chunk and dimensions must be positive')
    comm = MPI.COMM_WORLD
    rank, ranks = comm.rank, comm.size
    image = np.zeros(size) if rank == 0 else None
    xc, yc = (xlim[1]-xlim[0])/size[0], (ylim[1]-ylim[0])/size[1]
    stats = dict(rank=rank, mode=mode, compute_seconds=0., send_seconds=0.,
                 receive_seconds=0., rows=0, send_calls=0, receive_calls=0)
    started = time.monotonic()

    def calculate(start, stop):
        tick = time.monotonic()
        result = compute_chunk(start, stop, size, xlim, ylim, xc, yc)
        stats['compute_seconds'] += time.monotonic()-tick
        stats['rows'] += stop-start
        return result

    def send(buffer):
        tick = time.monotonic()
        comm.Send(buffer, dest=0, tag=rank)
        stats['send_seconds'] += time.monotonic()-tick
        stats['send_calls'] += 1

    def receive(worker, start, stop):
        tick = time.monotonic()
        comm.Recv(image[start:stop], source=worker, tag=worker)
        stats['receive_seconds'] += time.monotonic()-tick
        stats['receive_calls'] += 1

    if mode == 'original':
        for start, stop in chunks_for(rank, size[0], chunk, ranks):
            buffer = calculate(start, stop)
            if rank == 0:
                image[start:stop] = buffer
            else:
                send(buffer)
        if rank == 0:
            for worker in range(1, ranks):
                for start, stop in chunks_for(worker, size[0], chunk, ranks):
                    receive(worker, start, stop)
    elif mode == 'interleaved':
        for base in range(0, size[0], ranks * chunk):
            start, stop = base + rank*chunk, min(base + (rank+1)*chunk, size[0])
            if start < size[0]:
                buffer = calculate(start, stop)
                if rank == 0:
                    image[start:stop] = buffer
                else:
                    send(buffer)
            if rank == 0:
                for worker in range(1, ranks):
                    start = base + worker*chunk
                    if start < size[0]:
                        receive(worker, start, min(start+chunk, size[0]))
    else:
        raise ValueError(f'Unknown mode: {mode}')
    stats['algorithm_seconds'] = time.monotonic()-started
    tick = time.monotonic()
    comm.Barrier()
    stats['final_barrier_seconds'] = time.monotonic()-tick
    records = comm.gather(stats, root=0)
    if rank == 0 and os.environ.get('MANDELBROT_PROFILE_PATH'):
        Path(os.environ['MANDELBROT_PROFILE_PATH']).write_text(json.dumps(records, indent=2)+'\n')


if __name__ == '__main__':
    main()
