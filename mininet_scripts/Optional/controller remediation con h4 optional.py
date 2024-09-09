from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.lib import hub
import time

class TrafficMonitor(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(TrafficMonitor, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.monitor_thread = hub.spawn(self._monitor_traffic)
        self.prev_stats = {}
        self.THROUGHPUT_THRESHOLD = 1000000  # Threshold in Bytes/sec
        self.alarm = {}  # Dictionary to store alarms per MAC address
        self.unblock_time = {}  # Dictionary to store unblock times per MAC
        self.blocked_flows = {}  # Dictionary to store blocked MACs

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Install table-miss flow entry
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        self.datapaths[datapath.id] = datapath

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        instructions = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        if buffer_id is not None:
            flow_mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                         priority=priority, match=match,
                                         instructions=instructions)
        else:
            flow_mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                         match=match, instructions=instructions)
        datapath.send_msg(flow_mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})

        self.logger.info("Packet in: switch=%s, src=%s, dst=%s, in_port=%s", dpid, src, dst, in_port)
        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            if msg.buffer_id != 0xFFFFFFFF:  # Buffer ID for no buffer
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
                return
            else:
                self.add_flow(datapath, 1, match, actions)

        data = None
        if msg.buffer_id == 0xFFFFFFFF:  # Buffer ID for no buffer
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

    def _monitor_traffic(self):
        while True:
            for dp in self.datapaths.values():
                self._request_port_stats(dp)
            hub.sleep(10)  # Monitor every 10 seconds

    def _request_port_stats(self, datapath):
        self.logger.debug('Sending stats request: %016x', datapath.id)
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        request = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(request)

    def _calculate_throughput(self, dpid, port_no, rx_bytes, tx_bytes, prev_stats):
        prev_rx_bytes, prev_tx_bytes, prev_time = prev_stats
        current_time = time.time()
        interval = current_time - prev_time

        rx_throughput = (rx_bytes - prev_rx_bytes) / interval
        tx_throughput = (tx_bytes - prev_tx_bytes) / interval

        # Convert throughput to Mbps
        rx_throughput_mbps = (rx_throughput * 8) / 1_000_000
        tx_throughput_mbps = (tx_throughput * 8) / 1_000_000

        self.logger.info("Throughput on switch %016x, port %d: RX %.2f Mbps, TX %.2f Mbps",
                         dpid, port_no, rx_throughput_mbps, tx_throughput_mbps)

        return rx_throughput, tx_throughput

    def _handle_threshold_exceed(self, datapath, port_no, mac_address):
        self.logger.info("ALERT: High throughput detected on switch %016x port %d for MAC %s", datapath.id, port_no, mac_address)
        self.alarm[mac_address] = True
        self.unblock_time[mac_address] = time.time() + 180  # Allow unblock after 3 minute
        self.add_block_flow(datapath, port_no, mac_address)

    def _handle_threshold_below(self, datapath, port_no, mac_address):
        if mac_address in self.unblock_time:
            current_time = time.time()
            if current_time > self.unblock_time[mac_address]:
                self.logger.info("Throughput back under threshold for MAC %s, unblock time reached.", mac_address)
                self.unblock_mac(datapath, mac_address)
                del self.alarm[mac_address]
                del self.unblock_time[mac_address]

    def add_block_flow(self, datapath, port_no, mac_address):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Block traffic from the specific MAC address
        match = parser.OFPMatch(in_port=port_no, eth_src=mac_address)
        actions = []  # Empty actions list means drop
        priority = 100

        flow_mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                     match=match, instructions=[parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)])
        datapath.send_msg(flow_mod)

        # Save the blocked MAC for later unblock
        self.blocked_flows[mac_address] = match

        self.logger.info("Blocking traffic from MAC %s on port %d of switch %016x", mac_address, port_no, datapath.id)

    def unblock_mac(self, datapath, mac_address):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        if mac_address in self.blocked_flows:
            match = self.blocked_flows[mac_address]
            mod = parser.OFPFlowMod(datapath=datapath, command=ofproto.OFPFC_DELETE,
                                    out_port=ofproto.OFPP_ANY, out_group=ofproto.OFPG_ANY,
                                    match=match, priority=100)
            datapath.send_msg(mod)
            self.logger.info(f"Sbloccato il traffico dal MAC {mac_address} su switch {datapath.id}")
            del self.blocked_flows[mac_address]
        else:
            self.logger.warning(f"Nessuna regola di blocco trovata per il MAC {mac_address}")

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        body = ev.msg.body
        for stat in body:
            dpid = ev.msg.datapath.id
            port_no = stat.port_no
            rx_bytes = stat.rx_bytes
            tx_bytes = stat.tx_bytes

            # Ottieni l'indirizzo MAC associato alla porta
            mac_address = None
            if dpid in self.mac_to_port:
                # Cerca nella mappa MAC-to-port per trovare il MAC collegato alla porta
                for mac, port in self.mac_to_port[dpid].items():
                    if port == port_no:
                        mac_address = mac
                        break

            if not mac_address:
                self.logger.warning(f"MAC address non trovato per switch {dpid}, porta {port_no}")
                continue

            # Continuare con il calcolo del throughput solo se mac_address è valido
            if dpid not in self.prev_stats:
                self.prev_stats[dpid] = {}

            if port_no in self.prev_stats[dpid]:
                prev_stats = self.prev_stats[dpid][port_no]
                rx_throughput, tx_throughput = self._calculate_throughput(dpid, port_no, rx_bytes, tx_bytes, prev_stats)

                if rx_throughput > self.THROUGHPUT_THRESHOLD or tx_throughput > self.THROUGHPUT_THRESHOLD:
                    if not self.alarm.get(mac_address):
                        self._handle_threshold_exceed(ev.msg.datapath, port_no, mac_address)
                else:
                    if self.alarm.get(mac_address):
                        self._handle_threshold_below(ev.msg.datapath, port_no, mac_address)

            self.prev_stats[dpid][port_no] = (rx_bytes, tx_bytes, time.time())