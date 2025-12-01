import multiprocessing
import random
import socket
import threading
import json
import time
import pygame
import struct
from collections import deque
from tcp_json import send_tcp_json, recv_tcp_json
from BotTCP import BotTCP
from BotUDP import BotUDP

WIDTH, HEIGHT = 500, 500
BALL_SPEED = 150.0
PADDLE_SPEED = 100.0
PADDLE_SIZE = 80
FPS = 30
TICK = 1.0 / FPS


class GameState:
    def __init__(self):
        self.ball_x, self.ball_y = WIDTH / 2, HEIGHT / 2
        angle = random.uniform(-0.7,0.7)
        self.ball_vx = BALL_SPEED * (1 if random.random() < 0.5 else -1)
        self.ball_vy = BALL_SPEED * angle
        self.paddles = {'LEFT': HEIGHT/2, 'RIGHT': HEIGHT/2, 'BOTTOM': WIDTH/2}
        self.scores = {'LEFT':0, 'RIGHT':0, 'BOTTOM':0}

    def to_dict(self, seq):
        return {'seq': seq, 'ball': (self.ball_x, self.ball_y),
                'paddles': self.paddles.copy(),
                'scores': self.scores.copy()}


class ClientInfo:
    def __init__(self, conn_or_addr, side, proto, is_bot=False, is_observer=False):
        self.conn_or_addr = conn_or_addr
        self.side = side
        self.proto = proto
        self.is_bot = is_bot
        self.is_observer = is_observer
        self.input = None
        self.lock = threading.Lock()
        self.sent = 0
        self.acked = 0
        self.bytes_sent = 0
        self.pings = deque(maxlen=20)
        self.pkt_recv = 0
        self.last_send_time = 0
        self.avg_interval = 0
        self.last_msg_size = 0
        self.avg_msg_size = 0
        
        self.ping_history = []
        self.pps_history = []
        self.jitter_history = []
        self.time_history = []
        
        self.last_packet_time = None
        self.intervals = []
        
    def get_pps(self):
        if not self.intervals:
            return 0.0
        avg_interval = sum(self.intervals) / len(self.intervals)
        if avg_interval <= 0:
            return 0.0
        return 1.0 / avg_interval
    
    def get_jitter(self):
        if len(self.intervals) < 2:
            return 0.0
        diffs = [abs(self.intervals[i] - self.intervals[i-1]) 
                for i in range(1, len(self.intervals))]
        return sum(diffs) / len(diffs)


