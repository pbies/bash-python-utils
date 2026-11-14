#!/usr/bin/env python3
"""
Merged snippets: Base58/Bech32/CashAddr, secp256k1, Bitcoin/LTC/DOGE/BCH/ETH
addresses, WIF, BIP39/BIP32 derivation, Keccak/EIP-55, misc utils.

Required: ecdsa
Optional: pycryptodome (fast Keccak; pure-Python fallback is built in)
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import math
import os
import platform
import random
import re
import secrets
import struct
import sys
import time
import unicodedata
from functools import wraps
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import ecdsa
from ecdsa import SigningKey, SECP256k1


# =========================================================================
# Constants
# =========================================================================

DEFAULT_BECH32_HRP = "cro"
path = "m/44'/0'/0'/0/0"

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
Gx = 55066263022277343669578718895168534326250603453777594175500187360389116729240
Gy = 32670510020758816978083085130507043184471273380659243275938904335757337482424
GPOINT = (Gx, Gy)
_P = P
_N = N
curve_order = N

_H = 0x80000000  # BIP32 hardened offset

HEX64_RE = re.compile(rb'[0-9a-fA-F]{64}')

__b58chars = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
__b58base = 58
ALPHABET = __b58chars
_B58_ALPHA = ALPHABET.encode('ascii')
BASE58_INDEX: Dict = {}
for _i, _c in enumerate(ALPHABET):
	BASE58_INDEX[_c] = _i
	BASE58_INDEX[ord(_c)] = _i

VERSION_NAMES = {
	0x80: 'BTC-mainnet',
	0xEF: 'BTC-testnet',
	0xB0: 'LTC',
	0x9E: 'DOGE',
	0xCC: 'DASH',
}


# =========================================================================
# Hashing
# =========================================================================

def sha256(b: bytes) -> bytes:
	return hashlib.sha256(b).digest()

def sha256_hex(b: bytes) -> str:
	return hashlib.sha256(b).hexdigest()

def sha256d(b: bytes) -> bytes:
	return sha256(sha256(b))

def ripemd160(b: bytes) -> bytes:
	h = hashlib.new("ripemd160")
	h.update(b)
	return h.digest()

def ripemd160_hex(b: bytes) -> str:
	return ripemd160(b).hex()

def hash160(data: bytes) -> bytes:
	return ripemd160(sha256(data))

hash_160 = hash160
Hash = sha256d
_sha256 = sha256
_ripemd160 = ripemd160
_hash160 = hash160
_dsha256 = sha256d


# =========================================================================
# Keccak-256 (Ethereum: 0x01 padding) + EIP-55
# =========================================================================

_KECCAK_RNDC = [
	0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
	0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
	0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
	0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
	0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
	0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
_KECCAK_ROTC = [
	1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 2, 14,
	27, 41, 56, 8, 25, 43, 62, 18, 39, 61, 20, 44,
]
_KECCAK_MASK = 0xFFFFFFFFFFFFFFFF


def _rol64(x: int, n: int) -> int:
	return ((x << n) | (x >> (64 - n))) & _KECCAK_MASK


def _keccak_f1600(s: List[int]) -> List[int]:
	for rnd in range(24):
		c = [s[x] ^ s[x + 5] ^ s[x + 10] ^ s[x + 15] ^ s[x + 20] for x in range(5)]
		d = [c[(x - 1) % 5] ^ _rol64(c[(x + 1) % 5], 1) for x in range(5)]
		for x in range(5):
			for y in range(5):
				s[x + 5 * y] ^= d[x]
		x, y = 1, 0
		current = s[x + 5 * y]
		for t in range(24):
			xn, yn = y, (2 * x + 3 * y) % 5
			idx = xn + 5 * yn
			current, s[idx] = s[idx], _rol64(current, _KECCAK_ROTC[t])
			x, y = xn, yn
		for yy in range(5):
			row = s[5 * yy:5 * yy + 5]
			for xx in range(5):
				s[5 * yy + xx] = row[xx] ^ ((~row[(xx + 1) % 5]) & row[(xx + 2) % 5] & _KECCAK_MASK)
		s[0] ^= _KECCAK_RNDC[rnd]
	return s


def _keccak256_pure(data: bytes) -> bytes:
	rate = 136
	state = [0] * 25
	padded = bytearray(data)
	padded.append(0x01)
	while len(padded) % rate != 0:
		padded.append(0x00)
	padded[-1] |= 0x80
	for offset in range(0, len(padded), rate):
		block = padded[offset:offset + rate]
		for i in range(rate // 8):
			state[i] ^= struct.unpack_from('<Q', block, i * 8)[0]
		_keccak_f1600(state)
	out = bytearray()
	for i in range(4):
		out += struct.pack('<Q', state[i])
	return bytes(out)


try:
	from Crypto.Hash import keccak as _pc_keccak

	def keccak256(data: bytes) -> bytes:
		return _pc_keccak.new(data=data, digest_bits=256).digest()
except ImportError:
	keccak256 = _keccak256_pure

_keccak256 = keccak256


def to_checksum(addr_lower: str) -> str:
	"""addr_lower: 40 lowercase hex chars, no 0x prefix."""
	h = keccak256(addr_lower.encode('ascii'))
	out = []
	for i, c in enumerate(addr_lower):
		if c > '9':
			nibble = (h[i >> 1] >> 4) if (i & 1) == 0 else (h[i >> 1] & 0x0f)
			out.append(c.upper() if nibble >= 8 else c)
		else:
			out.append(c)
	return '0x' + ''.join(out)


def to_checksum_address(address: str) -> str:
	"""EIP-55 for a 0x-prefixed address."""
	return to_checksum(address[2:].lower())


def is_checksum_valid(address: str) -> bool:
	return address == to_checksum_address(address)


def _eip55(addr_bytes: bytes) -> str:
	return to_checksum(addr_bytes.hex())


# =========================================================================
# Base58 / Base58Check
# =========================================================================

def b58encode(v: bytes) -> str:
	num = int.from_bytes(v, 'big')
	encoded = ''
	while num > 0:
		num, rem = divmod(num, 58)
		encoded = ALPHABET[rem] + encoded
	n_leading = len(v) - len(v.lstrip(b'\x00'))
	return '1' * n_leading + encoded


def b58decode(s, length: int | None = None) -> bytes | None:
	"""Accepts str or bytes. Raises ValueError on invalid char. Returns None on length mismatch."""
	if isinstance(s, (bytes, bytearray)):
		s = s.decode('ascii')
	num = 0
	for ch in s:
		try:
			num = num * 58 + BASE58_INDEX[ch]
		except KeyError:
			raise ValueError(f"invalid base58 char: {ch!r}") from None
	combined = num.to_bytes((num.bit_length() + 7) // 8, 'big') if num else b''
	n_leading = len(s) - len(s.lstrip('1'))
	result = b'\x00' * n_leading + combined
	if length is not None and len(result) != length:
		return None
	return result


def b58encode_check(payload: bytes) -> str:
	return b58encode(payload + sha256d(payload)[:4])


def b58decode_check(s) -> bytes:
	raw = b58decode(s)
	if len(raw) < 5:
		raise ValueError("base58check: too short")
	payload, checksum = raw[:-4], raw[-4:]
	if sha256d(payload)[:4] != checksum:
		raise ValueError("base58check: bad checksum")
	return payload


def b58check_encode(versioned_payload: bytes) -> str:
	return b58encode_check(versioned_payload)

_b58enc = b58encode_check


def base58_decode(s) -> bytes:
	return b58decode(s)


def EncodeBase58Check(secret: bytes) -> str:
	return b58encode_check(secret)


def DecodeBase58Check(sec: str) -> bytes | None:
	try:
		return b58decode_check(sec)
	except ValueError:
		return None


def b58c_to_bytes(s: str) -> bytes:
	return b58decode_check(s)

def bytes_to_b58c(b: bytes) -> str:
	return b58encode_check(b)

def b58c_to_hex(s: str) -> str:
	return b58decode_check(s).hex()

def hex_to_b58c(h: str) -> str:
	return b58encode_check(bytes.fromhex(h))


# =========================================================================
# Bech32 / Bech32m / CashAddr
# =========================================================================

_BECH32_CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
_CASHADDR_CHARSET = _BECH32_CHARSET


def _convertbits(data, frombits: int, tobits: int, pad: bool = True):
	acc = 0
	bits = 0
	ret = []
	maxv = (1 << tobits) - 1
	for v in data:
		acc = (acc << frombits) | v
		bits += frombits
		while bits >= tobits:
			bits -= tobits
			ret.append((acc >> bits) & maxv)
	if pad:
		if bits:
			ret.append((acc << (tobits - bits)) & maxv)
	elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
		return None
	return ret

convertbits = _convertbits


def _bech32_polymod(values) -> int:
	GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
	chk = 1
	for v in values:
		b = chk >> 25
		chk = ((chk & 0x1ffffff) << 5) ^ v
		for i in range(5):
			chk ^= GEN[i] if ((b >> i) & 1) else 0
	return chk


def _bech32_hrp_expand(hrp: str) -> List[int]:
	return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_create(hrp: str, data: List[int], const: int) -> str:
	chk = _bech32_polymod(_bech32_hrp_expand(hrp) + data + [0] * 6) ^ const
	checksum = [(chk >> (5 * (5 - i))) & 31 for i in range(6)]
	return hrp + '1' + ''.join(_BECH32_CHARSET[d] for d in data + checksum)


def bech32_encode(hrp: str, data: List[int]) -> str:
	"""Plain Bech32 (const=1) over 5-bit data — same API as the bech32 package."""
	return _bech32_create(hrp, list(data), 1)


def _bech32_encode(hrp: str, witver: int, witprog: bytes) -> str:
	"""SegWit address: Bech32 for v0, Bech32m for v1+."""
	data = [witver] + _convertbits(witprog, 8, 5)
	const = 0x2bc830a3 if witver != 0 else 1
	return _bech32_create(hrp, data, const)


def _cashaddr_polymod(values: List[int]) -> int:
	c = 1
	generator = [0x98f2bc8e61, 0x79b76d99e2, 0xf33e5fb3c4, 0xae2eabe2a8, 0x1e4f43e470]
	for d in values:
		c0 = c >> 35
		c = ((c & 0x07ffffffff) << 5) ^ d
		for i in range(5):
			if (c0 >> i) & 1:
				c ^= generator[i]
	return c ^ 1


def _cashaddr_encode(prefix: str, version_byte: int, h160: bytes, with_prefix: bool = False) -> str:
	payload = bytes([version_byte]) + h160
	p5 = _convertbits(payload, 8, 5, True)
	prefix_expanded = [ord(x) & 0x1f for x in prefix] + [0]
	poly = _cashaddr_polymod(prefix_expanded + p5 + [0] * 8)
	checksum = [(poly >> 5 * (7 - i)) & 31 for i in range(8)]
	body = ''.join(_CASHADDR_CHARSET[d] for d in p5 + checksum)
	return prefix + ':' + body if with_prefix else body


# =========================================================================
# Conversions
# =========================================================================

def bytes_to_string(b: bytes) -> str:
	return b.decode("utf-8")

def bytes_to_int(b: bytes) -> int:
	return int.from_bytes(b, "big")

def bytes_to_hex(b: bytes) -> str:
	return b.hex()

def hex_to_bytes(h: str) -> bytes:
	return bytes.fromhex(h)

def hex_to_int(h: str) -> int:
	return int(h, 16)

def hex_to_string(h: str) -> str:
	return bytes.fromhex(h).decode("utf-8")

def hex2str(hex_str: str) -> str:
	return ''.join(chr(int(hex_str[i:i + 2], 16)) for i in range(0, len(hex_str), 2))

def int_to_bytes(value: int, length: int | None = None) -> bytes:
	if value == 0 and not length:
		return b"\x00"
	return value.to_bytes(length or (value.bit_length() + 7) // 8, "big")

def int_to_bytes3(value: int, length: int | None = None) -> bytes:
	if value == 0 and not length:
		return b"\x00"
	if not length:
		length = (value.bit_length() + 7) // 8 or 1
	return value.to_bytes(length, "big")

def int_to_bytes4(number: int, length: int) -> bytes:
	return number.to_bytes(length, "big")

def int_to_hex(i: int, hexdigits: int | None = None) -> str:
	h = format(i, "x")
	return h.zfill(hexdigits) if hexdigits else h

def int_to_hex2(n: int, hexdigits: int) -> str:
	h = hex(n)[2:]
	return '0' * (hexdigits - len(h)) + h

def int_to_hex64(i: int) -> str:
	return f"{i:064x}"

def int_to_pvk(x: int) -> str:
	return hex(x)[2:].zfill(64)

def int_to_str(i: int) -> str:
	return str(i)

def str_to_bytes(s: str) -> bytes:
	return s.encode()

def str_to_hex(s: str) -> str:
	return s.encode().hex()

def reverse_string(s: str) -> str:
	return s[::-1]

reverseString = reverse_string

def reverse_by_bytes(hex_str: str) -> str:
	hex_str = hex_str.replace(" ", "").lower()
	if len(hex_str) % 2 != 0:
		raise ValueError("Hex string must have even length")
	pairs = [hex_str[i:i + 2] for i in range(0, len(hex_str), 2)]
	return "".join(pairs[::-1])

def reverse_hex_pairs(hex_str: str) -> str:
	hex_str = hex_str.replace(" ", "").replace("0x", "")
	pairs = [hex_str[i:i + 2] for i in range(0, len(hex_str), 2)]
	return "".join(reversed(pairs))

def rev_hex(s: str) -> str:
	return bytes.fromhex(s)[::-1].hex()

def intToBytes(s: int) -> bytes:
	return chr(s).encode('utf-8')

def intToBytes2(s: int) -> bytearray:
	return bytearray([s])

def thousands_separator(i) -> str:
	return '{:,}'.format(i)

def growing_range(mid: int, x: int) -> List[int]:
	start = mid - x
	end = mid + x
	rng = [0] * (x * 2 - 1)
	rng[::2], rng[1::2] = range(mid, end), range(mid - 1, start, -1)
	return rng


# =========================================================================
# EC arithmetic (pure Python)
# =========================================================================

def modinv(a: int, n: int = P) -> int:
	return pow(a, -1, n)


def inverse_mod(a: int, m: int) -> int:
	if a < 0 or m <= a:
		a = a % m
	c, d = a, m
	uc, vc, ud, vd = 1, 0, 0, 1
	while c != 0:
		q, c, d = divmod(d, c) + (c,)
		uc, vc, ud, vd = ud - q * uc, vd - q * vc, uc, vc
	assert d == 1
	return ud if ud > 0 else ud + m


def ECadd(a: Tuple[int, int], b: Tuple[int, int]) -> Tuple[int, int]:
	L = ((b[1] - a[1]) * modinv(b[0] - a[0], P)) % P
	x = (L * L - a[0] - b[0]) % P
	y = (L * (a[0] - x) - a[1]) % P
	return x, y


def ECdouble(a: Tuple[int, int]) -> Tuple[int, int]:
	L = ((3 * a[0] * a[0]) * modinv(2 * a[1], P)) % P
	x = (L * L - 2 * a[0]) % P
	y = (L * (a[0] - x) - a[1]) % P
	return x, y


def EccMultiply(gen_point: Tuple[int, int], scalar: int) -> Tuple[int, int]:
	if scalar <= 0 or scalar >= N:
		raise ValueError("Invalid scalar/private key")
	Q = None
	Np = gen_point
	while scalar:
		if scalar & 1:
			Q = Np if Q is None else ECadd(Q, Np)
		Np = ECdouble(Np)
		scalar >>= 1
	return Q


# =========================================================================
# Public keys
# =========================================================================

def privkey_to_pubkey(privkey: bytes, *, compressed: bool = True) -> bytes:
	"""33 B compressed or 65 B uncompressed."""
	if not isinstance(privkey, (bytes, bytearray)) or len(privkey) != 32:
		raise ValueError("privkey must be exactly 32 bytes")
	vk = SigningKey.from_string(bytes(privkey), curve=SECP256k1).get_verifying_key()
	x = vk.pubkey.point.x()
	y = vk.pubkey.point.y()
	if compressed:
		return (b"\x03" if (y & 1) else b"\x02") + x.to_bytes(32, "big")
	return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


def pubkey_from_priv_int(priv_int: int, compressed: bool = True) -> bytes:
	return privkey_to_pubkey(priv_int.to_bytes(32, "big"), compressed=compressed)


def pvk_to_pubkey(key: bytes | str) -> str:
	"""priv (bytes or hex) -> uncompressed pubkey hex (04||X||Y)."""
	key_bytes = bytes.fromhex(key) if isinstance(key, str) else bytes(key)
	return privkey_to_pubkey(key_bytes, compressed=False).hex()


def decompress_pubkey(pk: bytes) -> bytes:
	if not isinstance(pk, (bytes, bytearray)) or len(pk) != 33 or pk[0] not in (2, 3):
		raise ValueError("expected 33-byte compressed pubkey")
	x = int.from_bytes(pk[1:], "big")
	alpha = (pow(x, 3, P) + 7) % P
	y = pow(alpha, (P + 1) // 4, P)
	if (y & 1) != (pk[0] & 1):
		y = (-y) % P
	return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


def compressedToUncompressed(hex_compressed: str) -> str:
	return decompress_pubkey(bytes.fromhex(hex_compressed)).hex()


def compress_pubkey(pk: bytes) -> bytes:
	if not (len(pk) == 65 and pk[0] == 0x04):
		raise ValueError("expected 65-byte uncompressed pubkey")
	y = int.from_bytes(pk[33:], "big")
	return bytes([0x02 if y % 2 == 0 else 0x03]) + pk[1:33]


def compress_pubkey_from_uncompressed_hex(uncompressed_hex: str) -> str:
	"""HEX 04||X||Y -> HEX 02/03||X."""
	return compress_pubkey(bytes.fromhex(uncompressed_hex)).hex()


def _pub_bytes(pk, compressed: bool = True) -> bytes:
	"""Accepts raw pubkey bytes or any object with .format(compressed=...) (e.g. coincurve.PublicKey)."""
	if hasattr(pk, 'format'):
		return pk.format(compressed=compressed)
	pk = bytes(pk)
	if compressed and len(pk) == 65:
		return compress_pubkey(pk)
	if not compressed and len(pk) == 33:
		return decompress_pubkey(pk)
	return pk


def private_to_hex_publics(hex_private_key: str) -> Tuple[str, str]:
	"""HEX priv -> (uncompressed_pub_hex, compressed_pub_hex), uppercase."""
	priv = bytes.fromhex(hex_private_key)
	return (privkey_to_pubkey(priv, compressed=False).hex().upper(),
			privkey_to_pubkey(priv, compressed=True).hex().upper())


# =========================================================================
# WIF
# =========================================================================

def pvk_to_wif(z: bytes | str, *, compressed: bool = True, version: int = 0x80) -> str:
	key = bytes.fromhex(z) if isinstance(z, str) else bytes(z)
	if len(key) != 32:
		raise ValueError("private key must be 32 bytes")
	return b58encode_check(bytes([version]) + key + (b"\x01" if compressed else b""))


def pvk_to_wif2(key_hex: str, *, compressed: bool = True) -> str:
	return pvk_to_wif(bytes.fromhex(key_hex), compressed=compressed)


def getWif(privkey: bytes, *, compressed: bool = True) -> str:
	return pvk_to_wif(privkey, compressed=compressed)


def wif_from_priv_int(priv_int: int, compressed: bool = True, mainnet: bool = True) -> str:
	return pvk_to_wif(priv_int.to_bytes(32, "big"), compressed=compressed,
					  version=0x80 if mainnet else 0xEF)


def int_to_b58c_wif(n: int, *, compressed: bool = True) -> str:
	if not (1 <= n < N):
		raise ValueError("value outside secp256k1 range")
	return pvk_to_wif(n.to_bytes(32, "big"), compressed=compressed)


def _wif(privkey: bytes, version: int = 0x80) -> str:
	return pvk_to_wif(privkey, compressed=True, version=version)

def _wif_compressed(privkey: bytes) -> str:
	return pvk_to_wif(privkey, compressed=True)

def _wif_uncompressed(privkey: bytes) -> str:
	return pvk_to_wif(privkey, compressed=False)


def wif_to_pvk(wif: str) -> str:
	"""Payload after the version byte, hex (includes 01 suffix for compressed WIF)."""
	return b58decode_check(wif)[1:].hex()


def wif_to_private_key(wif: str) -> bytes:
	"""WIF (mainnet) -> raw 32 B key."""
	decoded = b58decode_check(wif)
	if len(decoded) == 34 and decoded[0] == 0x80 and decoded[-1] == 0x01:
		return decoded[1:-1]
	if len(decoded) == 33 and decoded[0] == 0x80:
		return decoded[1:]
	raise ValueError("invalid WIF")


def wif_to_key(wif: str) -> Tuple[bytes, bytes]:
	"""Any-network WIF -> (version_byte, 32 B key)."""
	raw = b58decode(wif)
	if len(raw) < 5:
		raise ValueError("WIF too short: " + wif)
	payload, checksum = raw[:-4], raw[-4:]
	if sha256d(payload)[:4] != checksum:
		raise ValueError("bad checksum: " + wif)
	version = payload[0:1]
	if len(payload) == 34 and payload[-1] == 0x01:
		key = payload[1:-1]
	elif len(payload) == 33:
		key = payload[1:]
	else:
		raise ValueError("unexpected payload length (" + str(len(payload)) + "): " + wif)
	return version, key


def key_to_wif(version: bytes, key: bytes, compressed: bool) -> str:
	return b58encode_check(version + key + (b'\x01' if compressed else b''))


def convert(wif: str) -> Tuple[str, str]:
	"""WIF -> (compressed_wif, uncompressed_wif)."""
	version, key = wif_to_key(wif.strip())
	return key_to_wif(version, key, True), key_to_wif(version, key, False)


def validate_wif(candidate) -> dict | None:
	try:
		raw = b58decode(candidate)
	except (KeyError, ValueError, UnicodeDecodeError):
		return None
	if len(raw) not in (37, 38):
		return None
	payload, checksum = raw[:-4], raw[-4:]
	if sha256d(payload)[:4] != checksum:
		return None
	version = payload[0]
	if version not in VERSION_NAMES:
		return None
	if len(payload) == 34:
		if payload[-1] != 0x01:
			return None
		compressed = True
	elif len(payload) == 33:
		compressed = False
	else:
		return None
	return {'network': VERSION_NAMES[version], 'compressed': compressed}


# =========================================================================
# Bitcoin addresses
# =========================================================================

def pubkey_to_p2pkh_address(pubkey_bytes: bytes, mainnet: bool = True) -> str:
	return b58encode_check((b'\x00' if mainnet else b'\x6f') + hash160(pubkey_bytes))


def pubkey_to_addr(pubkey_hex: str) -> str:
	return pubkey_to_p2pkh_address(bytes.fromhex(pubkey_hex))


def pvk_to_addr(pvk: bytes | str) -> str:
	"""Uncompressed P2PKH."""
	return pubkey_to_addr(pvk_to_pubkey(pvk))


def pvk_bin_to_addr(pvk: bytes, *, compressed: bool = True) -> str:
	return pubkey_to_p2pkh_address(privkey_to_pubkey(pvk, compressed=compressed))


def private_key_to_address(private_key_bytes: bytes, *, compressed: bool = True) -> str:
	return pvk_bin_to_addr(private_key_bytes, compressed=compressed)


def getPublicKey(privkey: bytes) -> str:
	"""Original name kept; returns compressed P2PKH address."""
	return pvk_bin_to_addr(privkey, compressed=True)


def hex_public_to_public_addresses(hex_publics: List[str]) -> Tuple[str, str]:
	"""[uncompressed_hex, compressed_hex] -> (addr_uncompressed, addr_compressed)."""
	u, c = hex_publics
	return pubkey_to_p2pkh_address(bytes.fromhex(u)), pubkey_to_p2pkh_address(bytes.fromhex(c))


def _p2pkh_versioned(pubkey, version: int = 0x00) -> str:
	return b58encode_check(bytes([version]) + hash160(_pub_bytes(pubkey)))


def _p2pkh(pubkey) -> str:
	"""Raw bytes are hashed as given; key objects are compressed."""
	if hasattr(pubkey, 'format'):
		pubkey = pubkey.format(compressed=True)
	return b58encode_check(b'\x00' + hash160(bytes(pubkey)))


def _p2pkh_ltc(pubkey) -> str:
	return _p2pkh_versioned(pubkey, 0x30)


def _p2pkh_doge(pubkey) -> str:
	return _p2pkh_versioned(pubkey, 0x1E)


def _p2sh_p2wpkh(pubkey) -> str:
	redeem = b'\x00\x14' + hash160(_pub_bytes(pubkey))
	return b58encode_check(b'\x05' + hash160(redeem))


def _p2wpkh(pubkey) -> str:
	return _bech32_encode('bc', 0, hash160(_pub_bytes(pubkey)))


def _p2wsh_p2pk(pubkey) -> str:
	pub = _pub_bytes(pubkey)
	witness_script = bytes([len(pub)]) + pub + b'\xac'
	return _bech32_encode('bc', 0, sha256(witness_script))


def _p2wsh_p2wpkh(pubkey) -> str:
	"""Actually P2SH-P2WSH wrapping a P2PK witness script (name kept)."""
	pub = _pub_bytes(pubkey)
	witness_script = bytes([len(pub)]) + pub + b'\xac'
	redeem = b'\x00\x20' + sha256(witness_script)
	return b58encode_check(b'\x05' + hash160(redeem))


def _p2tr(pubkey) -> str:
	"""BIP86 key-path P2TR: Q = lift_x(x) + H_TapTweak(x)*G."""
	xonly = _pub_bytes(pubkey)[1:]
	internal = decompress_pubkey(b'\x02' + xonly)
	ip = (int.from_bytes(internal[1:33], 'big'), int.from_bytes(internal[33:], 'big'))
	tag_hash = sha256(b'TapTweak')
	t = int.from_bytes(sha256(tag_hash + tag_hash + xonly), 'big')
	if t >= N:
		raise ValueError("invalid tweak")
	q = ECadd(ip, EccMultiply(GPOINT, t))
	return _bech32_encode('bc', 1, q[0].to_bytes(32, 'big'))


def _bch_cashaddr(pubkey) -> str:
	return _cashaddr_encode('bitcoincash', 0, hash160(_pub_bytes(pubkey)))


# =========================================================================
# Cosmos-like Bech32
# =========================================================================

def pubkey_to_address(pubkey: bytes, *, hrp: str = DEFAULT_BECH32_HRP) -> str:
	if not isinstance(pubkey, (bytes, bytearray)):
		raise TypeError("pubkey must be bytes")
	five_bit = _convertbits(hash160(bytes(pubkey)), 8, 5, True)
	return bech32_encode(hrp, five_bit)


def privkey_to_address(privkey: bytes, *, hrp: str = DEFAULT_BECH32_HRP) -> str:
	return pubkey_to_address(privkey_to_pubkey(privkey), hrp=hrp)


# =========================================================================
# Ethereum
# =========================================================================

def priv_to_addr(sk_bytes: bytes) -> bytes:
	"""20-byte ETH address for a 32-byte private key."""
	pub = privkey_to_pubkey(sk_bytes, compressed=False)[1:]
	return keccak256(pub)[12:]


def _eth_address(pubkey) -> str:
	uncompressed = _pub_bytes(pubkey, compressed=False)[1:]
	return _eip55(keccak256(uncompressed)[-20:]).lower()


# =========================================================================
# Random private keys
# =========================================================================

def generate_random_private_key() -> str:
	"""secrets — cryptographic."""
	return secrets.token_hex(32)

def generate_random_private_key1() -> str:
	"""random.getrandbits — NOT cryptographic."""
	return hex(random.getrandbits(256))[2:].zfill(64)

def generate_random_private_key2() -> str:
	"""os.urandom — cryptographic."""
	return os.urandom(32).hex()

def generate_random_private_key3() -> str:
	"""random.randint in [1, N-1] — NOT cryptographic."""
	return hex(random.randint(1, N - 1))[2:].zfill(64)

def generate_random_private_key4() -> str:
	return secrets.token_hex(32)


def entropy_to_pvk(e: str) -> str | None:
	entropy_int = int(e, 16)
	if not (1 <= entropy_int < N):
		return None
	return SigningKey.from_secret_exponent(entropy_int, curve=SECP256k1).to_string().hex()


# =========================================================================
# BIP39 / BIP32 / derivation templates
# =========================================================================

def _coin_profile(purpose: Optional[int], coin_type: Optional[int]):
	"""-> (label, addr_fn(pubkey)->str, wif_version_or_None)."""
	if coin_type == 0:
		if purpose == 44:
			return 'BTC-p2pkh', _p2pkh, 0x80
		if purpose == 49:
			return 'BTC-p2sh-segwit', _p2sh_p2wpkh, 0x80
		if purpose == 84:
			return 'BTC-bech32', _p2wpkh, 0x80
		if purpose == 86:
			return 'BTC-taproot', _p2tr, 0x80
	if coin_type == 60:
		return 'ETH', _eth_address, None
	if coin_type == 2:
		return 'LTC-p2pkh', _p2pkh_ltc, 0xB0
	if coin_type == 145:
		return 'BCH-cashaddr', _bch_cashaddr, 0x80
	if coin_type == 3:
		return 'DOGE-p2pkh', _p2pkh_doge, 0x9E
	raise ValueError(f"no address encoder for purpose={purpose} coin_type={coin_type}")


def _mnemonic_to_seed(mnemonic: str, passphrase: str = '') -> bytes:
	mnemonic_n = unicodedata.normalize('NFKD', mnemonic)
	salt = 'mnemonic' + unicodedata.normalize('NFKD', passphrase)
	return hashlib.pbkdf2_hmac('sha512', mnemonic_n.encode('utf-8'), salt.encode('utf-8'), 2048, dklen=64)


def _validate_mnemonic(words: List[str], word_to_index: Dict[str, int]) -> bool:
	n = len(words)
	if n not in (12, 15, 18, 21, 24):
		return False
	try:
		indices = [word_to_index[w] for w in words]
	except KeyError:
		return False
	val = 0
	for idx in indices:
		val = (val << 11) | idx
	total_bits = n * 11
	checksum_bits = total_bits // 33
	ent_bits = total_bits - checksum_bits
	entropy = val >> checksum_bits
	checksum = val & ((1 << checksum_bits) - 1)
	expected = sha256(entropy.to_bytes(ent_bits // 8, 'big'))[0] >> (8 - checksum_bits)
	return checksum == expected


def _bip32_master(seed: bytes) -> Tuple[bytes, bytes]:
	I = hmac.new(b'Bitcoin seed', seed, hashlib.sha512).digest()
	return I[:32], I[32:]


def _ckd_priv(priv: bytes, cc: bytes, index: int) -> Tuple[bytes, bytes]:
	if index & _H:
		data = b'\x00' + priv + index.to_bytes(4, 'big')
	else:
		data = privkey_to_pubkey(priv, compressed=True) + index.to_bytes(4, 'big')
	I = hmac.new(cc, data, hashlib.sha512).digest()
	il = int.from_bytes(I[:32], 'big')
	if il >= N:
		raise ValueError('invalid IL')
	child = (il + int.from_bytes(priv, 'big')) % N
	if child == 0:
		raise ValueError('zero child')
	return child.to_bytes(32, 'big'), I[32:]


def _derive(priv: bytes, cc: bytes, path_ints: Iterable[int]) -> Tuple[bytes, bytes]:
	for index in path_ints:
		priv, cc = _ckd_priv(priv, cc, index)
	return priv, cc


def _parse_path(p: str) -> List[int]:
	"""'m/44'/0'/0'/0/0' -> list of ints with hardened bit."""
	parts = p.split('/')
	if parts[0] != 'm':
		raise ValueError(f"bad derivation path: {p}")
	out = []
	for comp in parts[1:]:
		hardened = comp.endswith(("'", 'h', 'H'))
		v = int(comp[:-1] if hardened else comp)
		out.append(v | _H if hardened else v)
	return out


