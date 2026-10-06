import sys
import numpy as np

# initialize MPI
from mpi4py import MPI

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
nranks = comm.Get_size()

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
if chunk_size < 1:
    raise ValueError("chunk-size must be positive")
if argv:
    size = tuple(map(int, argv.pop(0).split("x")))
if argv:
    xlim = tuple(map(float, argv.pop(0).split(":")))
if argv:
    ylim = tuple(map(float, argv.pop(0).split(":")))

# MPI CHANGE: only rank 0 prints shared configuration
if rank == 0:
    print(f"""\
Calculating the Mandelbrot set with these arguments:

{chunk_size = }
{size = }
{xlim = }
{ylim = }
""")

# Convert to numpy arrays, not really needed...
size = np.asarray(size)
xlim = np.asarray(xlim)
ylim = np.asarray(ylim)

# Dimensions of the image
image = np.zeros(size)

xconst = np.diff(xlim)[0] / size[0]
yconst = np.diff(ylim)[0] / size[1]

# MPI CHANGE: row calculation helper
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

# BLOCKING SECTION START: dynamic scheduler and MPI communication
WORK_TAG = 1
RESULT_TAG = 2
work = np.empty(1, dtype=np.int64)

if rank == 0:
    next_row = 0
    completed_rows = 0

    if nranks == 1:
        for x in range(size[0]):
            calculate_row(x)
        completed_rows = size[0]

    # Give one initial chunk to every worker.
    for worker in range(1, nranks):
        if next_row < size[0]:
            work[0] = next_row
            next_row += chunk_size
        else:
            work[0] = -1

        comm.Send(work, dest=worker, tag=WORK_TAG)

    # Receive completed chunks until the entire image is assembled.
    completed_row = np.empty(1, dtype=np.int64)
    status = MPI.Status()

    while completed_rows < size[0]:
        # Receive the chunk start from whichever worker finishes first.
        comm.Recv(
            completed_row,
            source=MPI.ANY_SOURCE,
            tag=RESULT_TAG,
            status=status,
        )

        worker = status.source
        x = int(completed_row[0])

        count = min(chunk_size, size[0] - x)
        # Receive contiguous rows directly into the image.
        comm.Recv(image[x:x + count, :], source=worker, tag=RESULT_TAG)
        completed_rows += count

        # Immediately give the available worker another row.
        if next_row < size[0]:
            work[0] = next_row
            next_row += chunk_size
        else:
            # No work remains, so stop this worker.
            work[0] = -1

        comm.Send(work, dest=worker, tag=WORK_TAG)

else:
    # Receive and calculate rows until rank 0 Sends the stop value.
    while True:
        comm.Recv(work, source=0, tag=WORK_TAG)
        x = int(work[0])

        if x == -1:
            break

        count = min(chunk_size, size[0] - x)
        for row in range(x, x + count):
            calculate_row(row)

        # Return the chunk start, followed by its calculated values.
        comm.Send(work, dest=0, tag=RESULT_TAG)
        comm.Send(image[x:x + count, :], dest=0, tag=RESULT_TAG)
# BLOCKING SECTION END
