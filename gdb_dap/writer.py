from .log import debug_exception, DEBUG, debug
import json

def writer_thread(stream, queue):
    try:
        while True:
            to_write = queue.get()

            to_write = json.dumps(to_write)

            if DEBUG:
                debug('Writing: %s\n' % (to_write,))

            if to_write.__class__ == bytes:
                as_bytes = to_write
            else:
                as_bytes = to_write.encode('utf-8')

            stream.write(f'Content-Length: {len(as_bytes)}\r\n\r\n'.encode('utf-8'))
            stream.write(as_bytes)
            stream.flush()
    except:
        debug_exception()
