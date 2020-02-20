from queue import Queue, Empty
from threading import Thread
from pygdbmi.gdbcontroller import GdbController, GdbTimeoutError, NoGdbProcessError
from time import time
from .log import debug, debug_exception


class GDBException(Exception):
    pass


def threadAndLevelToFrameId(threadId: int, level: int):
    return level << 8 | threadId


def frameIdToThreadAndLevel(frameId: int):
    return [frameId & 0xff, frameId >> 8]


class GDBResponse:
    def __init__(self, q_gdb, q_write):
        self.seq = 0
        self.request_seq = 0
        self.q_gdb = q_gdb
        self.disconnected = False
        self.q_write = q_write
        self.cur_resp = None

    def handle_events(self, timeout=0.01):
        if self.cur_resp:
            return self.cur_resp

        while True:
            try:
                r = self.q_gdb.get(timeout=timeout)
            except Empty:
                return None

            debug(f'GDBMI return: "{r}"\n')
            type_ = r['type']

            if type_ == 'notify':
                self.notify(r['message'], r['payload'])
            elif type_ == 'log':
                self.log(r['payload'], 'stderr')
            elif type_ == 'target':
                self.log(r['message'], 'stdout')
            elif type_ == 'console':
                self.log(r['payload'], 'console')
            elif type_ == 'output':
                messages = r['payload'].split('~')
                self.log(f'{messages[0]}\n', 'stdout')
                for m in messages[1:]:
                    self.log(m[1:-1], 'console')

            elif type_ == 'result':
                if 'message' == 'error':
                    raise GDBException(r['payload']['msg'])

                self.cur_resp = r
                return self.cur_resp

    @property
    def next_seq(self):
        self.seq += 1
        return self.seq

    def output(self, msg):
        if self.q_write is None:
            print(msg)
        else:
            self.q_write.put(msg)

    def event(self, type_, body=None):
        js = {'event': type_, 'type': 'event', 'seq': self.next_seq}
        if body:
            js['body'] = body

        self.output(js)

    def get_gdp_resp(self):
        if not self.cur_resp:
            self.handle_events(timeout=None)

        ret = self.cur_resp
        self.cur_resp = None
        return ret['message'], ret['payload']

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
            elif payload["reason"] in [
                    'end-stepping-range', 'function-finished'
            ]:
                self.event(
                    'stopped', {
                        'allThreadsStopped':
                        payload['stopped-threads'] == 'all',
                        'threadId': int(payload['thread-id']),
                        'reason': 'step'
                    })
            elif payload["reason"] in ['exited', 'exited-normally']:
                self.close()
            elif payload["reason"] == 'signal-received':
                self.event(
                    'stopped', {
                        'allThreadsStopped':
                        payload['stopped-threads'] == 'all',
                        'threadId': int(payload['thread-id']),
                        'reason': 'user request'
                    })
            else:

                self.log(
                    'console',
                    f'Not implemented stop reason (assuming exception): {payload["reason"]}'
                )
                self.event(
                    'stopped', {
                        'allThreadsStopped':
                        payload['stopped-threads'] == 'all',
                        'threadId': int(payload['thread-id']),
                        'reason': 'exception'
                    })

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

    def process(self, json_cmd):
        resp = {}
        return getattr(self, json_cmd["type"])(resp, json_cmd)

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
                return getattr(self, fname)(resp, **kwds)
            else:
                return getattr(self, f'{json_cmd["type"]}_default')(
                    resp, json_cmd['command'], **kwds)
        except Exception as e:
            resp['success'] = False
            resp['message'] = str(e)
            self.send_response(resp)
            debug_exception()

    def request_default(self, resp, command, **kwds):
        self.send_response(resp)

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

        self.send_response(resp)

    def request_launch(self,
                       resp,
                       gdbpath=None,
                       debugger_args=None,
                       env=None,
                       cwd=None,
                       target=None,
                       **kwds):

        self.get_gdp_resp()  # -gdb-set target-async on

        if cwd:
            self.get_gdp_resp()  # -environment-cd {cwd}

        if target:
            self.get_gdp_resp()  # -file-exec-and-symbols "{target}"

        self.event('initialized')
        self.send_response(resp)
        self.log('Running executable\n', 'console')

    def request_configurationDone(self, resp):
        self.get_gdp_resp()  # '-exec-run'

    def request_setBreakpoints(self, resp, source, breakpoints, lines, **kwds):
        bp_resp = []
        self.get_gdp_resp()  # '-break-delete'

        for b in breakpoints:
            self.get_gdp_resp()
            bp_resp.append({'line': b['line'], 'verified': True})

        resp['body'] = {'breakpoints': bp_resp}
        self.send_response(resp)

    def request_threads(self, resp):
        _, ret = self.get_gdp_resp()
        threads_resp = []

        for t in ret['threads']:
            threads_resp.append({
                'name': f'{t["id"]}:{t["name"]}',
                'id': int(t["id"])
            })

        resp['body'] = {'threads': threads_resp}
        self.send_response(resp)

    def request_stackTrace(self, resp, threadId=None):
        _, ret = self.get_gdp_resp()

        stack_resp = []
        for i, s in enumerate(ret['stack']):
            cur_stack_resp = {
                'name': f'{s["func"]}@{s["addr"]}',
                'column': 0,
                'id': threadAndLevelToFrameId(int(threadId), int(s['level']))
            }

            if 'file' in s:
                cur_stack_resp['source'] = {
                    'sourceReference': 0,
                    'path': s['fullname'],
                    'name': s['file']
                }

            if 'line' in s:
                cur_stack_resp['line'] = int(s['line'])

            stack_resp.append(cur_stack_resp)

        resp['body'] = {'stackFrames': stack_resp}

        self.send_response(resp)

    def request_continue(self, resp, reverse=False, threadId=None):
        msg, ret = self.get_gdp_resp()

        if msg == 'running':
            return resp

        self.send_error_response(resp, f'Could not continue: {ret["msg"]}')

    def request_stepBack(self, resp, threadId=None):
        msg, ret = self.get_gdp_resp()

        if msg == 'running':
            return resp

        self.send_error_response(resp, f'Could not step back: {ret["msg"]}')

    def request_next(self, resp, threadId=None, reverse=False):
        msg, ret = self.get_gdp_resp()

        if msg == 'running':
            return resp

        self.send_error_response(resp, f'Could not step over: {ret["msg"]}')

    def request_stepOut(self, resp, threadId):
        msg, ret = self.get_gdp_resp()

        if msg == 'running':
            return resp

        self.send_error_response(resp, f'Could not step out: {ret["msg"]}')

    def request_stepIn(self, resp, threadId=None, targetId=None):
        msg, ret = self.get_gdp_resp()

        if msg == 'running':
            return resp

        self.send_error_response(resp, f'Could not step in: {ret["msg"]}')

    def request_evaluate(self,
                         resp,
                         expression,
                         frameId=None,
                         context=None,
                         format=None):
        msg, ret = self.get_gdp_resp()
        resp['body'] = {'result': ret['value']}
        self.send_response(resp)

    # def request_completions(self, resp, text, column, frameId=None, line=None):
    #     msg, ret = self.get_gdp_resp()
    #     self.send_response(resp)

    def request_disconnect(self, resp, restart=False):
        self.send_response(resp)
        self.close()

    def close(self):
        self.event('terminated')
        self.output(None)
        self.disconnected = True


