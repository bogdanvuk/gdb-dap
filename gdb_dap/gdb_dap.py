from queue import Queue
from pygdbmi.gdbcontroller import GdbController
from time import time
from .log import debug

class GDBException(Exception):
    pass


def threadAndLevelToFrameId(threadId: int, level: int):
    return level << 8 | threadId


def frameIdToThreadAndLevel(frameId: int):
    return [frameId & 0xff, frameId >> 8]

class Session:
    def __init__(self, q_write):
        self.seq = 0
        self.request_seq = 0
        self.gdbmi = None
        self.disconnected = False
        self.q_write = q_write

    @property
    def next_seq(self):
        self.seq += 1
        return self.seq

    def output(self, msg):
        self.q_write.put(msg)

    def event(self, type_, body=None):
        js = {'event': type_, 'type': 'event', 'seq': self.next_seq}
        if body:
            js['body'] = body

        self.output(js)

    def send_response(self, resp):
        resp['seq'] = self.next_seq
        self.output(resp)

    def send_error_response(self, resp, msg):
        resp['seq'] = self.next_seq
        resp['success'] = False
        resp['msg'] = msg
        if 'body' in resp:
            resp['body']['error'] = msg

        self.output(resp)

    def log(self, message, category):
        self.event(
            'output', {
                'output': message.encode('utf-8').decode('unicode_escape'),
                'category': category
            })

    def notify(self, message, payload):
        if message == 'stopped':
            if payload["reason"] == 'breakpoint-hit':
                self.event(
                    'stopped', {
                        'allThreadsStopped':
                        payload['stopped-threads'] == 'all',
                        'threadId': int(payload['thread-id']),
                        'reason': 'breakpoint'
                    })
            elif payload["reason"] == 'end-stepping-range':
                self.event(
                    'stopped', {
                        'allThreadsStopped':
                        payload['stopped-threads'] == 'all',
                        'threadId': int(payload['thread-id']),
                        'reason': 'step'
                    })
            elif payload["reason"] == 'exited-normally':
                self.close()

            # else if (payload["reason"] == "function-finished")
            #     this.emit("step-out-end", parsed);
            # else if (payload["reason"] == "signal-received")
            #     this.emit("signal-stop", parsed);
            # else if (payload["reason"] == "exited-normally")
            #     this.emit("exited-normally", parsed);
            # else if (payload["reason"] == "exited") { // exit with error code != 0
            #     this.log("stderr", "Program exited with code " + parsed.record("exit-code"));
            #     this.emit("exited-normally", parsed);
            # } else {
            #     this.log("console", "Not implemented stop reason (assuming exception): " + reason);
            #     this.emit("stopped", parsed);
            # }

        elif message == 'thread-created':
            self.event('thread', {
                'threadId': payload['id'],
                'reason': 'started'
            })
        elif message == 'thread-exited':
            self.event('thread', {
                'threadId': payload['id'],
                'reason': 'exited'
            })

    def gdbmi_write(self, cmd):
        if self.gdbmi is None:
            raise GDBException('GDB terminated')

        start = time()
        ret = self.gdbmi.write(cmd)
        debug(f'GDBMI time: {time() - start}, cmd: {cmd}\n')

        # print(f'{cmd}: {ret}')

        res = (None, None)
        for r in ret:
            if r['type'] == 'result':
                res = (r['message'], r['payload'])
            elif r['type'] == 'notify':
                self.notify(r['message'], r['payload'])
            elif r['type'] == 'log':
                self.log(r['message'], 'stderr')
            elif r['type'] == 'target':
                self.log(r['message'], 'stdout')
            elif r['type'] == 'console':
                self.log(r['payload'], 'console')
            elif r['type'] == 'output':
                self.log(r['payload'], 'stdout')

        return res

    def process(self, json_cmd):

        resp = {}
        resp = getattr(self, json_cmd["type"])(resp, json_cmd)

        if resp:
            self.send_response(resp)

    def request(self, resp, json_cmd):
        self.request_seq += 1

        fname = f'{json_cmd["type"]}_{json_cmd["command"]}'
        kwds = json_cmd.get('arguments', {})

        resp.update({
            'success': True,
            'command': json_cmd['command'],
            'request_seq': self.request_seq,
            'type': 'response'
        })

        try:
            if hasattr(self, fname):
                resp = getattr(self, fname)(resp, **kwds)
            else:
                resp = getattr(self, f'{json_cmd["type"]}_default')(
                    resp, json_cmd['command'], **kwds)
        except Exception as e:
            resp['success'] = False
            resp['message'] = str(e)

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

    def request_launch(self,
                       resp,
                       gdbpath=None,
                       debugger_args=None,
                       env=None,
                       cwd=None,
                       target=None,
                       **kwds):

        self.gdbmi = GdbController()
        self.event('initialized')

        self.gdbmi_write("-gdb-set target-async on")

        if cwd:
            self.gdbmi_write(f'-environment-cd {cwd}')

        if target:
            self.gdbmi_write(f'-file-exec-and-symbols "{target}"')

        self.send_response(resp)
        self.log('Running executable\n', 'console')

    def request_configurationDone(self, resp):
        self.gdbmi_write('-exec-run')
        return resp

    def request_setBreakpoints(self, resp, source, breakpoints, lines, **kwds):
        bp_resp = []
        self.gdbmi_write(f'-break-delete')
        for b in breakpoints:
            self.gdbmi_write(
                f'-break-insert -f "{source["path"]}:{b["line"]}"')
            bp_resp.append({'line': b['line'], 'verified': True})

        resp['body'] = {'breakpoints': bp_resp}

        return resp

    def request_threads(self, resp):
        _, ret = self.gdbmi_write('-thread-info')
        threads_resp = []

        for t in ret['threads']:
            threads_resp.append({
                'name': f'{t["id"]}:{t["name"]}',
                'id': int(t["id"])
            })

        resp['body'] = {'threads': threads_resp}

        return resp

    def request_stackTrace(self, resp, threadId=None):
        command = "-stack-list-frames"
        if threadId is not None:
            command += f' --thread {threadId}'

        _, ret = self.gdbmi_write(command)

        stack_resp = []
        for i, s in enumerate(ret['stack']):
            stack_resp.append({
                'name':
                f'{s["func"]}@{s["addr"]}',
                'line':
                int(s['line']),
                'column':
                0,
                'id':
                threadAndLevelToFrameId(int(threadId), int(s['level'])),
                'source': {
                    'sourceReference': 0,
                    'path': s['fullname'],
                    'name': s['file']
                }
            })

        resp['body'] = {'stackFrames': stack_resp}

        return resp

    def request_continue(self, resp, reverse=False, threadId=None):
        msg, ret = self.gdbmi_write('-exec-continue' +
                                    (" --reverse" if reverse else ""))
        if msg == 'running':
            return resp

        self.send_error_response(resp, f'Could not continue: {ret["msg"]}')

    def request_stepBack(self, resp, threadId=None):
        return self.request_step(resp=resp, reverse=True, threadId=threadId)


