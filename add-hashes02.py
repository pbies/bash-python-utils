#!/usr/bin/env python3

import binascii
import hashlib
import os
import signal
import sys
from multiprocessing import Pool
from tqdm import tqdm

BATCH = 2000


def init():
	signal.signal(signal.SIGINT, signal.SIG_IGN)


def go(batch):
	out = bytearray()
	for line in batch:
		out += line
		out += b'\n'
		out += binascii.hexlify(hashlib.md5(line).digest())
		out += b'\n'
		out += binascii.hexlify(hashlib.sha256(line).digest())
		out += b'\n'
	return bytes(out)


def chunks(seq, n):
	for i in range(0, len(seq), n):
		yield seq[i:i + n]


def main():
	with open(sys.argv[1], 'rb') as f:
		content = f.read().splitlines()

	workers = os.cpu_count() or 1
	total = (len(content) + BATCH - 1) // BATCH

	pool = Pool(processes=workers, initializer=init)
	ok = False
	try:
		with open(sys.argv[2], 'wb', buffering=1024 * 1024) as o:
			for blob in tqdm(pool.imap_unordered(go, chunks(content, BATCH), chunksize=1), total=total, unit='batch', smoothing=0.05):
				o.write(blob)
		ok = True
	except KeyboardInterrupt:
		print('\nInterrupted, partial output kept', file=sys.stderr)
	finally:
		if ok:
			pool.close()
		else:
			pool.terminate()
		pool.join()

	if not ok:
		sys.exit(130)


if __name__ == '__main__':
	main()
