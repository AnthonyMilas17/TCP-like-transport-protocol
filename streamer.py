# do not import anything else from loss_socket besides LossyUDP
from lossy_socket import LossyUDP
# do not import anything else from socket except INADDR_ANY
from socket import INADDR_ANY

import struct
import heapq
import time
import hashlib

import threading

from concurrent.futures import ThreadPoolExecutor

class Streamer:
    def __init__(self, dst_ip, dst_port,
                 src_ip=INADDR_ANY, src_port=0):
        """Default values listen on all network interfaces, chooses a random source port,
           and does not introduce any simulated packet loss."""
        self.socket = LossyUDP()
        self.socket.bind((src_ip, src_port))
        self.dst_ip = dst_ip
        self.dst_port = dst_port
        self.seq_num = 0
        self.expected_seq_num = 0
        self.smallest_seq_in_flight = 0
        self.bytes_heap = []
        self.closed = False
        self.pif_set = set() #packets in flight buffer (only stores seq nums)
        self.pif_dict = {} # (data corresponding to seq nums)
        self.pif_acked = False
        self.lock = threading.Lock()
        self.expected_seq_threshold = time.time() + 0.3
        
        self.packets_in_buffer = set()
        
        self.default_md5_hash = hashlib.md5(b"").digest()
        
        self.constant_timeout = 1
        # self.timeout = self.constant_timeout
        
        executor = ThreadPoolExecutor(max_workers=2)
        executor.submit(self.listener)
        executor.submit(self.threshold_timeout)
        self.listening = False
        self.got_first_packet = False
        self.sending = False

    def send_packet(self, ack_val, ack_flag, fin_flag, curr_packet_payload, seq_num=None):
        
        #not a retransmitted seq num
        #when we send an ack, we set the ack seq.to self.seq_num
        if seq_num is None:
            seq_num = self.seq_num
            
        #print(f"curr_packet_payload is {curr_packet_payload}")
        #pack the packet
        #packet = (self.seq_num, curr_packet_payload)
        # Compute the hash using the payload and all header components except packet_hash itself
        header_without_hash = struct.pack(f'II??{len(curr_packet_payload)}B', seq_num, ack_val, ack_flag, fin_flag, *curr_packet_payload)
        packet_hash = hashlib.md5(header_without_hash).digest()
        
        # Pack the packet including the computed hash
        packet = struct.pack(f'II??16s{len(curr_packet_payload)}B', seq_num, ack_val, ack_flag, fin_flag, packet_hash, *curr_packet_payload)
        
        # Send the packet
        self.socket.sendto(bytes(packet), (self.dst_ip, self.dst_port))
        
        #increase the sequence number
        if not ack_flag and seq_num == self.seq_num:
            seq_num2, ack_val2, ack_flag2, fin_flag2, packet_hash2, payload2 = struct.unpack(f'II??16s{len(curr_packet_payload)}s', packet)
            #print("\n\n\n\n\n\n#######################  SENDING SIDE  ##############################")
            #print(f"SENDING {(seq_num, ack_val, ack_flag, fin_flag, packet_hash2, payload2)} (NOT ACK). Seq num was {self.seq_num}, now incrementing to {self.seq_num + 1}")
            #print("######################################################################")
            self.seq_num += 1
        

    def send(self, data_bytes: bytes) -> None:
        self.sending = True
        """Note that data_bytes can be larger than one packet."""
        # Your code goes here!  The code below should be changed!
        packet_size = 1472
        header_size = struct.calcsize('II??16s')
        payload_size = packet_size - header_size
        #print(f"length: {len(data_bytes)}")
        #print(f"data bytes: {data_bytes}")
        
        num_packets = len(data_bytes) // payload_size
        remainder = len(data_bytes) % payload_size
        if remainder > 0:
            num_packets += 1
            
        
        

        #####################################################################################
        # Here we are building the packet that we want to send from the total bytes, partitioning the packets by packet size 
        
        #initialize an empty array for the current packet
        local_seq_num = self.seq_num
        
        curr_packet_payload = []
        #loop through all the bytes
        for i in range(len(data_bytes)):
            
            ##add the current byte to the packet
            curr_packet_payload.append(data_bytes[i])
            
            # Once a packet has attained its maximum byte size, we send it and reset current packet
            if i % payload_size + 1 == payload_size:
                
                #send the current packet of length payload_size
                #header field is just the sequence number for now
                #packet_hash = hashlib.md5(bytes(curr_packet_payload)).digest()
                with self.lock:
                    pif_array = [curr_packet_payload,0,False,False,self.seq_num]
                    self.pif_set.add(self.seq_num)
                    self.pif_dict[self.seq_num] = pif_array

                self.send_packet(0, False, False, curr_packet_payload)
                
                
                
                local_seq_num += 1
                curr_packet_payload = []
                    
        
        if remainder > 0:
            #packet_hash = hashlib.md5(bytes(curr_packet_payload)).digest()
            
            with self.lock:
                pif_array = [curr_packet_payload,0,False,False,self.seq_num]
                self.pif_set.add(self.seq_num)
                self.pif_dict[self.seq_num] = pif_array
            self.send_packet(0, False, False, curr_packet_payload)
           
        
        #####################################################################################
        # for now I'm just sending the raw application-level data in one UDP payload
        









    def recv(self) -> bytes:
        """Blocks (waits) if no data is ready to be read from the connection."""
        # your code goes here!  The code below should be changed!
        self.listening = True
        
        # this sample code just calls the recvfrom method on the LossySocket
        #data, addr = self.socket.recvfrom()
    
        payload = b""
            

        while self.bytes_heap and self.bytes_heap[0][0] == self.expected_seq_num:
            #print(f'\nbuffer {self.bytes_heap}')
            with self.lock:
                #print(f"set {self.packets_in_buffer}")
                self.packets_in_buffer.remove(self.expected_seq_num)
                payload += b"" + heapq.heappop(self.bytes_heap)[5]
                self.expected_seq_num += 1
        

        return payload
    

    def threshold_timeout(self):
        while not self.closed:
            try:
                with self.lock:
                    if self.expected_seq_threshold < time.time() and self.listening and self.got_first_packet and not self.sending:
                        #print(f"SENDING ACK {self.expected_seq_num} for most recent packet of {self.expected_seq_num - 1}, because {self.expected_seq_num} was never received because it was never received")
                        self.expected_seq_threshold = time.time() + 0.15
                        self.send_packet(self.expected_seq_num, True, False, b"")
            except Exception as e:
                print("threshhold_timout died!")
                print(e)
            time.sleep(0.05)


    
    def listener(self):
        while not self.closed:
            try:
                #RECEIVER SIDE
                data, addr = self.socket.recvfrom()
                self.got_first_packet = True
                header_size = struct.calcsize('II??16s')
                payload_size = len(data) - header_size
                
                if data == b'':
                    continue

                #print(f"\n\n\nTRYING TO UNPACK {data} \n\n\n")

                
                seq_num, ack_val, ack_flag, fin_flag, packet_hash, payload = struct.unpack(f'II??16s{payload_size}s', data)
                

                #print("\n\n\nUNPACKED\n\n\n")


                payload_list = list(payload)
                
                header_without_hash = struct.pack(f'II??{len(payload_list)}B', seq_num, ack_val, ack_flag, fin_flag, *payload_list)
                recv_packet_hash = hashlib.md5(header_without_hash).digest()

                # Check if the computed hash matches the received hash
                if recv_packet_hash != packet_hash:
                    self.send_packet(self.expected_seq_num, True, False, b"")
                    continue

                if seq_num == self.expected_seq_num:
                    self.expected_seq_threshold = time.time() + 0.2
                    

                # if ack_flag:
                #     if(ack_val <= self.smallest_seq_in_flight):
                #         print(f"ACK FLAG TRUE {ack_val} FOR {ack_val - 1}. (DUPLICATE ACK, corresponding seq was already removed from pif_set)")
                #     else:
                #         print(f"ACK FLAG TRUE {ack_val} FOR {ack_val - 1}")
                
                #first, if the received packet is not an acknowledgement, then we accept out of order packets, and don't accept duplicate packets
                if not ack_flag and ((seq_num >= self.expected_seq_num and seq_num not in self.packets_in_buffer) or fin_flag):
                    with self.lock:

                        self.packets_in_buffer.add(seq_num)
                        heapq.heappush(self.bytes_heap, (seq_num, ack_val, ack_flag, fin_flag, packet_hash, payload))
                        #self.send_packet(seq_num + 1, True, False, b"")
                    if fin_flag:
                        #print(f'\nSENDING FIN ACK {seq_num + 1} FOR RECIEVED FIN {seq_num}')
                        #print("RECEIVED FIN, clearing all pifs")
                        self.pif_set.clear()
                        self.pif_dict.clear()
                        self.send_packet(seq_num + 1, True, False, b"")
                    #else:
                        #print(f'\nSENDING ACK {seq_num + 1} FOR RECIEVED PACKET {seq_num}')
                    # print("######################################################################"

                elif not ack_flag and seq_num > self.expected_seq_num:
                    #print(f"OUT OF ORDER. GOT {seq_num} AND EXPECTED CORRECT SEQ: {self.expected_seq_num}\n\rSENDING ACK {self.expected_seq_num} to request retransmission")
                    self.send_packet(self.expected_seq_num, True, False, b"")

                #SENDER SIDE
                elif ack_flag: #acks less or equal than smallest seq in flight are duplicate acks bc those seqs have already been acked, and removed from pif
                    
                    with self.lock:
                      
                        
                        if ack_val > self.smallest_seq_in_flight:
                            if ack_val > 0 and self.smallest_seq_in_flight >= 0 : #there's nothing to remove if <= 0
                                #print(f"REMOVING PACKETS {self.smallest_seq_in_flight} through {ack_val - 1} (INCLUSIVE)")
                                for i in range(self.smallest_seq_in_flight, ack_val):
                                    if i in self.pif_dict:
                                        #print(f"IN LOOP: removing seq {i}")
                                        self.pif_set.remove(i)
                                        self.pif_dict.pop(i)
                                    # else:
                                    #     print(f"passed removing on seq {i}")
                            # else:
                            #     print(f"PASSING on REMOVING SEQ {ack_val - 1}, also smallest seq in flight is {self.smallest_seq_in_flight}\n")
                        if self.pif_dict:

                            #print(f"RESENDING PACKETS IN RANGE {(ack_val, self.seq_num)}")
                            #print(f"IN LOOP: retransmitting seq {ack_val}")
                            recv_payload, recv_ack_val, recv_ack_flag, recv_fin_flag, recv_seq_num = self.pif_dict[ack_val]
                            self.send_packet(recv_ack_val, recv_ack_flag, recv_fin_flag, recv_payload, recv_seq_num)
                            
                        
                        if ack_val > self.smallest_seq_in_flight:
                            #print(f"len of pif_set is now: {len(self.pif_set)}")
                            self.smallest_seq_in_flight = ack_val
                        

                

            except Exception as e:
                print("listener died!")
                print(e)




    def close(self) -> None:
        print("\n\nCLOSING\n\n")
        if self.sending:
            self.sending = False
        # if self.listening:
        #    self.listening = False

        """Cleans up. It should block (wait) until the Streamer is done with all
           the necessary ACKs and retransmissions"""
        # your code goes here, especially after you add ACKs and retransmissions.
        #add wait in part 5

        print("\n\n\nCLOSE CALLED, WAITING FOR ALL ACKS\n\n\n")

        #Stalling until all sent packet have been acked
        while self.pif_set:
            time.sleep(0.01)
            #print(f"PIF SET: {self.pif_set}")

        print("\n\n\nALL ACKS RECEIVED, SENDING FIN\n\n\n")
        #send FIN
        
        #pif_array = [b'', 0, False, True, self.seq_num, time.time() + self.constant_timeout]
                
        with self.lock:
            pif_array = [b'',self.expected_seq_num,False,True,self.seq_num]
            self.pif_set.add(self.seq_num)
            self.pif_dict[self.seq_num] = pif_array
            self.send_packet(self.expected_seq_num, False, True, b'')
        
        close_threshold = time.time() + 3
        #wait for ACK of FIN

        while close_threshold > time.time() and self.pif_set:
            time.sleep(0.01)
            
        if not self.pif_set:
            print("\n\n\nFIN ACK RECEIVED, WAITING 2+ SECONDS\n\n\n")
            time.sleep(2)
        else:
            print("\n\n\nCLOSED CONNECTION BEFORE FIN ACK RECEIVED\n\n\n")
        

        print("\n\n\nSTOPPING SOCKET RECEIVE AND CLOSING\n\n\n")
        self.closed = True
        self.socket.stoprecv()
        
        return
