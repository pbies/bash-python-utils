#!/usr/bin/env python3

# from timing import Timer, timer

# with Timer():

import time
from functools import wraps


class Timer:
	"""with Timer() as t: ...  ->  t.elapsed available after block."""
	def __init__(self, label=None, verbose=True):
		self.label = label
		self.verbose = verbose
		self.elapsed = None

	def __enter__(self):
		self.start = time.perf_counter()
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		self.elapsed = time.perf_counter() - self.start
		if self.verbose:
			prefix = f'[{self.label}] ' if self.label else ''
			status = ' (raised)' if exc_type else ''
			print(f'{prefix}This took: {self.elapsed:.5f} seconds{status}')
		return False


def timer(func=None, *, verbose=True):
	"""Usable as @timer or @timer(verbose=...).
	verbose: bool, or zero-arg callable returning bool (evaluated per call)."""
	def decorate(f):
		@wraps(f)
		def wrapper(*args, **kwargs):
			start = time.perf_counter()
			try:
				return f(*args, **kwargs)
			finally:
				on = verbose() if callable(verbose) else verbose
				if on:
					print(f'  [{f.__name__}] took {time.perf_counter() - start:.4f}s')
		return wrapper
	if func is not None:
		return decorate(func)
	return decorate
