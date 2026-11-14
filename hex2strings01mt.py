#!/usr/bin/env python3

import os
import re
import sys
from datetime import datetime
from multiprocessing import Pool, cpu_count

from tqdm import tqdm

INPUT = 'input.txt'
OUTPUT = 'output.txt'

# separators allowed inside a hex line: whitespace, : - , ; _ . and 0x/\x prefixes
SEP = re.compile(r'(?:0[xX]|\\[xX]|[\s:\-,;_.])')
HEXONLY = re.compile(r'^[0-9a-fA-F]*$')


def hex2bytes(s):
	h = SEP.sub('', s)
	if not h or not HEXONLY.match(h):
		return None
	if len(h) & 1:
		h = h[:-1]
	if not h:
		return None
	return bytes.fromhex(h)


def clean(b):
	# decode valid UTF-8 sequences, drop invalid bytes (stray 0x80-0xFF),
	# then drop control code points: U+0000-U+001F, U+007F-U+009F
	t = b.decode('utf-8', errors='ignore')
	return ''.join(c for c in t if c >= ' ' and not ('\x7f' <= c <= '\x9f'))


def work(line):
	# returns (bytes consumed, output line or None)
	n = len(line)
	s = line.strip()
	if not s:
		return n, None
	b = hex2bytes(s)
	if b is None:
		return n, None
	r = clean(b)
	if not r:
		return n, None
	return n, r + '\n'


def lines(path):
	with open(path, 'r', encoding='utf-8', errors='ignore') as f:
		for l in f:
			yield l


def main():
	print(f'Input:  {INPUT}')
	print(f'Output: {OUTPUT}')
	start = datetime.now()
	print(f'Start:  {start}')
	size = os.path.getsize(INPUT)
	with Pool(cpu_count()) as p, open(OUTPUT, 'a', encoding='utf-8') as o, tqdm(total=size, unit='B', unit_scale=True, smoothing=0.1) as bar:
		for n, out in p.imap_unordered(work, lines(INPUT), chunksize=1000):
			if out is not None:
				o.write(out)
			bar.update(n)
	end = datetime.now()
	print(f'Start:   {start}')
	print(f'End:     {end}')
	print(f'Elapsed: {end - start}')
	print('\a', end='', file=sys.stderr)


if __name__ == '__main__':
	main()
