from queue import Queue
import json
from .log import debug, debug_exception, DEBUG

def read(stream):
    '''
    Reads one message from the stream and returns the related dict (or None if EOF was reached).

    :param stream:
        The stream we should be reading from.

    :return dict|NoneType:
        The dict which represents a message or None if the stream was closed.
    '''
    headers = {}
    while True:
        # Interpret the http protocol headers
        line = stream.readline() # The trailing \r\n should be there.

        if DEBUG:
            debug(f'read line: >>{line}<<\n')

        if not line:  # EOF
            return None

        line = line.strip().decode('ascii')
        if not line:  # Read just a new line without any contents
            if headers:
                break
            else:
                continue
        try:
            name, value = line.split(': ', 1)
        except ValueError:
            raise RuntimeError('invalid header line: {}'.format(line))
        headers[name] = value

    if not headers:
        raise RuntimeError('got message without headers')

    size = int(headers['Content-Length'])

    # Get the actual json
    body = stream.read(size)

    return json.loads(body.decode('utf-8'))


def reader_thread(stream, queue: Queue):
    try:
        while True:
            data = read(stream)
            if data is None:
                break

            queue.put(data)
    except Exception as e:
        queue.put(None)
        raise e
    except:
        debug_exception()

    debug(f'reader_thread Terminated\n')
