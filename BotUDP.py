import json
import socket
import threading


class BotUDP:
    def __init__(self, host='127.0.0.1', port=53000, name='BotUDP',side=None):
        self.host = host; self.port = port; self.name = name
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(1.0)
        self.side = None
        self.is_bot = True
        is_observer = False
        self.running = True
        reg_msg = {'type':'register','is_bot':True}
        if side:
            reg_msg['side'] = side
        self.sock.sendto(json.dumps(reg_msg).encode('utf-8'), self.addr)

        try:
            self.sock.sendto(json.dumps({'type':'register','is_bot':True,'side':self.side}).encode('utf-8'), self.addr)
        except Exception as e:
            print(f"{name}: register failed ->", e)
            self.running = False
            return
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _recv_loop(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                msg = json.loads(data.decode('utf-8'))
            except socket.timeout:
                continue
            except Exception:
                break
            t = msg.get('type')
            if t == 'ping':
                try:
                    self.sock.sendto(json.dumps({'type': 'pong', 'ts': msg['ts']}).encode('utf-8'), self.addr)
                except Exception:
                    pass
                continue

            if t == 'assign':
                self.side = msg.get('side')

            elif t == 'state':
                state = msg.get('state')
                self._decide_and_send(state)




    def _decide_and_send(self, state):
        ball_x, ball_y = state['ball']
        if not self.side:
            return
        inp = None
        if self.side in ['LEFT', 'RIGHT']:
            if ball_y < state['paddles'][self.side] - 8:
                inp = 'UP'
            elif ball_y > state['paddles'][self.side] + 8:
                inp = 'DOWN'
        else:
            if ball_x < state['paddles']['BOTTOM'] - 8:
                inp = 'LEFT'
            elif ball_x > state['paddles']['BOTTOM'] + 8:
                inp = 'RIGHT'
        if inp:
            try:
                self.sock.sendto(json.dumps({'type':'input','input':inp}).encode('utf-8'), self.addr)
            except Exception:
                pass