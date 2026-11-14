#!/usr/bin/env python3

import os
import pickle
import sys
import tempfile


def save_var(obj, path):
	# Atomic write: dump to temp file in same dir, then replace target
	d = os.path.dirname(os.path.abspath(path))
	fd, tmp = tempfile.mkstemp(dir=d, prefix='.tmp_', suffix='.pkl')
	try:
		with os.fdopen(fd, 'wb') as f:
			pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
			f.flush()
			os.fsync(f.fileno())
		os.replace(tmp, path)
	except BaseException:
		if os.path.exists(tmp):
			os.remove(tmp)
		raise


def load_var(path, default=None):
	# Return default if file missing
	if not os.path.exists(path):
		return default
	with open(path, 'rb') as f:
		return pickle.load(f)


def main():
	path = sys.argv[1] if len(sys.argv) > 1 else 'data.pkl'

	data = {
		'name': 'test',
		'values': [1, 2, 3],
		'nested': {'a': 1.5, 'b': (True, None)},
		'raw': b'\x00\x01\x02',
	}

	save_var(data, path)
	print(f'Saved to {path} ({os.path.getsize(path)} bytes)')

	loaded = load_var(path)
	print(f'Loaded: {loaded}')
	print(f'Equal: {loaded == data}')

	print('\a', end='', file=sys.stderr)


if __name__ == '__main__':
	main()
