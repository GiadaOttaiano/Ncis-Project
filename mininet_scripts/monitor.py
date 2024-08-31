from mininet.net import Mininet
from mininet.cli import CLI
from mininet.node import RemoteController
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from topology import Environment  # Assicurati che questo sia il nome del tuo file di topologia
import time

def start_monitoring(net):
    h2 = net.get('h2')
    core_switch = net.get('s3')  # Switch core

    # Monitoraggio del throughput con iperf
    info('Starting throughput monitoring...\n')
    h2.cmd('iperf -c 10.0.0.3 -t 60 > /tmp/h2-iperf.log &')
    time.sleep(5)

    # Monitoraggio della latenza
    info('Starting latency monitoring...\n')
    with open('/tmp/latency.log', 'w') as f:
        f.write('Time(ms)\n')
        for _ in range(60):  # Monitoraggio per 60 secondi
            latency = h2.cmd('ping -c 1 10.0.0.3 | grep "time=" | awk -F"time=" \'{print $2}\' | awk \'{print $1}\'')
            f.write(f'{latency.strip()}\n')
            time.sleep(1)

    # Monitoraggio della perdita di pacchetti
    info('Starting packet loss monitoring...\n')
    h2.cmd('tcpdump -i h2-eth0 icmp -w /tmp/h2-packet-loss.pcap &')

    # Monitoraggio delle statistiche dello switch core
    info('Starting core switch monitoring...\n')
    core_switch.cmd('ovs-ofctl dump-ports-desc s3 > /tmp/core-switch-stats.txt &')

def stop_monitoring(net):
    # Interrompe i processi di monitoraggio
    h2 = net.get('h2')
    core_switch = net.get('s3')
    h2.cmd('killall iperf')
    h2.cmd('killall tcpdump')
    core_switch.cmd('pkill -f "ovs-ofctl dump-ports-desc s3"')

def analyze_logs():
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

    # Calcolo della latenza media e del jitter
    latencies = [float(line.strip()) for line in latency_lines[1:] if line.strip()]
    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        jitter = max(latencies) - min(latencies)  # Jitter come la differenza tra max e min latenza
        info(f'Average Latency: {avg_latency:.2f} ms\n')
        info(f'Jitter: {jitter:.2f} ms\n')
    else:
        info('No latency data collected.\n')

    # Analisi della perdita di pacchetti
    info('Analyzing packet loss...\n')
    # Conversione del file pcap in un formato leggibile
    h2 = net.get('h2')
    h2.cmd('tcpdump -r /tmp/h2-packet-loss.pcap > /tmp/h2-packet-loss.txt')
    
    # Analisi semplice del file di pacchetti
    with open('/tmp/h2-packet-loss.txt', 'r') as f:
        packet_loss_lines = f.readlines()

    packet_loss_count = sum('ICMP' in line for line in packet_loss_lines)
    total_packets_sent = len(packet_loss_lines)
    
    if total_packets_sent > 0:
        loss_percentage = (packet_loss_count / total_packets_sent) * 100
        info(f'Packet Loss Percentage: {loss_percentage:.2f}%\n')
    else:
        info('No packet loss data available.\n')

    # Analisi delle statistiche dello switch core
    info('Analyzing core switch stats...\n')
    with open('/tmp/core-switch-stats.txt', 'r') as f:
        core_switch_stats = f.read()

    info(f'Core Switch Stats:\n{core_switch_stats}\n')

def main():
    setLogLevel('info')
    topo = Environment()
    net = Mininet(topo=topo, controller=RemoteController, link=TCLink)
    net.addController('c0')
    net.start()

    start_monitoring(net)
    
    # Attendi per la durata del monitoraggio
    time.sleep(60)
    stop_monitoring(net)
    analyze_logs()

    net.stop()

if __name__ == '__main__':
    main()
