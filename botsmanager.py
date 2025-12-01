import threading
import time
from BotTCP import BotTCP
from BotUDP import BotUDP

class AutoBotManager:
    def __init__(self, tcp_host='127.0.0.1', tcp_port=52000,
                       udp_host='127.0.0.1', udp_port=53000,
                       check_interval=1.0):
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port
        self.udp_host = udp_host
        self.udp_port = udp_port
        self.check_interval = check_interval

        self.sides = ['LEFT', 'RIGHT', 'BOTTOM']

        self.tcp_bots = {}  
        self.udp_bots = {}

        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            self._update_bots()
            time.sleep(self.check_interval)

    def _update_bots(self):
        try:
            from __main__ import tcp_server, udp_server
        except ImportError:
            return

        tcp_taken = {c.side for c in tcp_server.clients.values() if not c.is_observer}
        for side in self.sides:
            if side not in tcp_taken and side not in self.tcp_bots:
                bot = BotTCP(host='127.0.0.1', port=self.port, name=f"TCPBot-{side}", side=side)
                self.tcp_bots[side] = bot
                print(f"[AutoBotManager] TCP Bot added to {side}")
            elif side in tcp_taken and side in self.tcp_bots:
                self.tcp_bots[side].running = False
                del self.tcp_bots[side]
                print(f"[AutoBotManager] TCP Bot removed from {side}")

        udp_taken = {c.side for c in udp_server.clients.values() if not c.is_observer}
        for side in self.sides:
            if side not in udp_taken and side not in self.udp_bots:
                bot = BotUDP(host='127.0.0.1', port=self.port, name=f"UDPBot-{side}", side=side)
                self.udp_bots[side] = bot
                print(f"[AutoBotManager] UDP Bot added to {side}")
            elif side in udp_taken and side in self.udp_bots:
                self.udp_bots[side].running = False
                del self.udp_bots[side]
                print(f"[AutoBotManager] UDP Bot removed from {side}")


if __name__ == '__main__':
    manager = AutoBotManager()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        manager.running = False
        print("AutoBotManager stopped")