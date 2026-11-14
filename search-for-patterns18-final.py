#!/usr/bin/env python3

# Search fixed-size records: write the whole record if any line matches a pattern.
# Record size is detected from the first empty line in the searched file.

import sys, os, time
from itertools import islice
from tqdm import tqdm

def detect_record(path):
	# Record size = number of lines before the first empty line, plus that empty line.
	n = 0
	with open(path, 'r', errors='ignore') as f:
		for line in f:
			n += 1
			if not line.rstrip('\n'):
				return n
	return 0

def main():
	if len(sys.argv) < 4:
		print(f'Usage: {sys.argv[0]} patterns_file search_in_file output_file')
		sys.exit(1)

	print('Loading patterns...', flush=True)
	t0 = time.perf_counter()
	with open(sys.argv[1], 'r') as f:
		patt = set(f.read().splitlines())
	elapsed = time.perf_counter() - t0
	secs = int(elapsed)
	ms = int((elapsed - secs) * 1000)
	print(f'Patterns loaded in {secs} s {ms} ms')
	print(f'Searching for {len(patt)} patterns...')

	RECORD = detect_record(sys.argv[2])
	if not RECORD:
		print('No empty line found - cannot detect record size.')
		sys.exit(1)
	print(f'Record size: {RECORD} lines (incl. empty line)')

	size = os.path.getsize(sys.argv[2])
	r = z = 0
	out_buf = []

	with open(sys.argv[2], 'r', errors='ignore') as infile, \
		 open(sys.argv[3], 'w') as outfile, \
		 tqdm(total=size, unit='B', unit_scale=True) as pbar:

		while True:
			raw = list(islice(infile, RECORD))
			if not raw:
				break
			pbar.update(sum(len(x) for x in raw))

			rec = [x.rstrip('\n') for x in raw]
			hits = sum(1 for line in rec if line in patt)
			if hits:
				r += 1
				z += hits
				out_buf.append('\n'.join(rec))
				if len(out_buf) >= 500:
					outfile.write('\n'.join(out_buf) + '\n')
					out_buf.clear()
				pbar.set_postfix_str(f'found={r} uniq={z}')

		if out_buf:
			outfile.write('\n'.join(out_buf) + '\n')

	print(f'Found: {r} ; Unique: {z}')
	print('\a', end='', file=sys.stderr)
	sys.stdout.flush()
	sys.stderr.flush()
	os._exit(0)		# skip freeing the huge pattern set and interpreter teardown

if __name__ == '__main__':
	main()
