#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sorter04.py - Fully parallel external sort + dedup for huge line files (MD5 hashes).

Phase 1  Each worker reads its own byte range of the input (no data pickled through
         the parent), dedups + sorts it, and splits the result into P key-range
         partitions using splitters sampled from the input. One LZ4 frame per
         partition per chunk, all in one chunk file.
Phase 2  The P partitions are merged independently and in parallel. Key ranges are
         disjoint, so no cross-partition dedup is needed.
Phase 3  Partitions are concatenated in key order into the output; LZ4 decompression
         runs in a reader thread overlapped with disk writes.

Output is byte-ordered (LC_ALL=C), one unique line per row, empty lines dropped.
"""
import os
import sys
import time
import heapq
import bisect
import queue
import argparse
import tempfile
import threading
import lz4.frame
from multiprocessing import Pool, cpu_count

# -----------------------------------------------
# Default settings
# -----------------------------------------------
CHUNK_MB         = 128      # raw input bytes per phase-1 task
NUM_WORKERS      = cpu_count()
PARTS_PER_WORKER = 4        # partitions = workers * this (load balancing)
FANIN            = 512      # max open slices per merge; above this -> multi-level
TEMP_DIR         = "."
LZ4_LEVEL        = 1
READ_SIZE        = 64 * 1024
WRITE_BATCH      = 50000
COPY_BLOCK       = 8 << 20

_t0 = time.time()

def log(msg):
	print("[%7.1fs] %s" % (time.time() - _t0, msg))
	sys.stdout.flush()

# -----------------------------------------------
# Planning (parent process)
# -----------------------------------------------
def compute_ranges(path, size, chunk_bytes):
	# Byte ranges aligned to line boundaries.
	ranges = []
	start = 0
	with open(path, "rb") as f:
		while start < size:
			end = start + chunk_bytes
			if end >= size:
				end = size
			else:
				f.seek(end - 1)
				f.readline()
				end = f.tell()
			ranges.append((start, end))
			start = end
	return ranges

def sample_splitters(path, size, n_parts):
	# Evenly spaced samples -> quantiles -> partition boundaries.
	if n_parts <= 1:
		return []
	n = min(max(n_parts * 64, 1024), 65536)
	samples = set()
	with open(path, "rb") as f:
		for i in range(n):
			off = (size * i) // n
			f.seek(off)
			if off:
				f.readline()
			line = f.readline().rstrip(b"\r\n")
			if line:
				samples.add(line)
	samples = sorted(samples)
	if len(samples) < 2:
		return []
	return sorted(set(samples[(len(samples) * k) // n_parts] for k in range(1, n_parts)))

# -----------------------------------------------
# Worker state (set once per process, works with spawn on Windows)
# -----------------------------------------------
_W = {}

def init_worker(input_file, tmp_dir, splitters):
	_W["input"] = input_file
	_W["tmp"] = tmp_dir
	_W["spl"] = splitters

# -----------------------------------------------
# Phase 1 worker: read range, dedup, sort, partition
# -----------------------------------------------
def sort_chunk(args):
	chunk_id, start, end = args
	t = time.time()
	with open(_W["input"], "rb") as f:
		f.seek(start)
		data = f.read(end - start)
	if b"\r" in data:
		data = data.replace(b"\r\n", b"\n")
		if data.endswith(b"\r"):
			data = data[:-1]
	n_lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
	s = set(data.split(b"\n"))
	del data
	s.discard(b"")
	unique = sorted(s)  # bytes order = LC_ALL=C
	del s

	cuts = [0] + [bisect.bisect_left(unique, x) for x in _W["spl"]] + [len(unique)]
	path = os.path.join(_W["tmp"], "chunk_%06d.lz4" % chunk_id)
	index = []
	off = 0
	with open(path, "wb") as out:
		for p in range(len(cuts) - 1):
			a, b = cuts[p], cuts[p + 1]
			if a == b:
				index.append((0, 0))
				continue
			frame = lz4.frame.compress(b"\n".join(unique[a:b]) + b"\n",
									   compression_level=LZ4_LEVEL,
									   block_size=lz4.frame.BLOCKSIZE_MAX64KB)
			out.write(frame)
			index.append((off, len(frame)))
			off += len(frame)
	return chunk_id, path, index, n_lines, len(unique), time.time() - t

# -----------------------------------------------
# Streaming reader for one LZ4 frame inside a file
# -----------------------------------------------
def slice_iter(path, off, length):
	dec = lz4.frame.LZ4FrameDecompressor()
	tail = b""
	with open(path, "rb", buffering=0) as f:
		f.seek(off)
		remaining = length
		while remaining > 0:
			raw = f.read(min(READ_SIZE, remaining))
			if not raw:
				break
			remaining -= len(raw)
			chunk = dec.decompress(raw)
			if not chunk:
				continue
			lines = (tail + chunk).split(b"\n")
			tail = lines.pop()
			yield from filter(None, lines)
	if tail:
		yield tail

def merge_to_lz4(srcs, out_path, block_size):
	iters = [slice_iter(p, o, l) for (p, o, l) in srcs]
	prev = None
	count = 0
	buf = []
	with lz4.frame.open(out_path, mode="wb", compression_level=LZ4_LEVEL,
						block_size=block_size) as out:
		for line in heapq.merge(*iters):
			if line != prev:
				buf.append(line)
				prev = line
				if len(buf) >= WRITE_BATCH:
					out.write(b"\n".join(buf) + b"\n")
					count += len(buf)
					buf = []
		if buf:
			out.write(b"\n".join(buf) + b"\n")
			count += len(buf)
	return count

# -----------------------------------------------
# Phase 2 worker: merge one partition
# -----------------------------------------------
def merge_partition(args):
	p, srcs, fanin = args
	t = time.time()
	n_src = len(srcs)
	if not srcs:
		return p, None, 0, 0, time.time() - t
	level = 0
	while len(srcs) > fanin:
		nxt = []
		for i in range(0, len(srcs), fanin):
			out = os.path.join(_W["tmp"], "p%05d_l%d_%05d.lz4" % (p, level, i // fanin))
			merge_to_lz4(srcs[i:i + fanin], out, lz4.frame.BLOCKSIZE_MAX64KB)
			nxt.append((out, 0, os.path.getsize(out)))
		if level > 0:
			for s in srcs:
				os.remove(s[0])
		srcs = nxt
		level += 1
	out = os.path.join(_W["tmp"], "part_%05d.lz4" % p)
	count = merge_to_lz4(srcs, out, lz4.frame.BLOCKSIZE_MAX4MB)
	if level > 0:
		for s in srcs:
			os.remove(s[0])
	return p, out, count, n_src, time.time() - t

# -----------------------------------------------
# Phase 3: ordered concat, decompression overlapped with writes
# -----------------------------------------------
def concat_parts(part_paths, output_file):
	q = queue.Queue(maxsize=16)

	def reader():
		try:
			for path in part_paths:
				if path is None:
					continue
				with lz4.frame.open(path, mode="rb") as f:
					while True:
						b = f.read(COPY_BLOCK)
						if not b:
							break
						q.put(b)
				os.remove(path)
		except BaseException as e:
			q.put(e)
			return
		q.put(None)

	th = threading.Thread(target=reader, daemon=True)
	th.start()
	written = 0
	next_report = 10 << 30
	with open(output_file, "wb", buffering=0) as out:
		while True:
			b = q.get()
			if b is None:
				break
			if isinstance(b, BaseException):
				raise b
			out.write(b)
			written += len(b)
			if written >= next_report:
				log("  written %.1f GB" % (written / float(1 << 30)))
				next_report += 10 << 30
	th.join()
	return written

# -----------------------------------------------
# Main
# -----------------------------------------------
def main():
	ap = argparse.ArgumentParser(description="Fully parallel MD5 hash sort + dedup")
	ap.add_argument("input", help="Input file to sort")
	ap.add_argument("-o", "--output", help="Output file (default: overwrite the input file)")
	ap.add_argument("--chunk-mb", type=int, default=CHUNK_MB,
					help="Input MB per phase-1 task (default: %d)" % CHUNK_MB)
	ap.add_argument("--workers", type=int, default=NUM_WORKERS,
					help="Parallel processes (default: all cores = %d)" % NUM_WORKERS)
	ap.add_argument("--parts", type=int, default=0,
					help="Key-range partitions (default: workers * %d)" % PARTS_PER_WORKER)
	ap.add_argument("--fanin", type=int, default=FANIN,
					help="Max files merged at once per partition (default: %d)" % FANIN)
	ap.add_argument("--tmp-dir", default=TEMP_DIR)
	args = ap.parse_args()

	if not os.path.exists(args.input):
		print("Error: file '%s' not found." % args.input, file=sys.stderr)
		sys.exit(1)

	output_file = args.output if args.output else args.input
	tmp_output = output_file + ".sorting.tmp"
	size = os.path.getsize(args.input)
	workers = max(1, args.workers)
	want_parts = args.parts if args.parts > 0 else workers * PARTS_PER_WORKER
	fanin = max(2, args.fanin)

	log("=" * 60)
	log("Input   : %s  (%.2f GB)" % (args.input, size / float(1 << 30)))
	log("Output  : %s" % output_file)
	log("Workers : %d processes  |  chunk %d MB  |  fan-in %d" % (workers, args.chunk_mb, fanin))
	log("=" * 60)

	if size == 0:
		open(tmp_output, "wb").close()
		os.replace(tmp_output, output_file)
		log("Empty input. Done.")
		return

	ranges = compute_ranges(args.input, size, max(1, args.chunk_mb) << 20)
	splitters = sample_splitters(args.input, size, want_parts)
	n_parts = len(splitters) + 1
	log("Plan    : %d chunks  x  %d partitions" % (len(ranges), n_parts))

	with tempfile.TemporaryDirectory(dir=args.tmp_dir) as tmp_dir:
		with Pool(processes=workers, initializer=init_worker,
				  initargs=(args.input, tmp_dir, splitters)) as pool:

			# ---- Phase 1 ----
			log("[1/3] Parallel read + sort + partition...")
			chunks = [None] * len(ranges)
			tasks = [(i, s, e) for i, (s, e) in enumerate(ranges)]
			done = 0
			total_lines = 0
			for cid, path, index, n_lines, n_uniq, el in pool.imap_unordered(sort_chunk, tasks, chunksize=1):
				chunks[cid] = (path, index)
				done += 1
				total_lines += n_lines
				log("  [chunk %5d] %9d lines -> %9d unique  [%5.1fs]  (%d/%d %5.1f%%)"
					% (cid, n_lines, n_uniq, el, done, len(ranges), 100.0 * done / len(ranges)))

			# ---- Phase 2 ----
			log("[2/3] Parallel merge of %d partitions..." % n_parts)
			mtasks = []
			for p in range(n_parts):
				srcs = [(path, idx[p][0], idx[p][1]) for path, idx in chunks if idx[p][1]]
				mtasks.append((p, srcs, fanin))
			mtasks.sort(key=lambda t: -sum(s[2] for s in t[1]))  # largest first
			part_paths = [None] * n_parts
			total = 0
			done = 0
			for p, path, count, n_src, el in pool.imap_unordered(merge_partition, mtasks, chunksize=1):
				part_paths[p] = path
				total += count
				done += 1
				log("  [part %5d] %4d slices -> %10d unique  [%5.1fs]  (%d/%d %5.1f%%)"
					% (p, n_src, count, el, done, n_parts, 100.0 * done / n_parts))

		for path, _ in chunks:
			try:
				os.remove(path)
			except OSError:
				pass

		# ---- Phase 3 ----
		log("[3/3] Writing output...")
		written = concat_parts(part_paths, tmp_output)

	os.replace(tmp_output, output_file)
	log("=" * 60)
	log("Done!  Input lines   : %d" % total_lines)
	log("       Unique lines  : %d" % total)
	log("       Output size   : %.2f GB" % (written / float(1 << 30)))
	log("       Total time    : %.1f s\a" % (time.time() - _t0))
	log("=" * 60)


if __name__ == "__main__":
	main()
