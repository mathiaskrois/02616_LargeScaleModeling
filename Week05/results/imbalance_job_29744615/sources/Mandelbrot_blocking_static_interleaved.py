#!/usr/bin/env python3
"""Blocking cyclic static scheduling, receiving results after each chunk round."""
from Mandelbrot_static_profiled import main

if __name__ == '__main__':
    main(mode='interleaved')
