#!/usr/bin/env python3

# This software is
# Copyright (c) 2012-2018 Dhiru Kholia <dhiru at openwall.com>
# Copyright (c) 2019 Solar Designer
# Copyright (c) 2019 exploide
# Redistribution and use in source and binary forms, with or without
# modification, are permitted.  (This is a heavily cut-down "BSD license".)

import binascii
import glob
import mmap
import os
import struct
import sys


def hexstr(bytestr):
	return binascii.hexlify(bytestr).decode('ascii')


# BDB btree leaf page layout constants
BDB_BTREE_LEAF	= 5		# page type byte at offset 25
BDB_HDR_SIZE	= 26	# fixed page header length
BITEM_HDR		= 3		# item header: 2-byte length + 1-byte type


def _read_compact_size(buf, pos):
	"""Return (value, new_pos) or raise IndexError."""
	size = buf[pos]
	pos += 1
	if size == 253:
		(size,) = struct.unpack_from('<H', buf, pos); pos += 2
	elif size == 254:
		(size,) = struct.unpack_from('<I', buf, pos); pos += 4
	elif size == 255:
		(size,) = struct.unpack_from('<Q', buf, pos); pos += 8
	return size, pos


def _parse_mkey_value(vbuf):
	"""Parse mkey value bytes -> dict or None."""
	try:
		pos = 0
		n, pos = _read_compact_size(vbuf, pos)
		enc_key = vbuf[pos:pos + n]; pos += n
		n, pos = _read_compact_size(vbuf, pos)
		salt    = vbuf[pos:pos + n]; pos += n
		(method,) = struct.unpack_from('<I', vbuf, pos); pos += 4
		(iters,)  = struct.unpack_from('<I', vbuf, pos)
		return {
			'encrypted_key':         hexstr(enc_key),
			'salt':                  hexstr(salt),
			'nDerivationMethod':     method,
			'nDerivationIterations': iters,
		}
	except Exception:
		return None


def _scan_pages(data, pagesize, mkey_tag):
	"""Walk BDB btree leaf pages of given size, return parsed mkey or None."""
	num_pages = len(data) // pagesize
	for pno in range(num_pages):
		page = data[pno * pagesize:(pno + 1) * pagesize]
		if len(page) < BDB_HDR_SIZE:
			continue
		page_type = page[25]
		if page_type != BDB_BTREE_LEAF:
			continue
		num_entries = struct.unpack_from('<H', page, 20)[0]
		for i in range(num_entries):
			idx_off = BDB_HDR_SIZE + i * 2
			if idx_off + 2 > pagesize:
				break
			item_off = struct.unpack_from('<H', page, idx_off)[0]
			if item_off + BITEM_HDR > pagesize:
				continue
			item_len  = struct.unpack_from('<H', page, item_off)[0]
			item_type = page[item_off + 2]
			if item_type != 1:
				continue
			item_data = page[item_off + BITEM_HDR:item_off + BITEM_HDR + item_len]
			if item_data != mkey_tag:
				continue
			# value is the next entry
			next_idx_off = BDB_HDR_SIZE + (i + 1) * 2
			if next_idx_off + 2 > pagesize:
				continue
			val_off = struct.unpack_from('<H', page, next_idx_off)[0]
			if val_off + BITEM_HDR > pagesize:
				continue
			val_len  = struct.unpack_from('<H', page, val_off)[0]
			val_data = page[val_off + BITEM_HDR:val_off + BITEM_HDR + val_len]
			result = _parse_mkey_value(val_data)
			if result:
				return result
	return None


def _naive_scan(data, mkey_tag):
	"""No page structure: find mkey_tag anywhere, try to parse value after it."""
	pos = 0
	while True:
		idx = data.find(mkey_tag, pos)
		if idx == -1:
			break
		for offset in range(0, 32):
			vstart = idx + len(mkey_tag) + offset
			vbuf   = data[vstart:vstart + 200]
			result = _parse_mkey_value(vbuf)
			if result and 8 <= len(result['salt']) <= 72:
				return result
		pos = idx + 1
	return None


def _raw_scan_mkey(walletfile):
	MKEY_TAG = b'\x04mkey'
	try:
		with open(walletfile, 'rb') as f:
			try:
				data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
			except (mmap.error, ValueError):
				data = f.read()
	except IOError as e:
		sys.stderr.write("%s: cannot read file: %s\n" % (walletfile, e))
		return None

	try:
		for pagesize in (4096, 8192, 1024, 2048, 16384, 32768, 65536, 512):
			mkey = _scan_pages(data, pagesize, MKEY_TAG)
			if mkey:
				sys.stderr.write("%s: raw scan recovered mkey (pagesize=%d)\n" % (walletfile, pagesize))
				return mkey

		mkey = _naive_scan(data, MKEY_TAG)
		if mkey:
			sys.stderr.write("%s: naive byte scan recovered mkey\n" % walletfile)
		return mkey
	finally:
		if isinstance(data, mmap.mmap):
			data.close()


def process_wallet(walletfile, outfile):
	mkey = _raw_scan_mkey(walletfile)
	if mkey is None:
		sys.stderr.write("%s: no mkey found (not encrypted or unreadable)\n" % walletfile)
		return None

	cry_salt   = mkey['salt']
	cry_master = mkey['encrypted_key'][-64:]
	cry_rounds = mkey['nDerivationIterations']

	line = "$bitcoin$%s$%s$%s$%s$%s$2$00$2$00\n" % (
		len(cry_master), cry_master, len(cry_salt), cry_salt, cry_rounds
	)

	sys.stdout.write(line)
	outfile.write(line)
	outfile.flush()
	return cry_master


if __name__ == '__main__':
	# Single-file mode: called by the bash wrapper with a path argument
	if len(sys.argv) == 2:
		with open(os.devnull, 'w') as devnull:
			process_wallet(sys.argv[1], devnull)
		sys.exit(0)

	dat_files = sorted(glob.glob("*.dat"))
	if not dat_files:
		sys.stderr.write("No .dat files found in current directory\n")
		sys.exit(1)

	used_names = set()

	with open("hashes.txt", "a") as outfile:
		for walletfile in dat_files:
			sys.stderr.write("Processing: %s\n" % walletfile)
			cry_master = process_wallet(walletfile, outfile)
			if cry_master is None:
				continue

			candidate = cry_master + ".dat"
			n = 2
			while candidate in used_names or (os.path.exists(candidate) and candidate != walletfile):
				candidate = "%s (%02d).dat" % (cry_master, n)
				n += 1

			used_names.add(candidate)
			if candidate != walletfile:
				try:
					os.rename(walletfile, candidate)
					sys.stderr.write("%s -> %s\n" % (walletfile, candidate))
				except OSError as e:
					sys.stderr.write("Cannot rename %s: %s\n" % (walletfile, e))
			else:
				sys.stderr.write("%s: already named correctly\n" % walletfile)

	print('\a', end='', file=sys.stderr)
