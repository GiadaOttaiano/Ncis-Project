from mininet.net import Mininet
from mininet.cli import CLI
from mininet.node import RemoteController
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from topology import Environment  # Assicurati che questo sia il nome del tuo file di topologia
import time

def start_monitoring(net):
    h2 = net.get('h2')
    h3 = net.get('h3')

    # Monitoraggio della latenza
    info('Starting latency monitoring...\n')
    with open('/tmp/latency.log', 'w') as f:
        f.write('Time(ms)\n')
        for _ in range(60):  # Monitoraggio per 60 secondi
            latency = h2.cmd('ping -c 1 10.0.0.3 | grep "time=" | awk -F"time=" \'{print $2}\' | awk \'{print $1}\'')
            f.write(f'{latency.strip()}\n')
            time.sleep(1)

def analyze_logs():
    # Analizza i log di iperf e latenza
    info('Analyzing logs...\n')

    # Analisi del log di iperf
    with open('/tmp/h2-iperf.log', 'r') as f:
        iperf_log = f.read()

    # Estrazione di throughput e perdita di pacchetti
    lines = iperf_log.splitlines()
    throughput = []
    packet_loss = None
    for line in lines:
        if 'bit/sec' in line:
            throughput.append(line)
        if 'Loss' in line:
            packet_loss = line

    # Report di throughput
    info('Throughput Report:\n')
    for line in throughput:
        info(f'{line}\n')

    # Report di perdita di pacchetti
    if packet_loss:
        info(f'Packet Loss Report:\n{packet_loss}\n')
    else:
        info('No packet loss reported.\n')

    # Analisi della latenza
    with open('/tmp/latency.log', 'r') as f:
        latency_lines = f.readlines()

    # Calcolo della latenza media
    latencies = [float(line.strip()) for line in latency_lines[1:] if line.strip()]
    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        jitter = max(latencies) - min(latencies)  # Jitter come la differenza tra max e min latenza
        info(f'Average Latency: {avg_latency:.2f} ms\n')
        info(f'Jitter: {jitter:.2f} ms\n')
    else:
        info('No latency data collected.\n')

def main():
    setLogLevel('info')
    topo = Environment()
    net = Mininet(topo=topo, controller=RemoteController, link=TCLink)
    net.addController('c0')
    net.start()

    start_monitoring(net)
    
    # Attendi per la durata del monitoraggio
    time.sleep(60)
    analyze_logs()

    net.stop()

if __name__ == '__main__':
    main()
