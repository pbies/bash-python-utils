#!/usr/bin/env python3

# pip3 install pypdf2

from PyPDF2 import PdfMerger
import sys

def main():
	if len(sys.argv) < 3:
		print("usage: merge.py out.pdf in1.pdf in2.pdf ...")
		return
	out = sys.argv[1]
	pdfs = sys.argv[2:]
	merger = PdfMerger()
	for p in pdfs:
		merger.append(p)
	merger.write(out)
	merger.close()

if __name__ == "__main__":
	main()