def _build_derivation_entry(tmpl: str) -> dict:
	parts = tmpl.split('/')
	if parts[0] != 'm':
		raise ValueError(f"bad derivation path (must start with 'm'): {tmpl}")
	parsed: List[Optional[int]] = []
	var_idx = None
	for pos, comp in enumerate(parts[1:]):
		hardened = comp.endswith(("'", 'h', 'H'))
		core = comp[:-1] if hardened else comp
		if core == 'i':
			if var_idx is not None:
				raise ValueError(f"path has more than one 'i': {tmpl}")
			var_idx = pos
			parsed.append(None)
		else:
			val = int(core)
			if hardened:
				val |= _H
			parsed.append(val)
	if var_idx is None:
		raise ValueError(f"path has no 'i' placeholder: {tmpl}")
	purpose = parsed[0] & ~_H if parsed[0] is not None else None
	coin_type = parsed[1] & ~_H if len(parsed) > 1 and parsed[1] is not None else None
	label, addr_fn, wif_version = _coin_profile(purpose, coin_type)
	return {
		'template': tmpl,
		'template_parts': parts,
		'var_idx': var_idx,
		'prefix': parsed[:var_idx],
		'suffix': parsed[var_idx + 1:],
		'label': label,
		'addr_fn': addr_fn,
		'wif_version': wif_version,
	}


