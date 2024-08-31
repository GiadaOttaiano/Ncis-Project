from mininet.net import Mininet
from mininet.cli import CLI
from mininet.node import RemoteController
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from topology import Environment  # Importa la topologia dal file di topologia

def start_iperf(net):
    # Avvia iperf server su h3
    h3 = net.get('h3')
    h3.cmd('iperf -s > /tmp/h3-iperf.log &')

    # Avvia iperf client UDP su h1 (attacker)
    h1 = net.get('h1')
    h1.cmd('iperf -u -c 10.0.0.3 -b 100M > /tmp/h1-iperf.log &')

    # Avvia iperf client TCP su h2
    h2 = net.get('h2')
    h2.cmd('iperf -c 10.0.0.3 -b 5M > /tmp/h2-iperf.log &')

def stop_iperf(net):
    # Interrompe iperf su h1, h2 e h3
    h1 = net.get('h1')
    h2 = net.get('h2')
    h3 = net.get('h3')

    h1.cmd('killall iperf')
    h2.cmd('killall iperf')
    h3.cmd('killall iperf')

def main():
    setLogLevel('info')
    topo = Environment()
    net = Mininet(topo=topo, controller=RemoteController, link=TCLink)
    net.addController('c0')
    net.start()

    info('Starting iperf tests...\n')
    start_iperf(net)
    
    # Avvia lo script di monitoraggio come processo separato
    info('Starting report script...\n')
    report_process = subprocess.Popen(['python3', 'report.py'])
    
    # Attendi che l'utente termini la sessione CLI
    CLI(net)
    
    # Termina il processo di monitoraggio quando la CLI viene chiusa
    report_process.terminate()
    report_process.wait()

    info('Stopping iperf tests...\n')
    stop_iperf(net)
    net.stop()

if __name__ == '__main__':
    main()