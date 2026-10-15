#!/usr/bin/env python3
"""Blocking dynamic scheduler with per-rank timing diagnostics.

The scheduling, communication and arithmetic match Mandelbrot_blocking_dynamic.py.
Each rank additionally records its computation time, the chunks it computed and
the time spent inside Send/Recv. Rank 0 writes all records as JSON to
MANDELBROT_PROFILE_PATH when that variable is set.
"""
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
from mpi4py import MPI

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
nranks = comm.Get_size()

chunk_size = 10
size = 1000, 1000
xlim = -2.2, 0.75
ylim = -1.3, 1.3

argv = sys.argv[1:]
if argv:
    chunk_size = int(argv.pop(0))
if chunk_size < 1:
    raise ValueError("chunk-size must be positive")
if argv:
    size = tuple(map(int, argv.pop(0).split("x")))
if argv:
    xlim = tuple(map(float, argv.pop(0).split(":")))
if argv:
    ylim = tuple(map(float, argv.pop(0).split(":")))

size = np.asarray(size)
xlim = np.asarray(xlim)
ylim = np.asarray(ylim)

image = np.zeros(size)

xconst = np.diff(xlim)[0] / size[0]
yconst = np.diff(ylim)[0] / size[1]

stats = dict(rank=rank, mode='dynamic', compute_seconds=0., send_seconds=0.,
             receive_seconds=0., rows=0, chunks=0, chunk_starts=[],
             send_calls=0, receive_calls=0)


def calculate_row(x):
    cx = complex(xlim[0] + x * xconst, 0)

    for y in range(size[1]):
        c = cx + complex(0, ylim[0] + y * yconst)
        z = 0

        for i in range(100):
            z = z*z + c
            if np.abs(z) > 2:
                image[x, y] = i
                break


def send(buffer, dest, tag):
    tick = time.monotonic()
    comm.Send(buffer, dest=dest, tag=tag)
    stats['send_seconds'] += time.monotonic() - tick
    stats['send_calls'] += 1


def receive(buffer, source, tag, status=None):
    tick = time.monotonic()
    comm.Recv(buffer, source=source, tag=tag, status=status)
    stats['receive_seconds'] += time.monotonic() - tick
    stats['receive_calls'] += 1


WORK_TAG = 1
RESULT_TAG = 2
work = np.empty(1, dtype=np.int64)
started = time.monotonic()

if rank == 0:
    next_row = 0
    completed_rows = 0

    if nranks == 1:
        tick = time.monotonic()
        for x in range(size[0]):
            calculate_row(x)
        stats['compute_seconds'] += time.monotonic() - tick
        stats.update(rows=int(size[0]), chunks=1, chunk_starts=[0])
        completed_rows = size[0]

    # Give one initial chunk to every worker.
    for worker in range(1, nranks):
        if next_row < size[0]:
            work[0] = next_row
            next_row += chunk_size
        else:
            work[0] = -1
        send(work, worker, WORK_TAG)

    completed_row = np.empty(1, dtype=np.int64)
    status = MPI.Status()

    while completed_rows < size[0]:
        receive(completed_row, MPI.ANY_SOURCE, RESULT_TAG, status)
        worker = status.source
        x = int(completed_row[0])
        count = min(chunk_size, size[0] - x)
        receive(image[x:x + count, :], worker, RESULT_TAG)
        completed_rows += count

        if next_row < size[0]:
            work[0] = next_row
            next_row += chunk_size
        else:
            work[0] = -1
        send(work, worker, WORK_TAG)

else:
    while True:
        receive(work, 0, WORK_TAG)
        x = int(work[0])

        if x == -1:
            break

        count = min(chunk_size, size[0] - x)
        tick = time.monotonic()
        for row in range(x, x + count):
            calculate_row(row)
        stats['compute_seconds'] += time.monotonic() - tick
        stats['rows'] += int(count)
        stats['chunks'] += 1
        stats['chunk_starts'].append(x)

        send(work, 0, RESULT_TAG)
        send(image[x:x + count, :], 0, RESULT_TAG)

stats['algorithm_seconds'] = time.monotonic() - started
tick = time.monotonic()
comm.Barrier()
stats['final_barrier_seconds'] = time.monotonic() - tick
records = comm.gather(stats, root=0)
if rank == 0 and os.environ.get('MANDELBROT_PROFILE_PATH'):
    Path(os.environ['MANDELBROT_PROFILE_PATH']).write_text(json.dumps(records, indent=2) + '\n')
