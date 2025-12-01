
import socket
import threading
import json
import time
import struct
from collections import deque
from BotTCP import BotTCP
from BotUDP import BotUDP
import pygame
import random

WIDTH, HEIGHT = 600, 600
BALL_SPEED = 150.0
PADDLE_SPEED = 100.0
PADDLE_SIZE = 80
FPS = 30
TICK = 1.0 / FPS

def send_tcp_json(conn, data):
    try:
        msg = json.dumps(data).encode('utf-8')
        length = struct.pack('>I', len(msg))
        conn.sendall(length + msg)
    except Exception:
        pass

def recv_tcp_json(conn):
    try:
        header = conn.recv(4)
        if not header:
            return None
        (length,) = struct.unpack('>I', header)
        data = b''
        while len(data) < length:
            chunk = conn.recv(length - len(data))
            if not chunk:
                return None
            data += chunk
        return json.loads(data.decode('utf-8'))
    except Exception:
        return None

class GameState:
    def __init__(self):
        self.ball_x, self.ball_y = WIDTH / 2, HEIGHT / 2
        angle = random.uniform(-0.7,0.7)
        self.ball_vx = BALL_SPEED * (1 if random.random() < 0.5 else -1)
        self.ball_vy = BALL_SPEED * angle
        self.paddles = {'LEFT': HEIGHT / 2, 'RIGHT': HEIGHT / 2, 'BOTTOM': WIDTH / 2}
        self.scores = {'LEFT': 0, 'RIGHT': 0, 'BOTTOM': 0}

    def to_dict(self, seq):
        return {'seq': seq, 'ball': (self.ball_x, self.ball_y), 'paddles': self.paddles.copy(), 'scores': self.scores.copy()}

class ClientInfo:
    def __init__(self, conn_or_addr, side, proto):
        self.conn_or_addr = conn_or_addr 
        self.side = side
        self.proto = proto
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

        if protocol == 'tcp':
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(('0.0.0.0', port))
            self.sock.listen(5)
        else:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(('0.0.0.0', port))

        self._start_threads()

    def _start_threads(self):
        if self.protocol == 'tcp':
            threading.Thread(target=self._accept_loop, daemon=True).start()
        else:
            threading.Thread(target=self._udp_recv_loop, daemon=True).start()
        
        threading.Thread(target=self._game_loop, daemon=True).start()
        threading.Thread(target=self._ping_loop, daemon=True).start()

    def _accept_loop(self):
        sides = ['LEFT', 'RIGHT', 'BOTTOM']
        idx = 0
        while self.running:
            try:
                conn, addr = self.sock.accept()
                conn.settimeout(1.0)
                side = sides[idx % 3]
                idx += 1

                with self.lock:
                    self._remove_bot_for_side(side)
                    client = ClientInfo(conn, side, 'tcp')
                    self.clients[conn.fileno()] = client

                time.sleep(0.1)
                send_tcp_json(conn, {'type': 'assign', 'side': side})
                print(f"[SERVER] assign sent -> {side} to {addr}")

                threading.Thread(target=self._handle_tcp_client, args=(conn,), daemon=True).start()
            except Exception as e:
                print("accept error:", e)
                continue


    def _handle_tcp_client(self, conn):
        fileno = conn.fileno()
        while self.running:
            msg = recv_tcp_json(conn)
            if not msg:
                break
            self._process_msg(msg, self.clients.get(fileno))
        try:
            conn.close()
        except Exception:
            pass
        if fileno in self.clients:
            del self.clients[fileno]

    def _udp_recv_loop(self):
        sides = ['LEFT', 'RIGHT', 'BOTTOM']
        idx = 0
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                msg = json.loads(data.decode('utf-8'))
                if addr not in self.clients and msg.get('type') == 'register':
                    side = sides[idx % 3]; idx += 1
                    self._remove_bot_for_side(side)
                    client = ClientInfo(addr, side, 'udp')
                    self.clients[addr] = client
                    assign = json.dumps({'type': 'assign', 'side': side}).encode('utf-8')
                    self.sock.sendto(assign, addr)
                else:
                    client = self.clients.get(addr)
                    if client:
                        self._process_msg(msg, client)
            except Exception:
                continue

    def _process_msg( self, msg, client):
        if not client:
            return
        client.pkt_recv += 1

        t = msg.get('type')
        if t == 'input':
            with client.lock:
                client.input = msg.get('input')
        elif t == 'ack':
            client.acked += 1
        elif t == 'pong':
            client.pings.append((time.time() - msg['ts']) * 1000)
   
    def _broadcast_state(self):
        self.seq += 1
        state = self.game.to_dict(self.seq)
        msg = {'type': 'state', 'seq': self.seq, 'state': state}
        encoded = json.dumps(msg).encode('utf-8')

        now = time.time()
        with self.lock:
            clients_copy = list(self.clients.values())

        for client in clients_copy:
            try:
                if client.proto == 'tcp':
                    conn = client.conn_or_addr
                    send_tcp_json(conn, msg)
                else:
                    addr = client.conn_or_addr
                    self.sock.sendto(encoded, addr)

                client.sent += 1
                client.bytes_sent += len(encoded)
                client.last_msg_size = len(encoded)
                if client.last_send_time != 0:
                    interval = (now - client.last_send_time) * 1000
                    client.avg_interval = client.avg_interval * 0.8 + interval * 0.2
                client.last_send_time = now
                if client.avg_msg_size == 0:
                    client.avg_msg_size = len(encoded)
                else:
                    client.avg_msg_size = client.avg_msg_size * 0.8 + len(encoded) * 0.2

            except Exception:
                continue


    def _game_loop(self):
        last_time = time.time()
        while self.running:
            now = time.time()
            dt = now - last_time
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

        for client in list(self.clients.values()):
            with client.lock:
                inp = client.input
                if client.side in ['LEFT', 'RIGHT']:
                    if inp == 'UP':
                        g.paddles[client.side] -= PADDLE_SPEED * dt
                    elif inp == 'DOWN':
                        g.paddles[client.side] += PADDLE_SPEED * dt
                elif client.side == 'BOTTOM':
                    if inp == 'LEFT':
                        g.paddles['BOTTOM'] -= PADDLE_SPEED * dt
                    elif inp == 'RIGHT':
                        g.paddles['BOTTOM'] += PADDLE_SPEED * dt

        for k in g.paddles:
            if k in ['LEFT','RIGHT']:
                g.paddles[k] = max(PADDLE_SIZE/2, min(HEIGHT - PADDLE_SIZE/2, g.paddles[k]))
            else:
                g.paddles[k] = max(PADDLE_SIZE/2, min(WIDTH - PADDLE_SIZE/2, g.paddles[k]))

    def _ping_loop(self): 
        while self.running:
            msg = json.dumps({'type': 'ping', 'ts': time.time()}).encode('utf-8')
            with self.lock:
                clients_copy = list(self.clients.values())

            for client in clients_copy:
                try:
                    if client.proto == 'tcp':
                        send_tcp_json(client.conn_or_addr, {'type': 'ping', 'ts': time.time()})
                    else:
                        self.sock.sendto(msg, client.conn_or_addr)
                except Exception:
                    continue
            time.sleep(1.0)  
    def _remove_bot_for_side(self, side):
        to_remove = None
        for key, client in list(self.clients.items()):
            print(f"s { side }")
            print(f"k {client.side}")
            if client.side == side:
                if client.proto == 'tcp':
                    try:
                        peer = client.conn_or_addr.getpeername()[0]
                    except Exception:
                        peer = None
                else:
                    peer = client.conn_or_addr[0] if isinstance(client.conn_or_addr, tuple) else None

                if peer == '127.0.0.1': 
                    to_remove = key
                    try:
                        if client.proto == 'tcp':
                            time.sleep(1)
                            client.conn_or_addr.close()
                        print(f" Usunięto bota z pozycji {side}.")
                    except Exception as e:
                        print(f"Błąd przy usuwaniu bota: {e}")
                    break

        if to_remove:
            del self.clients[to_remove]

    