class GDBRequest:
    def __init__(self):
        self.gdbmi = None
        self.disconnected = False

    def gdbmi_write(self, cmd):
        if self.gdbmi is None:
            raise GDBException('GDB terminated')

        debug(f'GDBMI write: "{cmd}"\n')
        self.gdbmi.write(cmd, read_response=False)

    def process(self, json_cmd):
        getattr(self, json_cmd["type"])(json_cmd)

    def request(self, json_cmd):
        fname = f'{json_cmd["type"]}_{json_cmd["command"]}'
        kwds = json_cmd.get('arguments', {})

        if hasattr(self, fname):
            getattr(self, fname)(**kwds)
        else:
            getattr(self, f'{json_cmd["type"]}_default')(json_cmd['command'],
                                                         **kwds)

    def request_default(self, command, **kwds):
        pass

    def request_initialize(self, **kwds):
        pass

    def request_launch(self,
                       gdbpath=None,
                       debugger_args=None,
                       env=None,
                       cwd=None,
                       target=None,
                       **kwds):

        self.gdbmi = GdbController()

        self.gdbmi_write("-gdb-set target-async on")

        if cwd:
            self.gdbmi_write(f'-environment-cd {cwd}')

        if target:
            self.gdbmi_write(f'-file-exec-and-symbols "{target}"')

    def request_configurationDone(self):
        self.gdbmi_write('-exec-run')

    def request_setBreakpoints(self, source, breakpoints, lines, **kwds):
        self.gdbmi_write(f'-break-delete')
        for b in breakpoints:
            self.gdbmi_write(
                f'-break-insert -f "{source["path"]}:{b["line"]}"')

    def request_threads(self):
        self.gdbmi_write('-thread-info')

    def request_stackTrace(self, threadId=None):
        command = "-stack-list-frames"
        if threadId is not None:
            command += f' --thread {threadId}'

        self.gdbmi_write(command)

    def request_continue(self, reverse=False, threadId=None):
        self.gdbmi_write('-exec-continue' + (" --reverse" if reverse else ""))

    def request_stepBack(self, threadId):
        return self.request_step(reverse=True, threadId=threadId)

    def request_stepIn(self, threadId):
        return self.request_step(reverse=False, threadId=threadId)

    def request_next(self, threadId=None, reverse=False):
        self.gdbmi_write('-exec-next' + (" --reverse" if reverse else ""))

    def request_step(self, threadId=None, reverse=False):
        self.gdbmi_write('-exec-step' + (" --reverse" if reverse else ""))

    def request_stepOut(self, threadId=None, reverse=False):
        self.gdbmi_write('-exec-finish' + (" --reverse" if reverse else ""))

    def request_evaluate(self,
                         expression,
                         frameId=None,
                         context=None,
                         format=None):
        if frameId is not None:
            self.gdbmi_write(
                f'-data-evaluate-expression "{expression}"'
            )
        else:
            threadId, level = frameIdToThreadAndLevel(frameId)
            self.gdbmi_write(
                f'-data-evaluate-expression {expression} --thread {threadId} --level {level}'
            )

    # def request_completions(self, text, column, frameId=None, line=None):
    #     self.gdbmi_write(f'-complete {text[:column]}')

    def request_disconnect(self, restart=False):
        self.gdbmi_write('-gdb-exit')
        self.disconnected = True
        # self.close()

    def close(self):
        if self.gdbmi:
            self.gdbmi.exit()
            self.gdbmi = None


