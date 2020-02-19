import sys
from threading import Thread
from queue import Queue
from gdb_dap.reader import reader_thread
from gdb_dap.writer import writer_thread
from gdb_dap.gdb_dap import json_process

if __name__ == "__main__":
    thread = None
    reader = None
    writer = None

    read_from = sys.stdin.buffer
    write_to = sys.stdout.buffer
    # read_from = open('./cmds.txt', 'rb')

    q_read = Queue()
    q_write = Queue()

    reader = Thread(target=reader_thread, args=(read_from, q_read))
    writer = Thread(target=writer_thread, args=(write_to, q_write))
    thread = Thread(target=json_process, args=(q_read, q_write))

    if thread:
        thread.start()

    writer.start()
    reader.start()

    if thread:
        thread.join()

    writer.join()
    reader.join()