def main():
    pygame.init()
    WIN_W = WIDTH * 2 + 20
    WIN_H = HEIGHT + 100
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption('Two Pong Servers: TCP (left) | UDP (right)')
    font = pygame.font.SysFont(None, 20)
    clock = pygame.time.Clock()

    tcp_port = 52000
    udp_port = 53000
    tcp_server = PongServer(protocol='tcp', port=tcp_port, name='TCP')
    udp_server = PongServer(protocol='udp', port=udp_port, name='UDP')

    time.sleep(0.2)

    tcp_bots = []
    for i in range(3):
        bot = BotTCP(host='127.0.0.1', port=tcp_port, name=f'TCPBot{i+1}')
        tcp_bots.append(bot)
        time.sleep(0.05)

    udp_bots = []
    for i in range(3):
        bot = BotUDP(host='127.0.0.1', port=udp_port, name=f'UDPBot{i+1}')
        udp_bots.append(bot)
        time.sleep(0.05)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        screen.fill((255, 255, 255))

        draw_game_area(screen, 10, 10, tcp_server.game, font, title=f"TCP Server (port {tcp_port})", clients=tcp_server.clients)

        draw_game_area(screen, WIDTH + 20, 10, udp_server.game, font, title=f"UDP Server (port {udp_port})", clients=udp_server.clients)
        
        pygame.display.flip()
        clock.tick(FPS)

    tcp_server.running = False
    udp_server.running = False
    pygame.quit()



def draw_game_area(screen, x_off, y_off, game, font, title="", clients=None):
    pygame.draw.rect(screen, (255,218,185), (x_off-2, y_off-2, WIDTH+4, HEIGHT+4))
    pygame.draw.circle(screen, (255,0,255), (int(x_off + game.ball_x), int(y_off + game.ball_y)), 8)
    pygame.draw.rect(screen, (0,200,0), (x_off + 0, int(y_off + game.paddles['LEFT'] - PADDLE_SIZE/2), 10, PADDLE_SIZE))
    pygame.draw.rect(screen, (200,0,0), (x_off + WIDTH - 10, int(y_off + game.paddles['RIGHT'] - PADDLE_SIZE/2), 10, PADDLE_SIZE))
    pygame.draw.rect(screen, (0,0,200), (x_off + int(game.paddles['BOTTOM'] - PADDLE_SIZE/2), y_off + HEIGHT - 10, PADDLE_SIZE, 10))
    pygame.draw.rect(screen, (60,60,60), (x_off, y_off, WIDTH, HEIGHT), 2)
    title_surf = font.render(title, True, (12,12,12))
    screen.blit(title_surf, (x_off, y_off + HEIGHT + 6))


    if clients is not None:
        i = 0
        for c in clients.values():
            ping = sum(c.pings)/len(c.pings) if c.pings else 0
            txt = (f"{c.side} | Sent:{c.sent} Recv:{c.pkt_recv} "
                   f"Bytes:{c.bytes_sent} Δt:{c.avg_interval:.1f}ms "
                   f"Msg:{c.avg_msg_size:.0f}B Ping:{ping:.1f}ms")
            surf = font.render(txt, True, (12,12,12))
            screen.blit(surf, (x_off, y_off + HEIGHT + 26 + i * 18))
            i += 1

if __name__ == '__main__':
    main()  