class PongServer:
    def __init__(self, protocol='tcp', port=52000, name='TCP'):
        self.protocol = protocol
        self.port = port
        self.name = name
        self.lock = threading.Lock()
        self.game = GameState()
        self.seq = 0
        self.running = True
        self.clients = {}         
        self.tcp_bots = {}         
        self.udp_bots = {}         
        self.plot_buffer = []

        if protocol=='tcp':
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,1)
            self.sock.bind(('0.0.0.0', port))
            self.sock.listen(5)
        else:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,1)
            self.sock.bind(('0.0.0.0', port))

        self._start_threads()
        threading.Thread(target=self._spawn_initial_bots, daemon=True).start()

    def _start_threads(self):
        if self.protocol=='tcp':
            threading.Thread(target=self._accept_loop, daemon=True).start()
        else:
            threading.Thread(target=self._udp_recv_loop, daemon=True).start()
        threading.Thread(target=self._game_loop, daemon=True).start()
        threading.Thread(target=self._ping_loop, daemon=True).start()
        threading.Thread(target=self._stats_loop, daemon=True).start()

    def _spawn_initial_bots(self):
        sides = ['LEFT','RIGHT','BOTTOM']
        while self.running:
            with self.lock:
                taken_sides = {c.side for c in self.clients.values() if not c.is_observer and not c.is_bot}

            for side in sides:
                if self.protocol=='tcp' and side not in self.tcp_bots and side not in taken_sides:
                    bot = BotTCP(host='127.0.0.1', port=self.port, name=f"TCPBot-{side}", side=side)
                    self.tcp_bots[side] = bot
                if self.protocol=='udp' and side not in self.udp_bots and side not in taken_sides:
                    bot = BotUDP(host='127.0.0.1', port=self.port, name=f"UDPBot-{side}", side=side)
                    self.udp_bots[side] = bot
            time.sleep(2.0)

    def _accept_loop(self):
        while self.running:
            try:
                conn, addr = self.sock.accept()
            except Exception:
                continue
            threading.Thread(target=self._handle_tcp_client, args=(conn,), daemon=True).start()
            print(f"[SERVER] TCP connection accepted: {addr}")

    def _handle_tcp_client(self, conn):
        fileno = conn.fileno()
        peer = ('unknown',0)
        try: peer = conn.getpeername()
        except: pass

        registered = False

        while self.running:
            msg = recv_tcp_json(conn)
            if not msg: break

            if not registered:
                t = msg.get('type')
                if t in ('register','identify'):
                    is_bot = bool(msg.get('is_bot', False))
                    side = msg.get('side', None)
                    if side not in ['LEFT','RIGHT','BOTTOM']:
                        side = None
                    is_observer = False if is_bot else (side is None)
                    with self.lock:
                        client_info = ClientInfo(conn, side, 'tcp', is_bot=is_bot, is_observer=is_observer)
                        self.clients[fileno] = client_info
                        registered = True
                    if is_observer:
                        send_tcp_json(conn, {'type':'observer'})
                        print(f"[SERVER] TCP observer registered: {peer}")
                    elif is_bot:
                        send_tcp_json(conn, {'type':'assign','side':side})
                        print(f"[SERVER] TCP bot registered: {peer} -> {side}")
                    else:
                        send_tcp_json(conn, {'type':'assign','side':side})
                        print(f"[SERVER] TCP player registered & assigned: {peer} -> {side}")
                    continue
                else:
                    send_tcp_json(conn, {'type':'error','msg':'Please register first'})
                    continue

            self._process_msg(msg, self.clients.get(fileno))

        try: conn.close()
        except: pass
        with self.lock:
            if fileno in self.clients:
                del self.clients[fileno]
                print(f"[SERVER] TCP client disconnected: {peer}")

    def _udp_recv_loop(self):
        sides = ['LEFT','RIGHT','BOTTOM']
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                msg = json.loads(data.decode('utf-8'))
            except Exception:
                continue

            client = self.clients.get(addr)

            if not client and msg.get('type')=='register':
                is_bot = bool(msg.get('is_bot', False))
                side = msg.get('side', None)
                is_observer = (not is_bot and side is None)
                with self.lock:
                    client = ClientInfo(addr, side, 'udp', is_bot=is_bot, is_observer=is_observer)
                    self.clients[addr] = client
                if is_observer:
                    self.sock.sendto(json.dumps({'type':'observer'}).encode('utf-8'), addr)
                elif is_bot:
                    self.sock.sendto(json.dumps({'type':'assign','side':side}).encode('utf-8'), addr)
                else:
                    self.sock.sendto(json.dumps({'type':'assign','side':side}).encode('utf-8'), addr)
                continue

            if client:
                self._process_msg(msg, client)

    def _process_msg(self, msg, client):
        if not client: return
        client.pkt_recv += 1
        now = time.time()
        if client.last_packet_time is not None:
            interval = now - client.last_packet_time
            client.intervals.append(interval)
        client.last_packet_time = now
        t = msg.get('type')
        if t=='input':
            with client.lock:
                client.input = msg.get('input')
        elif t=='ack':
            client.acked +=1
        elif t=='pong':
            client.pings.append((time.time()-msg['ts'])*1000)
        elif t=='request_side':
            requested = msg.get('side')
            if requested not in ['LEFT','RIGHT','BOTTOM']:
                return
            with self.lock:
                if requested in self.tcp_bots:
                    bot = self.tcp_bots[requested]
                    bot.running = False
                    del self.tcp_bots[requested]
                    
                if requested in self.udp_bots:
                    bot = self.udp_bots[requested]
                    bot.running = False
                    time.sleep(0.1)
                    del self.udp_bots[requested]
                
                for key, c in list(self.clients.items()):
                    if c.side == requested and c.is_bot:
                        del self.clients[key]
                        print(f"[SERVER] Removed bot client from {requested}")
                
                client.side = requested
                client.is_observer = False
                if client.proto=='tcp':
                    send_tcp_json(client.conn_or_addr, {'type':'assign','side':requested})
                else:
                    self.sock.sendto(json.dumps({'type':'assign','side':requested}).encode('utf-8'), client.conn_or_addr)


    def _game_loop(self):
        last_time = time.time()
        while self.running:
            now = time.time()
            dt = now-last_time
            last_time = now
            self._update_game(dt)
            self._broadcast_state()
            time.sleep(TICK)

    def _reset_round(self):
        g = self.game
        g.ball_x, g.ball_y = WIDTH / 2, HEIGHT / 2
        angle = random.uniform(-0.7, 0.7)
        g.ball_vx = BALL_SPEED * (1 if random.random() < 0.5 else -1)
        g.ball_vy = BALL_SPEED * angle

    def _update_game(self, dt):
        g = self.game
        g.ball_x += g.ball_vx * dt
        g.ball_y += g.ball_vy * dt

        # if g.ball_x <= 0:
        #     g.ball_vx = abs(g.ball_vx)
        # if g.ball_x >= WIDTH:
        #     g.ball_vx = -abs(g.ball_vx)
        # if g.ball_y <= 0:
        #     g.ball_vy = abs(g.ball_vy)
        # if g.ball_y >= HEIGHT:
        #     g.ball_vy = -abs(g.ball_vy)

        # If ball leaves the frame → restart round
        if g.ball_x < 0 or g.ball_x > WIDTH or g.ball_y < 0 or g.ball_y > HEIGHT:
            self._reset_round()
            return

        if g.ball_x <= 10 and abs(g.ball_y - g.paddles['LEFT']) < PADDLE_SIZE/2:
            g.ball_vx = abs(g.ball_vx)
        if g.ball_x >= WIDTH - 10 and abs(g.ball_y - g.paddles['RIGHT']) < PADDLE_SIZE/2:
            g.ball_vx = -abs(g.ball_vx)
        if g.ball_y >= HEIGHT - 10 and abs(g.ball_x - g.paddles['BOTTOM']) < PADDLE_SIZE/2:
            g.ball_vy = -abs(g.ball_vy)

        if g.ball_x <=0: g.ball_vx=abs(g.ball_vx)
        if g.ball_x>=WIDTH: g.ball_vx=-abs(g.ball_vx)
        if g.ball_y<=0: g.ball_vy=abs(g.ball_vy)
        if g.ball_y>=HEIGHT: g.ball_vy=-abs(g.ball_vy)
        for client in list(self.clients.values()):
            with client.lock:
                inp = client.input
                if client.side in ['LEFT','RIGHT']:
                    if inp=='UP': g.paddles[client.side]-=PADDLE_SPEED*dt
                    elif inp=='DOWN': g.paddles[client.side]+=PADDLE_SPEED*dt
                elif client.side=='BOTTOM':
                    if inp=='LEFT': g.paddles['BOTTOM']-=PADDLE_SPEED*dt
                    elif inp=='RIGHT': g.paddles['BOTTOM']+=PADDLE_SPEED*dt
        for k in g.paddles:
            if k in ['LEFT','RIGHT']: g.paddles[k] = max(PADDLE_SIZE/2,min(HEIGHT-PADDLE_SIZE/2,g.paddles[k]))
            else: g.paddles[k] = max(PADDLE_SIZE/2,min(WIDTH-PADDLE_SIZE/2,g.paddles[k]))

    def _broadcast_state(self):
        self.seq +=1
        state = self.game.to_dict(self.seq)
        msg = {'type':'state','seq':self.seq,'state':state}
        encoded = json.dumps(msg).encode('utf-8')
        now = time.time()
        with self.lock:
            clients_copy = list(self.clients.values())
        for client in clients_copy:
            try:
                if client.proto=='tcp':
                    send_tcp_json(client.conn_or_addr, msg)
                else:
                    self.sock.sendto(encoded, client.conn_or_addr)
            except:
                continue

    def _ping_loop(self):
        while self.running:
            msg = json.dumps({'type':'ping','ts':time.time()}).encode('utf-8')
            with self.lock:
                clients_copy = list(self.clients.values())
            for client in clients_copy:
                try:
                    if client.proto=='tcp':
                        send_tcp_json(client.conn_or_addr, {'type':'ping','ts':time.time()})
                    else:
                        self.sock.sendto(msg, client.conn_or_addr)
                except:
                    continue
            time.sleep(1.0)

    def save_statistics(self, filename='stats.json'):
        try:
            with open(filename, 'r') as f:
                all_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            all_data = {}
        
        server_key = f"{self.protocol.upper()}_port_{self.port}"
        
        data = {}
        with self.lock:
            for c in self.clients.values():
                ping = sum(c.pings)/len(c.pings) if c.pings else None
                key = c.side if c.side else str(c.conn_or_addr)
                
                now = time.time()

                c.time_history.append(now)
                c.ping_history.append(ping)
                c.pps_history.append(c.get_pps())
                c.jitter_history.append(c.get_jitter())

                if len(c.time_history) > 10000:
                    c.time_history.pop(0)
                    c.ping_history.pop(0)
                    c.pps_history.pop(0)
                    c.jitter_history.pop(0)

                data[key] = {
                    "current": {
                        'sent': c.sent,
                        'acked': c.acked,
                        'bytes_sent': c.bytes_sent,
                        'pkt_recv': c.pkt_recv,
                        'avg_interval_ms': c.avg_interval,
                        'avg_msg_size_bytes': c.avg_msg_size,
                        'ping_ms': ping,
                        'is_bot': c.is_bot,
                        'is_observer': c.is_observer
                    },
                    "history": {
                        "time": c.time_history,
                        "ping": c.ping_history,
                        "pps": c.pps_history,
                        "jitter": c.jitter_history
                    }
                }
        all_data[server_key] = data

        with open(filename, 'w') as f:
            json.dump(all_data, f, indent=4)

        print(f"[{self.protocol.upper()}] Statistics saved to {filename}")

    def _stats_loop(self):
        while self.running:
            time.sleep(1)
            self.save_statistics()
            
    def draw_plot(self, screen, x, y, width, height, data, color=(0,255,0)):
        if len(data) < 2:
            return
        max_val = max(data)
        min_val = min(data)
        span = max(1, max_val - min_val)
        scaled = [
            height - int((val - min_val) / span * height)
            for val in data
        ]
        step = max(1, width // len(data))
        points = []
        for i, val in enumerate(scaled):
            px = x + i * step
            py = y + val
            points.append((px, py))
        pygame.draw.lines(screen, color, False, points, 2)
        pygame.draw.rect(screen, (180,180,180), (x, y, width, height), 1)

    def get_plot_data(self):
        values = []
        with self.lock:
            for c in self.clients.values():
                if c.pings:
                    avg = sum(c.pings)/len(c.pings)
                    values.append(avg)
        
        if not values:
            values = [0]

        avg_server_ping = sum(values) / len(values)
        return avg_server_ping

    
def draw_game_area(screen, x_off, y_off, game, font, serwer, title="", clients=None):
    pygame.draw.rect(screen, (255,218,185), (x_off-2, y_off-2, WIDTH+4, HEIGHT+4))
    pygame.draw.circle(screen, (255,0,255), (int(x_off + game.ball_x), int(y_off + game.ball_y)), 8)
    pygame.draw.rect(screen, (0,200,0), (x_off + 0, int(y_off + game.paddles['LEFT'] - PADDLE_SIZE/2), 10, PADDLE_SIZE))
    pygame.draw.rect(screen, (200,0,0), (x_off + WIDTH - 10, int(y_off + game.paddles['RIGHT'] - PADDLE_SIZE/2), 10, PADDLE_SIZE))
    pygame.draw.rect(screen, (0,0,200), (x_off + int(game.paddles['BOTTOM'] - PADDLE_SIZE/2), y_off + HEIGHT - 10, PADDLE_SIZE, 10))
    pygame.draw.rect(screen, (60,60,60), (x_off, y_off, WIDTH, HEIGHT), 2)
    title_surf = font.render(title, True, (12,12,12))
    screen.blit(title_surf, (x_off, y_off + HEIGHT + 6))

    if clients is not None:
        for i, c in enumerate(clients.values()):
            ping = sum(c.pings)/len(c.pings) if c.pings else 0
            txt = (f"{c.side} | Sent:{c.sent} Recv:{c.pkt_recv} "
                   f"Bytes:{c.bytes_sent} Δt:{c.avg_interval:.1f}ms "
                   f"Msg:{c.avg_msg_size:.0f}B Ping:{ping:.1f}ms")
            surf = font.render(txt, True, (200,200,200))
            screen.blit(surf, (x_off, y_off + HEIGHT + 26 + i * 18))
    
    value = serwer.get_plot_data()
    serwer.plot_buffer.append(value)
    if len(serwer.plot_buffer) > 300: 
        serwer.plot_buffer.pop(0)
    
    plot_x = x_off
    plot_y = y_off + HEIGHT + 26 + len(clients)*18 + 20
    plot_w = WIDTH
    plot_h = 120

    serwer.draw_plot(screen, plot_x, plot_y, plot_w, plot_h, serwer.plot_buffer)


def start_client(host, port, protocol):
    from klient import PongClient  
    client = PongClient(host=host, port=port, protocol=protocol)
    client.run()
    

if __name__ == '__main__':
    pygame.init()

    tcp_port = 52000
    udp_port = 53000
    host = '127.0.0.1'
    tcp_server = PongServer(protocol='tcp', port=tcp_port, name='TCP')
    udp_server = PongServer(protocol='udp', port=udp_port, name='UDP')

    time.sleep(0.2)  

    processes = []
    WIN_W = WIDTH * 2 + 200
    WIN_H = HEIGHT + 300
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption('Two Pong Servers: TCP (left) | UDP (right)')
    font = pygame.font.SysFont(None, 20)
    clock = pygame.time.Clock()     
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
        screen.fill((255, 255, 255))
        draw_game_area(screen, 10, 10, tcp_server.game, font, tcp_server, 
                      title=f"TCP Server (port {tcp_port})", clients=tcp_server.clients) 
        draw_game_area(screen, WIDTH + 20, 10, udp_server.game, font, udp_server,
                      title=f"UDP Server (port {udp_port})", clients=udp_server.clients)
        pygame.display.flip()
        clock.tick(FPS)   

    tcp_server.running = False
    udp_server.running = False
    pygame.quit()

    for p in processes:
        p.terminate()