def _load_derivations(file_path: Path) -> List[dict]:
	entries = []
	for line in Path(file_path).read_text(encoding='utf-8').splitlines():
		line = line.strip()
		if not line:
			continue
		tmpl = line.split('\t', 1)[1].strip() if '\t' in line else line
		if tmpl:
			entries.append(_build_derivation_entry(tmpl))
	if not entries:
		raise ValueError(f"no derivation paths found in {file_path}")
	return entries


# =========================================================================
# File / text utils
# =========================================================================

def _fast_count_lines(file_path, bufsize: int = 1024 * 1024) -> int:
	"""Counts lines; a final line without trailing newline is counted."""
	cnt = 0
	last = b''
	with open(file_path, 'rb', buffering=bufsize) as f:
		while True:
			chunk = f.read(bufsize)
			if not chunk:
				break
			cnt += chunk.count(b'\n')
			last = chunk[-1:]
	if last and last != b'\n':
		cnt += 1
	return cnt

def _fast_count_lines2(file_path: Path, bufsize: int = 1024 * 1024) -> int:
	return _fast_count_lines(file_path, bufsize)

def count_lines(file_path) -> int:
	return _fast_count_lines(file_path)

lines = count_lines
countLines = count_lines


def st(path_or_iterable: str | Path | Iterable[str]) -> List[str]:
	"""Stripped lines from a file path or an iterable of lines."""
	if isinstance(path_or_iterable, (str, Path)):
		with open(path_or_iterable, "r", encoding="utf-8", errors="replace") as f:
			return [line.strip() for line in f]
	return [line.strip() for line in path_or_iterable]


