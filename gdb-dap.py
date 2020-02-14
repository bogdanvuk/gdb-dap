import sys
from threading import Thread
import asyncio
from queue import Queue
import json
import pprint
from pygdbmi.gdbcontroller import GdbController

i = 0


def dump(s):
    global i
    with open('/tools/home/gdb-dap/gdb-dap.log', 'a') as f:
        f.write(f'{i:3}: {s}\n')
        i += 1


class Session:
    def __init__(self):
        self.seq = 0
        self.request_seq = 0
        self.gdbmi = None

    @property
    def next_seq(self):
        self.seq += 1
        return self.seq

    def event(self, type_, body=None):
        js = {'event': type_, 'type': 'event', 'seq': self.next_seq}
        if body:
            js['body'] = body

        print(json.dumps(js))

    def send_response(self, resp):
        print(json.dumps(resp))

    def log(self, message):
        self.event({'output': message, 'category': 'console'})

    def notify(self, message, payload):
        if message == 'thread-created':
            self.event('thread', {'threadId': payload['id'], 'reason': 'started'})
        elif message == 'thread-exited':
            self.event('thread', {'threadId': payload['id'], 'reason': 'exited'})

    def gdbmi_write(self, cmd):
        ret = self.gdbmi.write(cmd)
        print(f'{cmd}: {ret}')

        res = None
        for r in ret:
            if r['type'] == 'result':
                res = r['payload']
            elif r['type'] == 'notify':
                self.notify(r['message'], r['payload'])

        return res

    def process(self, json_cmd):

        resp = {}
        resp = getattr(self, json_cmd["type"])(resp, json_cmd)

        if resp:
            resp['seq'] = self.next_seq
            self.send_response(resp)

    def request(self, resp, json_cmd):
        self.request_seq += 1

        fname = f'{json_cmd["type"]}_{json_cmd["command"]}'
        kwds = json_cmd.get('arguments', {})

        resp.update(
            {
                'success': True,
                'command': json_cmd['command'],
                'request_seq': self.request_seq,
                'type': 'response'
            })

        if hasattr(self, fname):
            resp = getattr(self, fname)(resp, **kwds)
        else:
            resp = getattr(self, f'{json_cmd["type"]}_default')(
                resp, json_cmd['command'], **kwds)

        return resp

    def request_default(self, resp, command, **kwds):
        return resp

    def request_initialize(self, resp, **kwds):
        resp['body'] = {
            'supportsGotoTargetsRequest': True,
            'supportsHitConditionalBreakpoints': True,
            'supportsConfigurationDoneRequest': True,
            'supportsConditionalBreakpoints': True,
            'supportsFunctionBreakpoints': True,
            'supportsEvaluateForHovers': True,
            'supportsSetVariable': True,
            'supportsStepBack': True,
        }

        return resp

    def request_launch(
        self,
        resp,
        gdbpath=None,
        debugger_args=None,
        env=None,
        cwd=None,
        target=None,
        **kwds):

        self.gdbmi = GdbController()
        self.event('initialized')

        if cwd:
            self.gdbmi_write(f'-environment-cd {cwd}')

        if target:
            self.gdbmi_write(f'-file-exec-and-symbols {target}')

        self.send_response(resp)

        self.gdbmi_write('-exec-run')

    def request_setBreakpoints(self, resp, source, breakpoints, lines, **kwds):
        bp_resp = []
        self.gdbmi_write(f'-break-delete')
        for b in breakpoints:
            self.gdbmi_write(f'-break-insert -f "{source["path"]}:{b["line"]}"')
            bp_resp.append({'line': b['line'], 'verified': True})

        resp['body'] = {'breakpoints': bp_resp}

        return resp

    def request_threads(self, resp):
        ret = self.gdbmi_write('-thread-info')
        threads_resp = []

        for t in ret['threads']:
            pass

        resp['body'] = {'threads': threads_resp}

        return resp

    def close(self):
        print('Close')
        if self.gdbmi:
            self.gdbmi.exit()


def json_process(in_queue: Queue):
    session = Session()
    while True:
        data = in_queue.get()
        if data is None:
            session.close()
            return

        session.process(data)


def json_read(queue: Queue):
    json_loading = False
    json_cmd = ''

    while True:
        line = readline()
        # line = await loop.run_in_executor(None, sys.stdin.readline)

        if line is None:
            queue.put(None)
            return

        if line == '{':
            json_loading = True
            json_cmd = ''

        if json_loading:
            json_cmd += line

        if line == '}':
            json_loading = False
            data = json.loads(json_cmd)
            dump(json.dumps(data))

            queue.put(data)


# def readline():
#     s = sys.stdin.readline()
#     if not s:
#         return None

#     return s.rstrip()

cmds_str = [
    '''{
  "command": "initialize",
  "arguments": {
    "clientID": "vscode",
    "clientName": "Visual Studio Code",
    "adapterID": "gdb",
    "pathFormat": "path",
    "linesStartAt1": true,
    "columnsStartAt1": true,
    "supportsVariableType": true,
    "supportsVariablePaging": true,
    "supportsRunInTerminalRequest": true,
    "locale": "en-us"
  },
  "type": "request",
  "seq": 1
}'''.split('\n'),
    '''{
  "command": "launch",
  "arguments": {
    "type": "gdb",
    "request": "launch",
    "name": "GDB::Run<1>",
    "target": "/tools/home/sprinting/qdac_2_fpga/sw/QDAC/build/test_commands_square",
    "cwd": "/tools/home/sprinting/qdac_2_fpga/sw/QDAC/test/test_runners/commands/",
    "dap-server-path": [
      "node",
      "/tools/home/.emacs.d/.extension/vscode/webfreak.debug/extension/out/src/gdb.js"
    ]
  },
  "type": "request",
  "seq": 2
}'''.split('\n'),
    '''{
  "command": "setBreakpoints",
  "arguments": {
    "source": {
      "name": "test_square.c",
      "path": "/tools/home/sprinting/qdac_2_fpga/sw/QDAC/test/test_runners/commands/test_square.c"
    },
    "breakpoints": [
      {
        "line": 66
      }
    ],
    "sourceModified": false,
    "lines": [
      66
    ]
  },
  "type": "request",
  "seq": 3
}'''.split('\n'),
    '''{
  "command": "setExceptionBreakpoints",
  "arguments": {
    "filters": []
  },
  "type": "request",
  "seq": 4
}'''.split('\n'),
    '''{
  "command": "configurationDone",
  "type": "request",
  "seq": 5
}'''.split('\n'),
    '''{
  "command": "threads",
  "type": "request",
  "seq": 6
}'''.split('\n'),
]

cmds = [item for sublist in cmds_str for item in sublist]
cmds_iter = iter(cmds)


def readline():
    try:
        return next(cmds_iter)
    except StopIteration:
        return None


if __name__ == "__main__":
    q = Queue()
    thread = Thread(target=json_process, args=(q, ))
    thread.start()

    json_read(q)
    thread.join()
    print("thread finished...exiting")
