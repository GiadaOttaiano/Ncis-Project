from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib import hub
import time  # Importa la libreria time
 
class SimpleSwitch13(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
 
    def _init_(self, *args, **kwargs):
        super(SimpleSwitch13, self)._init_(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}  # Aggiunto per memorizzare i datapath
        self.monitor_thread = hub.spawn(self._monitor)  # Avvia il thread di monitoraggio
        self.prev_stats = {}  # Dizionario per memorizzare le statistiche precedenti
        self.THROUGHPUT_THRESHOLD = 224000  # Soglia di throughput in Byte/s
        self.alarm = False  # Variabile di allarme
 
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
 
        # install table-miss flow entry
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        self.datapaths[datapath.id] = datapath  # Memorizza il datapath per il monitoraggio
 
    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
 
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)
 
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        # Se si raggiunge questo punto, potresti voler aumentare
        # la lunghezza di miss_send_length del tuo switch
        if ev.msg.msg_len < ev.msg.total_len:
            self.logger.debug("packet truncated: only %s of %s bytes",
                              ev.msg.msg_len, ev.msg.total_len)
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']
 
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
 
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            # ignora i pacchetti LLDP
            return
        dst = eth.dst
        src = eth.src
 
        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})
 
        self.logger.info("packet in %s %s %s %s", dpid, src, dst, in_port)
 
        # Impara un indirizzo MAC per evitare FLOOD la prossima volta.
        self.mac_to_port[dpid][src] = in_port
 
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD
 
        actions = [parser.OFPActionOutput(out_port)]
 
        # installa un flusso per evitare il packet_in la prossima volta
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            # verifica se abbiamo un buffer_id valido, se s\u00ec, evita di inviare sia flow_mod che packet_out
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
                return
            else:
                self.add_flow(datapath, 1, match, actions)
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
 
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
 
    def _monitor(self):
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            hub.sleep(10)  # Monitoraggio ogni 10 secondi
 
    def _request_stats(self, datapath):
        self.logger.debug('send stats request: %016x', datapath.id)
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
 
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)
 
    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        body = ev.msg.body
        dpid = ev.msg.datapath.id
 
        for stat in sorted(body, key=lambda x: x.port_no):
            port_no = stat.port_no
            rx_bytes = stat.rx_bytes
            tx_bytes = stat.tx_bytes
 
            if (dpid, port_no) in self.prev_stats:
                prev_rx_bytes, prev_tx_bytes, prev_time = self.prev_stats[(dpid, port_no)]
                curr_time = time.time()
 
                interval = curr_time - prev_time
                rx_throughput = (rx_bytes - prev_rx_bytes) / interval
                tx_throughput = (tx_bytes - prev_tx_bytes) / interval
 
                # Converti il throughput in Mbps
                rx_throughput_mbps = (rx_throughput * 8) / 1_000_000
                tx_throughput_mbps = (tx_throughput * 8) / 1_000_000
 
                # Stampa le statistiche di throughput in Mbps
                self.logger.info("Throughput switch %016x, porta %d: RX %.2f Mbps, TX %.2f Mbps",
                                 dpid, port_no, rx_throughput_mbps, tx_throughput_mbps)
 
                # Se supera la soglia, attiva l'allarme (in B/s)
                if rx_throughput > self.THROUGHPUT_THRESHOLD or tx_throughput > self.THROUGHPUT_THRESHOLD:
                    if not self.alarm:  # Attiva l'allarme solo se non \u00e8 gi\u00e0 attivo
                        self.alarm = True
                        self.logger.info("ALLERTA: Alto throughput rilevato su switch %016x porta %d", dpid, port_no)
                else:
                    if self.alarm:  # Disattiva l'allarme se il throughput rientra nei limiti
                        self.alarm = False
                        self.logger.info("Throughput sotto la soglia per switch %016x porta %d, allarme disattivato.", dpid, port_no)
 
            # Aggiorna le statistiche precedenti
            self.prev_stats[(dpid, port_no)] = (rx_bytes, tx_bytes, time.time())