#!/usr/bin/env python3
"""Fast streaming byte-by-byte comparison of two files using multiple threads.

Exit codes: 0 = files are the same, 1 = files differ, 2 = error.
"""

import argparse
import os
import sys
import threading
import time

CHUNK = 8 * 1024 * 1024
EXIT_SAME = 0
EXIT_DIFF = 1
EXIT_ERROR = 2


class State:
	def __init__(self):
		self.lock = threading.Lock()
		self.read_a = 0
		self.read_b = 0
		self.stop = threading.Event()
		self.diff_offset = None
		self.error = None

	def add(self, na, nb):
		with self.lock:
			self.read_a += na
			self.read_b += nb

	def set_diff(self, offset):
		with self.lock:
			if self.diff_offset is None or offset < self.diff_offset:
				self.diff_offset = offset
		self.stop.set()


def first_mismatch(a, b):
	lo, hi = 0, min(len(a), len(b))
	while hi - lo > 4096:
		mid = (lo + hi) // 2
		if a[lo:mid] != b[lo:mid]:
			hi = mid
		else:
			lo = mid
	for i in range(lo, hi):
		if a[i] != b[i]:
			return i
	return hi


def worker(path_a, path_b, start, end, state):
	try:
		with open(path_a, "rb", buffering=0) as fa, open(path_b, "rb", buffering=0) as fb:
			fa.seek(start)
			fb.seek(start)
			pos = start
			while pos < end and not state.stop.is_set():
				n = min(CHUNK, end - pos)
				a = fa.read(n)
				b = fb.read(n)
				state.add(len(a), len(b))
				if a != b:
					state.set_diff(pos + first_mismatch(a, b))
					return
				if len(a) < n:
					state.set_diff(pos + len(a))
					return
				pos += n
	except OSError as e:
		state.error = e
		state.stop.set()


def fmt_size(n):
	for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
		if n < 1024 or unit == "TiB":
			return f"{n} B" if unit == "B" else f"{n:.1f} {unit}"
		n /= 1024


def print_progress(state, size, t0, final=False):
	with state.lock:
		ra, rb = state.read_a, state.read_b
	pa = 100.0 * ra / size if size else 100.0
	pb = 100.0 * rb / size if size else 100.0
	el = max(time.monotonic() - t0, 1e-9)
	speed = (ra + rb) / el
	line = f"A: {pa:6.2f}% ({fmt_size(ra)})  B: {pb:6.2f}% ({fmt_size(rb)})  {fmt_size(speed)}/s  {el:.1f}s"
	sys.stderr.write("\r" + line.ljust(90))
	if final:
		sys.stderr.write("\n")
	sys.stderr.flush()


def main():
	ap = argparse.ArgumentParser(description="Compare two files byte by byte.")
	ap.add_argument("file_a")
	ap.add_argument("file_b")
	ap.add_argument("-t", "--threads", type=int, default=4, help="worker threads (default 4)")
	ap.add_argument("-q", "--quiet", action="store_true", help="no progress output")
	args = ap.parse_args()

	try:
		size_a = os.path.getsize(args.file_a)
		size_b = os.path.getsize(args.file_b)
		if size_a == size_b and os.path.samefile(args.file_a, args.file_b):
			print("Files are the same")
			return EXIT_SAME
	except OSError as e:
		print(f"Error: {e}", file=sys.stderr)
		return EXIT_ERROR

	if size_a != size_b:
		print(f"Size A: {size_a} bytes, size B: {size_b} bytes")
		print("Files differ")
		return EXIT_DIFF

	size = size_a
	threads = max(1, min(args.threads, size // CHUNK or 1))
	part = size // threads
	state = State()
	pool = []
	for i in range(threads):
		start = i * part
		end = size if i == threads - 1 else (i + 1) * part
		pool.append(threading.Thread(target=worker, args=(args.file_a, args.file_b, start, end, state), daemon=True))

	t0 = time.monotonic()
	for t in pool:
		t.start()
	try:
		while any(t.is_alive() for t in pool):
			if not args.quiet:
				print_progress(state, size, t0)
			time.sleep(0.2)
	except KeyboardInterrupt:
		state.stop.set()
		sys.stderr.write("\nInterrupted\n")
		return EXIT_ERROR
	if not args.quiet:
		print_progress(state, size, t0, final=True)

	if state.error:
		print(f"Error: {state.error}", file=sys.stderr)
		return EXIT_ERROR
	if state.diff_offset is not None:
		print(f"First difference at offset {state.diff_offset} (0x{state.diff_offset:X})")
		print("Files differ")
		return EXIT_DIFF
	print("Files are the same")
	return EXIT_SAME


if __name__ == "__main__":
	sys.exit(main())
