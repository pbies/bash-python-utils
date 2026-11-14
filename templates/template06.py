#!/usr/bin/env python3
# Script template with main(), filename echo and timing, variant 06.

import sys, os, datetime, time

start_msg=''
start_time=0

def main():
	global start_msg, start_time
	os.system('cls' if os.name == 'nt' else 'clear')
	print(f'{__file__} = {sys.argv[0]}')
	start_msg='Started: '+datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
	print(start_msg)
	start_time=time.time()

	# your code

	stop_time=time.time()
	print(start_msg)
	print('Stopped: '+datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
	print(f'Execution took: {str(datetime.timedelta(seconds=stop_time-start_time))}')
	sys.stdout.write('\a')
	sys.stdout.flush()

# https://stackoverflow.com/questions/5925918/python-suppressing-errors-from-going-to-commandline
class SuppressErrors:
	def write(self, *args):
		pass
	def flush(self, *args):
		pass

if __name__ == '__main__':
	sys.tracebacklimit = 0
	sys.stderr = SuppressErrors()
	try:
		main()
	except KeyboardInterrupt:
		print('\nKeyboard break!\a')
		stop_time=time.time()
		print(start_msg)
		print('Stopped: '+datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
		print(f'Execution took: {str(datetime.timedelta(seconds=stop_time-start_time))}')
		try:
			sys.exit(130)
		except SystemExit:
			os._exit(130)
