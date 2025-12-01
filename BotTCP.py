from tcp_json import recv_tcp_json, send_tcp_json


import socket
import threading


class BotTCP:
    def __init__(self, host='127.0.0.1', port=52000, name='BotTCP',side=None):
        self.host = host; self.port = port; self.name = name
        self.side = None
        self.is_bot = True
        is_observer = False
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(1.0)
        self.running = True
        try:
            self.sock.connect((host, port))
            reg_msg = {'type':'register', 'is_bot':True}
            if side: reg_msg['side'] = side
            send_tcp_json(self.sock, reg_msg)
        except Exception as e:
            print(f"{name}: cannot connect TCP ->", e)
            self.running = False
            return
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _recv_loop(self):
        while self.running:
            msg = recv_tcp_json(self.sock)
            if not msg:
                break
            t = msg.get('type')
            if t == 'ping': 
                send_tcp_json(self.sock, {'type': 'pong', 'ts': msg['ts']})
                continue

            if t == 'assign':
                self.side = msg.get('side')
            elif t == 'state':
                state = msg.get('state')
                self._decide_and_send(state)
        try:
            self.sock.close()
        except Exception:
            pass

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
            send_tcp_json(self.sock, {'type':'input','input':inp})