def gdb_resp_reader(out_queue: Queue, gdbmi: GdbController):
    try:
        while True:
            ret = gdbmi.get_gdb_response(timeout_sec=0.01,
                                         raise_error_on_timeout=False)
            for r in ret:
                out_queue.put(r)
    except (NoGdbProcessError, OSError):
        debug(f'gdb_resp_reader Terminated\n')
    except:
        debug_exception()


def gdb_resp(in_queue: Queue, gdb_resp: Queue, out_queue: Queue, gdb_req):
    gdb_resp = GDBResponse(gdb_resp, out_queue)

    try:
        while True:
            gdb_resp.handle_events()

            try:
                data = in_queue.get(timeout=0.01)
            except Empty:
                continue

            if data is None:
                break

            gdb_resp.process(data)

            if gdb_resp.disconnected:
                break

    except GDBException:
        pass
    except:
        debug_exception()

    debug(f'gdb_resp Terminated\n')


def json_process(in_queue: Queue, out_queue: Queue):
    try:
        gdb_req = GDBRequest()
        q_resp = Queue()
        q_gdb_resp = Queue()
        gdb_resp_reader_thread = None
        gdb_resp_thread = Thread(target=gdb_resp,
                                 args=(q_resp, q_gdb_resp, out_queue, gdb_req))
        gdb_resp_thread.start()

        while True:
            data = in_queue.get()
            if data is None:
                gdb_req.close()
                break

            debug(f'DAP REQ: {data}\n')
            gdb_req.process(data)
            if gdb_resp_reader_thread is None and gdb_req.gdbmi is not None:
                gdb_resp_reader_thread = Thread(target=gdb_resp_reader,
                                                args=(q_gdb_resp,
                                                      gdb_req.gdbmi))
                gdb_resp_reader_thread.start()

            q_resp.put(data)

            if gdb_req.disconnected:
                break

        q_resp.put(None)
        if gdb_resp_reader_thread:
            gdb_resp_reader_thread.join()

        gdb_resp_thread.join()

        gdb_req.close()
        debug(f'json_process Terminated\n')
    except:
        debug_exception()
