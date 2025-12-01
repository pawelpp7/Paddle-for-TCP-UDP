import json
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

def plot_stats(json_file, output_prefix="plot"):
    with open(json_file, "r") as f:
        data = json.load(f)
    
    # Iteruj przez serwery (TCP_port_52000, UDP_port_53000)
    for server_name, server_data in data.items():
        print(f"\n[PLOT] Processing server: {server_name}")
        
        # Zbierz wszystkie dane klientów tego serwera
        all_clients = {}
        for client, stats in server_data.items():
            hist = stats["history"]
            
            # Pomiń klientów bez danych historycznych
            if not hist["time"] or len(hist["time"]) < 2:
                continue
            
            # Konwertujczas na relative (od pierwszego pomiaru)
            t = np.array(hist["time"])
            t_rel = t - t[0]  # czas względny w sekundach
            
            # Filtruj None wartości dla ping
            ping = np.array([p if p is not None else np.nan for p in hist["ping"]])
            
            # Jitter w ms
            jitter = np.array([j * 1000 if j is not None else np.nan for j in hist["jitter"]])
            
            # PPS
            pps = np.array([p if p is not None else np.nan for p in hist["pps"]])
            
            all_clients[client] = {
                'time': t_rel,
                'ping': ping,
                'jitter': jitter,
                'pps': pps,
                'is_bot': stats["current"].get("is_bot", False),
                'is_observer': stats["current"].get("is_observer", False)
            }
        
        if not all_clients:
            print(f"[PLOT] No data for {server_name}, skipping...")
            continue
        
        # ====================
        # Wykres 1: Porównanie wszystkich klientów na jednym wykresie
        # ====================
        fig, axes = plt.subplots(3, 1, figsize=(14, 10))
        fig.suptitle(f'Network Statistics - {server_name}', fontsize=16, fontweight='bold')
        
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']
        
        for idx, (client, client_data) in enumerate(all_clients.items()):
            color = colors[idx % len(colors)]
            label_suffix = " (bot)" if client_data['is_bot'] else " (player)"
            if client_data['is_observer']:
                label_suffix = " (observer)"
            
            # Ping
            axes[0].plot(client_data['time'], client_data['ping'], 
                        label=f"{client}{label_suffix}", color=color, linewidth=1.5, alpha=0.8)
            
            # Jitter
            axes[1].plot(client_data['time'], client_data['jitter'], 
                        label=f"{client}{label_suffix}", color=color, linewidth=1.5, alpha=0.8)
            
            # PPS
            axes[2].plot(client_data['time'], client_data['pps'], 
                        label=f"{client}{label_suffix}", color=color, linewidth=1.5, alpha=0.8)
        
        # Ping
        axes[0].set_ylabel("Ping (ms)", fontsize=12, fontweight='bold')
        axes[0].set_title("Round-Trip Time (Ping)", fontsize=13)
        axes[0].grid(True, alpha=0.3, linestyle='--')
        axes[0].legend(loc='upper right', framealpha=0.9)
        axes[0].set_ylim(bottom=0)
        
        # Jitter
        axes[1].set_ylabel("Jitter (ms)", fontsize=12, fontweight='bold')
        axes[1].set_title("Network Jitter", fontsize=13)
        axes[1].grid(True, alpha=0.3, linestyle='--')
        axes[1].legend(loc='upper right', framealpha=0.9)
        axes[1].set_ylim(bottom=0)
        
        # PPS
        axes[2].set_ylabel("Packets/sec", fontsize=12, fontweight='bold')
        axes[2].set_xlabel("Time (seconds)", fontsize=12, fontweight='bold')
        axes[2].set_title("Packets Per Second", fontsize=13)
        axes[2].grid(True, alpha=0.3, linestyle='--')
        axes[2].legend(loc='upper right', framealpha=0.9)
        axes[2].set_ylim(bottom=0)
        
        plt.tight_layout()
        filename = f"{output_prefix}_{server_name}_combined.png"
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[PLOT] Saved: {filename}")
        
        # ====================
        # Wykres 2: Indywidualne wykresy dla każdego klienta
        # ====================
        for client, client_data in all_clients.items():
            fig, axes = plt.subplots(3, 1, figsize=(12, 9))
            
            label_type = "Bot" if client_data['is_bot'] else "Player"
            if client_data['is_observer']:
                label_type = "Observer"
            
            fig.suptitle(f'{server_name} - {client} ({label_type})', 
                        fontsize=16, fontweight='bold')
            
            # Ping z statystykami
            valid_ping = client_data['ping'][~np.isnan(client_data['ping'])]
            if len(valid_ping) > 0:
                avg_ping = np.mean(valid_ping)
                min_ping = np.min(valid_ping)
                max_ping = np.max(valid_ping)
                std_ping = np.std(valid_ping)
                
                axes[0].plot(client_data['time'], client_data['ping'], 
                           color='#1f77b4', linewidth=2, alpha=0.8)
                axes[0].axhline(y=avg_ping, color='red', linestyle='--', 
                              linewidth=1.5, label=f'Avg: {avg_ping:.2f} ms')
                axes[0].fill_between(client_data['time'], 
                                    avg_ping - std_ping, avg_ping + std_ping,
                                    alpha=0.2, color='red', label=f'±1 std: {std_ping:.2f} ms')
                axes[0].set_title(f'Ping (min: {min_ping:.2f}, max: {max_ping:.2f} ms)', 
                                fontsize=12)
            else:
                axes[0].set_title('Ping (no data)', fontsize=12)
            
            axes[0].set_ylabel("Ping (ms)", fontsize=11, fontweight='bold')
            axes[0].grid(True, alpha=0.3, linestyle='--')
            axes[0].legend(loc='upper right')
            axes[0].set_ylim(bottom=0)
            
            # Jitter z statystykami
            valid_jitter = client_data['jitter'][~np.isnan(client_data['jitter'])]
            if len(valid_jitter) > 0:
                avg_jitter = np.mean(valid_jitter)
                max_jitter = np.max(valid_jitter)
                
                axes[1].plot(client_data['time'], client_data['jitter'], 
                           color='#ff7f0e', linewidth=2, alpha=0.8)
                axes[1].axhline(y=avg_jitter, color='red', linestyle='--', 
                              linewidth=1.5, label=f'Avg: {avg_jitter:.2f} ms')
                axes[1].set_title(f'Jitter (max: {max_jitter:.2f} ms)', fontsize=12)
            else:
                axes[1].set_title('Jitter (no data)', fontsize=12)
            
            axes[1].set_ylabel("Jitter (ms)", fontsize=11, fontweight='bold')
            axes[1].grid(True, alpha=0.3, linestyle='--')
            axes[1].legend(loc='upper right')
            axes[1].set_ylim(bottom=0)
            
            # PPS z statystykami
            valid_pps = client_data['pps'][~np.isnan(client_data['pps'])]
            if len(valid_pps) > 0:
                avg_pps = np.mean(valid_pps)
                min_pps = np.min(valid_pps)
                max_pps = np.max(valid_pps)
                
                axes[2].plot(client_data['time'], client_data['pps'], 
                           color='#2ca02c', linewidth=2, alpha=0.8)
                axes[2].axhline(y=avg_pps, color='red', linestyle='--', 
                              linewidth=1.5, label=f'Avg: {avg_pps:.2f} pkt/s')
                axes[2].set_title(f'PPS (min: {min_pps:.2f}, max: {max_pps:.2f})', 
                                fontsize=12)
            else:
                axes[2].set_title('PPS (no data)', fontsize=12)
            
            axes[2].set_ylabel("Packets/sec", fontsize=11, fontweight='bold')
            axes[2].set_xlabel("Time (seconds)", fontsize=11, fontweight='bold')
            axes[2].grid(True, alpha=0.3, linestyle='--')
            axes[2].legend(loc='upper right')
            axes[2].set_ylim(bottom=0)
            
            plt.tight_layout()
            filename = f"{output_prefix}_{server_name}_{client}.png"
            plt.savefig(filename, dpi=150, bbox_inches='tight')
            plt.close()
            print(f"[PLOT] Saved: {filename}")
        
        # ====================
        # Wykres 3: Statystyki porównawcze (box plots)
        # ====================
        if len(all_clients) > 1:
            fig, axes = plt.subplots(1, 3, figsize=(16, 5))
            fig.suptitle(f'Comparative Statistics - {server_name}', 
                        fontsize=16, fontweight='bold')
            
            client_names = []
            ping_data = []
            jitter_data = []
            pps_data = []
            
            for client, client_data in all_clients.items():
                label_suffix = " (bot)" if client_data['is_bot'] else ""
                client_names.append(f"{client}{label_suffix}")
                
                valid_ping = client_data['ping'][~np.isnan(client_data['ping'])]
                valid_jitter = client_data['jitter'][~np.isnan(client_data['jitter'])]
                valid_pps = client_data['pps'][~np.isnan(client_data['pps'])]
                
                ping_data.append(valid_ping if len(valid_ping) > 0 else [0])
                jitter_data.append(valid_jitter if len(valid_jitter) > 0 else [0])
                pps_data.append(valid_pps if len(valid_pps) > 0 else [0])
            
            # Box plots
            bp1 = axes[0].boxplot(ping_data, labels=client_names, patch_artist=True)
            axes[0].set_ylabel("Ping (ms)", fontsize=11, fontweight='bold')
            axes[0].set_title("Ping Distribution", fontsize=12)
            axes[0].grid(True, alpha=0.3, axis='y')
            axes[0].tick_params(axis='x', rotation=15)
            
            bp2 = axes[1].boxplot(jitter_data, labels=client_names, patch_artist=True)
            axes[1].set_ylabel("Jitter (ms)", fontsize=11, fontweight='bold')
            axes[1].set_title("Jitter Distribution", fontsize=12)
            axes[1].grid(True, alpha=0.3, axis='y')
            axes[1].tick_params(axis='x', rotation=15)
            
            bp3 = axes[2].boxplot(pps_data, labels=client_names, patch_artist=True)
            axes[2].set_ylabel("Packets/sec", fontsize=11, fontweight='bold')
            axes[2].set_title("PPS Distribution", fontsize=12)
            axes[2].grid(True, alpha=0.3, axis='y')
            axes[2].tick_params(axis='x', rotation=15)
            
            # Kolorowanie box plots
            for bp, color in zip([bp1, bp2, bp3], ['#1f77b4', '#ff7f0e', '#2ca02c']):
                for patch in bp['boxes']:
                    patch.set_facecolor(color)
                    patch.set_alpha(0.6)
            
            plt.tight_layout()
            filename = f"{output_prefix}_{server_name}_comparison.png"
            plt.savefig(filename, dpi=150, bbox_inches='tight')
            plt.close()
            print(f"[PLOT] Saved: {filename}")
            

    server_names = []
    avg_ping_values = []
    avg_jitter_values = []
    avg_pps_values = []

    for server_name, server_data in data.items():
        all_pings = []
        all_jitters = []
        all_pps = []

        for client, stats in server_data.items():
            hist = stats["history"]

            # pomijamy brak danych
            if not hist["time"] or len(hist["time"]) < 2:
                continue

            # ping
            valid_ping = [p for p in hist["ping"] if p is not None]
            all_pings.extend(valid_ping)

            # jitter (ms)
            valid_jitter = [j * 1000 for j in hist["jitter"] if j is not None]
            all_jitters.extend(valid_jitter)

            # PPS
            valid_pps = [p for p in hist["pps"] if p is not None]
            all_pps.extend(valid_pps)

        if not all_pings:
            continue

        server_names.append(server_name)
        avg_ping_values.append(np.mean(all_pings))
        avg_jitter_values.append(np.mean(all_jitters))
        avg_pps_values.append(np.mean(all_pps))

    if len(server_names) >= 2:
        x = np.arange(len(server_names))
        w = 0.25

        plt.figure(figsize=(12, 6))

        plt.bar(x - w, avg_ping_values, width=w)
        plt.bar(x,     avg_jitter_values, width=w)
        plt.bar(x + w, avg_pps_values, width=w)

        plt.xticks(x, server_names)

        plt.tight_layout()
        filename = f"{output_prefix}_TCP_vs_UDP_comparison.png"
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[PLOT] Saved: {filename}")


if __name__ == "__main__":
    plot_stats("stats.json", output_prefix="network_plot")