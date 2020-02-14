import sys
import asyncio
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

    async def gdb_write(self, cmd):
        return await loop.run_in_executor(None, self.gdbmi.write, cmd)

    async def event(self, type_):
        js = {'event': type_, 'type': 'event', 'seq': self.next_seq}
        print(json.dumps(js))

    async def process(self, json_cmd):

        resp = {}
        resp = await getattr(self, json_cmd["type"])(resp, json_cmd)

        resp['seq'] = self.next_seq

        return resp

    async def request(self, resp, json_cmd):
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

        if getattr(self, fname):
            resp = await getattr(self, fname)(resp, **kwds)
        else:
            resp = await getattr(self, f'{json_cmd["type"]}_default')(resp, **kwds)

        return resp

    async def request_default(self, resp, command, **kwds):
        return {'body': {}, 'dflt': True}

    async def request_initialize(self, resp, **kwds):
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

    async def request_launch(
        self, gdbpath=None, debugger_args=None, env=None, cwd=None, target=None, **kwds):
        self.gdbmi = GdbController()
        await self.event('initialized')

        if cwd:
            await self.gdb_write(f'-environment-cd {cwd}')

        if target:
            await self.gdb_write(f'-file-exec-and-symbols {target}')

    def close(self):
        print('Close')
        if self.gdbmi:
            self.gdbmi.exit()

    #     self.miDebugger = new MI2(gdbpath | "gdb", ["-q", "--interpreter=mi2"], debugger_args, env)

    #     self.initDebugger()
    #     self.quit = False;
    #     self.attached = False;
    #     self.needContinue = False;
    #     self.isSSH = False;
    #     self.started = False;
    #     self.crashed = False;
    #     self.debugReady = False;
    #     self.setValuesFormattingMode(args.valuesFormatting);
    #     self.miDebugger.printCalls = !!args.printCalls;
    #     self.miDebugger.debugOutput = !!args.showDevDebugOutput;


async def json_process(in_queue: asyncio.Queue):
    session = Session()
    while True:
        data = await in_queue.get()
        if data is None:
            session.close()
            return

        resp = await session.process(data)
        print(json.dumps(resp, indent=4))


async def json_read(loop, queue: asyncio.Queue):
    json_loading = False
    json_cmd = ''

    while True:
        line = readline()
        # line = await loop.run_in_executor(None, sys.stdin.readline)

        if line is None:
            await queue.put(None)
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

            await queue.put(data)


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
}'''.split('\n'), '''{
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
}'''.split('\n')
]

cmds = [item for sublist in cmds_str for item in sublist]
cmds_iter = iter(cmds)


def readline():
    try:
        return next(cmds_iter)
    except StopIteration:
        return None


queue = asyncio.Queue()
loop = asyncio.get_event_loop()
loop.run_until_complete(asyncio.gather(json_read(loop, queue), json_process(queue)))
loop.close()
