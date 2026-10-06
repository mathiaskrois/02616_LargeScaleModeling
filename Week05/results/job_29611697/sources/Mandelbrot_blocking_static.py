import sys
import numpy as np
from mpi4py import MPI

_help = f"""\
{sys.argv[0]} [chunk-size] [size widthXheight] [limits xmin:xmax ymin:ymax]

Here are some examples:

Call it with a chunk-size of 10
$ {sys.argv[0]} 10

Call it with a chunk-size of 10 and image size of 100 by 500 pixels
$ {sys.argv[0]} 10 100x500

Call it with a chunk-size of 10 and image size of 100 by 500 pixels
spanning the coordinates x \\in 0.1-0.3 and y \\in 0.2-0.3
$ {sys.argv[0]} 10 100x500 0.1:0.3 0.2:0.3
"""

for h in ("help", "-h", "-help", "--help"):
    if h in sys.argv:
        print(_help)
        sys.exit(0)

# First we define all the defaults, then we let the arguments overwrite
# them.
chunk_size = 10
size = 1000, 1000
xlim = -2.2, 0.75
ylim = -1.3, 1.3

# Now grab the arguments
argv = sys.argv[1:]
if argv:
    chunk_size = int(argv.pop(0))
if argv:
    size = tuple(map(int, argv.pop(0).split("x")))
if argv:
    xlim = tuple(map(float, argv.pop(0).split(":")))
if argv:
    ylim = tuple(map(float, argv.pop(0).split(":")))



# Convert to numpy arrays, not really needed...
size = np.asarray(size)
xlim = np.asarray(xlim)
ylim = np.asarray(ylim)


comm = MPI.COMM_WORLD
nranks = comm.Get_size()
rank = comm.Get_rank()

# Dimensions of the image
if rank == 0:
    image = np.zeros(size)
    print(f"""\
    Calculating the Mandelbrot set with these arguments:

    {chunk_size = }
    {size = }
    {xlim = }
    {ylim = }
    """)

xconst = np.diff(xlim)[0] / size[0]
yconst = np.diff(ylim)[0] / size[1]


def static_scheduler_cyclic(rank, chunk_size, nrows, nranks):
    nchunks = (nrows + chunk_size -1) // chunk_size
    rank_rows = []

    for chunk in range(nchunks):
        if chunk % nranks == rank:
            start = chunk * chunk_size 
            stop = min(chunk * chunk_size + chunk_size, nrows)
            rank_rows.append(np.arange(start, stop))

    return rank_rows


def compute_chunk(start, stop, size, xlim, ylim, xconst, yconst):
    xchunk = np.zeros([stop-start, size[1]])

    for x in range(start, stop):
        cx = complex(xlim[0] + x * xconst, 0)
        for y in range(size[1]):
            # process (x, y)
            c = cx + complex(0, ylim[0] + y * yconst)
            z = 0
            for i in range(100):
                z = z*z + c
                if np.abs(z) > 2:
                    xchunk[x-start, y] = i # Load into the local buffer
                    break

    return xchunk


def compute():
    chunks = static_scheduler_cyclic(rank=rank, chunk_size=chunk_size, nrows =size[0], nranks=nranks)

    for k in chunks:
        start = k[0]
        stop = k[-1]+1
        buf = compute_chunk(start, stop, size, xlim, ylim, xconst, yconst)

        if rank == 0:
            image[start:stop] = buf

        else:
            comm.Send(buf, dest=0, tag=rank)
            

    if rank == 0:
        for r in range(1, nranks):
            rank_rows = static_scheduler_cyclic(rank = r, chunk_size=chunk_size, nrows =size[0], nranks=nranks)
            for rows in rank_rows:
                start = rows[0]
                stop = rows[-1]+1
                comm.Recv(image[start:stop], source=r, tag = r)

    return 

compute()