# def stepInRequest(response: DebugProtocol.NextResponse, args: DebugProtocol.NextArguments): void {
# 	this.miDebugger.step().then(done => {
# 		this.sendResponse(response);
# 	}, msg => {
# 		this.sendErrorResponse(response, 4, `Could not step in: ${msg}`);
# 	});
# }

# def stepOutRequest(response: DebugProtocol.NextResponse, args: DebugProtocol.NextArguments): void {
# 	this.miDebugger.stepOut().then(done => {
# 		this.sendResponse(response);
# 	}, msg => {
# 		this.sendErrorResponse(response, 5, `Could not step out: ${msg}`);
# 	});
# }

    def request_next(self, resp, threadId=None, reverse=False):
        msg, ret = self.gdbmi_write('-exec-next' +
                                    (" --reverse" if reverse else ""))
        if msg == 'running':
            return resp

        self.send_error_response(resp, f'Could not step over: {ret["msg"]}')

    def request_step(self, resp, threadId=None):
        msg, ret = self.gdbmi_write('-exec-step')
        if msg == 'running':
            return resp

        self.send_error_response(resp, f'Could not step in: {ret["msg"]}')

    def request_disconnect(self, resp, restart=False):
        self.gdbmi_write('-gdb-exit')
        self.close()
        self.send_response(resp)

    def close(self):
        if self.gdbmi:
            self.gdbmi.exit()
            self.gdbmi = None

        self.event('terminated')
        self.disconnected = True


def json_process(in_queue: Queue, out_queue: Queue):
    session = Session(out_queue)
    while True:
        data = in_queue.get()
        if data is None:
            session.close()
            return

        session.process(data)

        if session.disconnected:
            return
