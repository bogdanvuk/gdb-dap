import json
from gdb_dap.gdb_dap import json_process
from queue import Queue

def test_gdp(log_file):
    json_loading = False
    json_cmd = ''

    json_in = []
    json_out = []

    direction = None

    with open(log_file) as f:
        for line in f:
            line = line.rstrip()
            if line == '{':
                json_loading = True
                json_cmd = ''

            if json_loading:
                json_cmd += line
            else:
                direction = line

            if line == '}':
                json_loading = False
                data = json.loads(json_cmd)
                if direction == 'Sending:':
                    json_in.append(data)
                else:
                    json_out.append(data)



    json_res = []

    q_resp = Queue()
    for data in json_in:
        q_resp.put(data)

    json_process(q_resp, None)

    with open('ref.txt', 'w') as f:
        for ref in json_out:
            f.write(json.dumps(ref, indent=4))

    with open('res.txt', 'w') as f:
        for res in json_res:
            f.write(json.dumps(res, indent=4))

test_gdp('example2.txt')