def read_jsonfile(filename):
	with open(filename, 'r', encoding='utf-8') as f:
		return json.load(f)

def write_jsonfile(filename, array):
	with open(filename, 'w', encoding='utf-8') as f:
		f.write(json.dumps(array, sort_keys=True, indent=4))

def dump(filename, data):
	with open(filename, 'w', encoding='utf-8') as f:
		json.dump(data, f, ensure_ascii=False, indent=4)


def substring_after(s: str, delim: str) -> str:
	return s.partition(delim)[2]

def substring_before(s: str, delim: str) -> str:
	return s.partition(delim)[0]

def find_all_matches(pattern: str, string: str) -> List[str]:
	"""Non-overlapping matches."""
	return [m.group(0) for m in re.finditer(pattern, string)]

def find_all_matches_overlapping(pattern: str, string: str) -> List[str]:
	pat = re.compile(pattern)
	pos = 0
	out = []
	while (match := pat.search(string, pos)) is not None:
		pos = match.start() + 1
		out.append(match[0])
	return out

def one_element_in(a, string) -> bool:
	return any(i in string for i in a)


# =========================================================================
# Formatting / console / timing
# =========================================================================

def human(n) -> str:
	units = ['', 'K', 'M', 'G', 'T', 'P', 'E']
	i = 0
	x = float(n)
	while x >= 1000.0 and i < len(units) - 1:
		x /= 1000.0
		i += 1
	return f"{x:.2f}{units[i]}"

