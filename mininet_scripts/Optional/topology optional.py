import threading
import random
import time
from mininet.log import setLogLevel, info
from mininet.topo import Topo
from mininet.net import Mininet, CLI
from mininet.node import OVSKernelSwitch, Host
from mininet.link import TCLink, Link
from mininet.node import RemoteController #Controller

class Environment(object):
    def _init_(self):
        "Create a network."
        self.net = Mininet(controller=RemoteController, link=TCLink)
        
        info("*** Starting controller\n")
        c1 = self.net.addController( 'c1', controller=RemoteController) #Controller
        c1.start()
        
        info("*** Adding hosts and switches\n")
        self.h1 = self.net.addHost('h1', mac ='00:00:00:00:00:01', ip= '10.0.0.1')
        self.h2 = self.net.addHost('h2', mac ='00:00:00:00:00:02', ip= '10.0.0.2')
        self.h3 = self.net.addHost('h3', mac ='00:00:00:00:00:03', ip= '10.0.0.3')
        self.h4 = self.net.addHost('h4', mac ='00:00:00:00:00:04', ip= '10.0.0.4')
        self.cpe1 = self.net.addSwitch('s1', cls=OVSKernelSwitch)
        self.cpe2 = self.net.addSwitch('s2', cls=OVSKernelSwitch)
        self.core = self.net.addSwitch('s3', cls=OVSKernelSwitch)
        self.cpe4 = self.net.addSwitch('s4', cls=OVSKernelSwitch)
        
        info("*** Adding links\n")  
        self.net.addLink(self.h1, self.cpe1, bw=10, delay='0.0010ms')
        self.net.addLink(self.h4, self.cpe1, bw=10, delay='0.0010ms')
        self.net.addLink(self.h2, self.cpe2, bw=10, delay='0.0010ms')
        self.net.addLink(self.cpe1, self.core, bw=10, delay='0.0010ms')
        self.net.addLink(self.cpe2, self.core, bw=5, delay='10ms')
        self.net.addLink(self.cpe4, self.core, bw=5, delay='10ms')
        self.net.addLink(self.cpe4, self.h3, bw=5, delay='10ms')
         
        info("*** Starting network\n")
        self.net.build()
        self.net.start()

...
if _name_ == '_main_':

    setLogLevel('info')
    info('starting the environment\n')
    env = Environment()

    info("*** Running CLI\n")
    CLI(env.net)