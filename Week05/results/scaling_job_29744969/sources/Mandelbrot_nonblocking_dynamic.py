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

# NON-BLOCKING SECTION START: dynamic scheduler and MPI communication
WORK_TAG = 1
RESULT_TAG = 2
work = np.empty(1, dtype=np.int64)

if rank == 0:
    next_row = 0
    completed_rows = 0
    # Keep a header receive posted for every worker that has work.
    completed_chunks = [np.empty(1, dtype=np.int64) for _ in range(nranks)]
    receives = [MPI.REQUEST_NULL for _ in range(nranks)]

    if nranks == 1:
        for x in range(size[0]):
            calculate_row(x)
        completed_rows = size[0]

    # Give one initial chunk to every worker.
    for worker in range(1, nranks):
        if next_row < size[0]:
            work[0] = next_row
            next_row += chunk_size
            receives[worker] = comm.Irecv(
                completed_chunks[worker], source=worker, tag=RESULT_TAG
            )
        else:
            work[0] = -1

        comm.Isend(work, dest=worker, tag=WORK_TAG).Wait()

    # Receive completed chunks until the entire image is assembled.
    while completed_rows < size[0]:
        # Wait for any posted header; other workers' receives remain active.
        worker = MPI.Request.Waitany(receives)
        x = int(completed_chunks[worker][0])

        count = min(chunk_size, size[0] - x)
        # Receive contiguous rows directly into the image.
        comm.Irecv(image[x:x + count, :], source=worker, tag=RESULT_TAG).Wait()
        completed_rows += count

        # Immediately give the available worker another row.
        if next_row < size[0]:
            work[0] = next_row
            next_row += chunk_size
            receives[worker] = comm.Irecv(
                completed_chunks[worker], source=worker, tag=RESULT_TAG
            )
        else:
            # No work remains, so stop this worker.
            work[0] = -1
            receives[worker] = MPI.REQUEST_NULL

        comm.Isend(work, dest=worker, tag=WORK_TAG).Wait()

else:
    # Receive and calculate rows until rank 0 Sends the stop value.
    while True:
        comm.Irecv(work, source=0, tag=WORK_TAG).Wait()
        x = int(work[0])

        if x == -1:
            break

        count = min(chunk_size, size[0] - x)
        for row in range(x, x + count):
            calculate_row(row)

        # Return the chunk start, followed by its calculated values.
        header_request = comm.Isend(work, dest=0, tag=RESULT_TAG)
        data_request = comm.Isend(image[x:x + count, :], dest=0, tag=RESULT_TAG)
        MPI.Request.Waitall([header_request, data_request])
# NON-BLOCKING SECTION END