def human_size(n) -> str:
	for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
		if n < 1024 or unit == 'TB':
			return '%.1f%s' % (n, unit)
		n /= 1024.0

def human_time(seconds) -> str:
	if seconds < 0 or seconds != seconds or seconds == float('inf'):
		return '--:--:--'
	seconds = int(seconds)
	h, rem = divmod(seconds, 3600)
	m, s = divmod(rem, 60)
	return '%d:%02d:%02d' % (h, m, s)

def format_elapsed(seconds) -> str:
	"""H:MM:SS.mmm"""
	h = int(seconds // 3600)
	m = int((seconds % 3600) // 60)
	s = seconds % 60
	return f'{h}:{m:02d}:{s:06.3f}'

def fmt_elapsed(s) -> str:
	s = int(s)
	return "%02d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)

def fmt_rate(r) -> str:
	if r >= 1e6:
		return "%.2f Mkey/s" % (r / 1e6)
	if r >= 1e3:
		return "%.2f kkey/s" % (r / 1e3)
	return "%.1f key/s" % r


def systype() -> str:
	s = platform.system()
	if s == "Darwin":
		return 'Mac'
	if s == "Windows":
		return 'Win'
	return 'Linux'

def cls():
	os.system('cls' if os.name == 'nt' else 'clear')

def clear_screen():
	sys.stdout.write('\033[2J\033[H')
	sys.stdout.flush()

def bell():
	print('\a', end='', file=sys.stderr, flush=True)

def beep():
	try:
		import winsound
		winsound.Beep(880, 300)
	except Exception:
		sys.stdout.write("\a")
		sys.stdout.flush()


def log(message: str):
	ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	with open("log.txt", "a", encoding="utf-8") as f:
		f.write(f"{ts} {message}\n")
	print(f"{ts} {message}", flush=True)

def log_step(message: str):
	print(f'[{datetime.datetime.now().strftime("%H:%M:%S")}] {message}')


class Timer:
	"""with Timer(): ..."""
	def __enter__(self):
		self.start = time.perf_counter()
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		self.end = time.perf_counter()
		print(f"This took: {self.end - self.start: .5f} seconds")


def timer(func, verbose_flag=None):
	"""Decorator. verbose_flag: None (always print) or a one-element list [bool]."""
	@wraps(func)
	def wrapper(*args, **kwargs):
		func_start = time.time()
		result = func(*args, **kwargs)
		if verbose_flag is None or (isinstance(verbose_flag, list) and verbose_flag[0]):
			print(f'  [{func.__name__}] took {time.time() - func_start:.4f}s')
		return result
	return wrapper


# =========================================================================
# BST
# =========================================================================

class Node:
	def __init__(self, data):
		self.left = None
		self.right = None
		self.data = data

	def insert(self, data):
		if data < self.data:
			if self.left is None:
				self.left = Node(data)
			else:
				self.left.insert(data)
		elif data > self.data:
			if self.right is None:
				self.right = Node(data)
			else:
				self.right.insert(data)


def buildTree(sorted_values: list, start: int, end: int) -> Node | None:
	if start > end:
		return None
	mid = start + (end - start) // 2
	node = Node(sorted_values[mid])
	node.left = buildTree(sorted_values, start, mid - 1)
	node.right = buildTree(sorted_values, mid + 1, end)
	return node


def search(root: Node | None, key) -> Node | None:
	while root is not None and root.data != key:
		root = root.right if key > root.data else root.left
	return root


# =========================================================================
# Legacy names (ported from Python 2 to Python 3)
# =========================================================================

def privateKeyToWif(key_hex: str) -> str:
	return b58encode_check(b'\x80' + bytes.fromhex(key_hex))

def wifToPrivateKey(s: str) -> str:
	return b58decode_check(s).hex()

def privateKeyToPublicKey(s: str) -> str:
	return pvk_to_pubkey(s)

def pubKeyToAddr(s: str) -> str:
	return pubkey_to_addr(s)

def keyToAddr(s: str) -> str:
	return pubKeyToAddr(privateKeyToPublicKey(s))


# =========================================================================
# Self-test
# =========================================================================

if __name__ == "__main__":
	print(b58c_to_bytes('1KFHE7w8BhaENAswwryaoccDb6qcT6DbYY'))
	print(bytes_to_b58c(b'\x00\xc8%\xa1\xec\xf2\xa6\x83\x0cD\x01b\x0c:\x16\xf1\x99PW\xc2\xab'))
	print(bytes_to_string(b'abc123'))
	print(bytes_to_int(b'\x80\x00'))
	print(bytes_to_hex(b'\x80\x00'))
	print(count_lines(__file__))
	print(hex_to_bytes('8000'))
	print(hex_to_int('8000'))
	print(int_to_bytes(32768))
	print(int_to_str(65))
	print(int_to_hex(32768))
	print(pubkey_to_addr('0430210c23b1a047bc9bdbb13448e67deddc108946de6de639bcc75d47c0216b1be383c4a8ed4fac77c0d2ad737d8499a362f483f8fe39d1e86aaed578a9455dfc'))
	print(pvk_to_wif(bytes.fromhex("000000000000000000000000000000000000000000000001a838b13505b26867")))
	print(wif_to_pvk('5HpHagT65TZzG1PH3CSu63k8DbpvD8s5ipCnYRNeQuRFKarWVVs'))

	priv = bytes.fromhex("11" * 32)
	wif_c = pvk_to_wif(priv, compressed=True)
	wif_u = pvk_to_wif(priv, compressed=False)
	print("WIF (compressed):", wif_c)
	print("WIF (uncompressed):", wif_u)
	assert wif_to_private_key(wif_c) == priv
	assert wif_to_private_key(wif_u) == priv
	assert convert(wif_u) == (wif_c, wif_u)
	assert validate_wif(wif_c) == {'network': 'BTC-mainnet', 'compressed': True}

	pub_c = privkey_to_pubkey(priv, compressed=True)
	pub_u = privkey_to_pubkey(priv, compressed=False)
	print("pub (compressed):", pub_c.hex())
	print("pub (uncompressed):", pub_u.hex())
	print("addr (P2PKH, compressed):", pubkey_to_p2pkh_address(pub_c))
	print("addr (P2PKH, uncompressed):", pubkey_to_p2pkh_address(pub_u))
	print("addr (bech32 cosmos):", pubkey_to_address(pub_c))
	assert decompress_pubkey(pub_c) == pub_u
	assert compress_pubkey_from_uncompressed_hex(pub_u.hex()) == pub_c.hex()

	Q = EccMultiply(GPOINT, int("11" * 32, 16))
	assert Q[0].to_bytes(32, "big") == pub_u[1:33]
	assert Q[1].to_bytes(32, "big") == pub_u[33:]

	# Known vectors, private key = 1
	one = (1).to_bytes(32, 'big')
	pub1 = privkey_to_pubkey(one)
	assert pvk_bin_to_addr(one, compressed=True) == '1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH'
	assert pvk_bin_to_addr(one, compressed=False) == '1EHNa6Q4Jz2uvNExL497mE43ikXhwF6kZm'
	assert _p2wpkh(pub1) == 'bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4'
	assert to_checksum(priv_to_addr(one).hex()) == '0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf'
	assert is_checksum_valid('0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf')
	assert keccak256(b'').hex() == 'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470'
	assert _keccak256_pure(b'abc') == keccak256(b'abc')
	assert keyToAddr(one.hex()) == '1EHNa6Q4Jz2uvNExL497mE43ikXhwF6kZm'

	# BIP39/BIP32/BIP86 vectors ("abandon ... about")
	seed = _mnemonic_to_seed('abandon ' * 11 + 'about')
	m_priv, m_cc = _bip32_master(seed)
	k44, _ = _derive(m_priv, m_cc, _parse_path("m/44'/0'/0'/0/0"))
	k84, _ = _derive(m_priv, m_cc, _parse_path("m/84'/0'/0'/0/0"))
	k86, _ = _derive(m_priv, m_cc, _parse_path("m/86'/0'/0'/0/0"))
	assert _p2pkh(privkey_to_pubkey(k44)) == '1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA'
	assert _p2wpkh(privkey_to_pubkey(k84)) == 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'
	assert _p2tr(privkey_to_pubkey(k86)) == 'bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr'

	root = buildTree([1, 3, 5, 7, 9], 0, 4)
	assert search(root, 7).data == 7 and search(root, 4) is None

	print("sanity: OK")
