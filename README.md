# TCP-like Reliable Transport Protocol

A reliable streaming transport protocol built on top of UDP in Python. It replicates core TCP behaviors — including packet sequencing, ACK-based reliability, out-of-order delivery handling, loss recovery, and pipelining — over an unreliable network simulated by a lossy socket layer.

---

## Overview

UDP is fast but unreliable — packets can be lost, corrupted, or arrive out of order. This project implements a `Streamer` class that wraps UDP and provides reliable, ordered byte-stream delivery similar to TCP, without using TCP itself.

The protocol is tested against a `LossyUDP` socket that simulates real-world network conditions: configurable packet loss, bit corruption, and random delivery delays.

---

## Features

- **1472-byte packetization** — data is chunked to fit within UDP's max payload size
- **Sequence numbers** — every packet is tagged with a sequence number for ordering and deduplication
- **ACK-based reliability** — the receiver acknowledges packets; the sender retransmits on missed ACKs
- **MD5 hash-based corruption detection** — each packet includes a hash of its header + payload; corrupted packets are dropped and trigger a re-ACK requesting retransmission
- **Out-of-order delivery handling** — a min-heap buffer holds out-of-order packets and delivers them in sequence
- **Pipelining** — multiple packets can be in-flight simultaneously for higher throughput
- **FIN/FIN-ACK handshake** — graceful connection teardown, blocking until all outstanding packets are acknowledged before sending FIN
- **Threshold-based timeout** — a background thread periodically re-sends ACKs if expected packets haven't arrived, preventing stalls in lossy conditions

---

## Packet Format

Each packet is packed as a binary struct:

| Field | Type | Size | Description |
|---|---|---|---|
| `seq_num` | unsigned int | 4 bytes | Sender's sequence number |
| `ack_val` | unsigned int | 4 bytes | ACK number (next expected seq) |
| `ack_flag` | bool | 1 byte | True if this is an ACK packet |
| `fin_flag` | bool | 1 byte | True if this is a FIN (connection close) |
| `packet_hash` | bytes | 16 bytes | MD5 hash of header + payload |
| `payload` | bytes | variable | Application data |

---

## Project Structure

```
TCP-like-transport-protocol/
├── streamer.py       # Core Streamer class — send, recv, close logic
├── lossy_socket.py   # LossyUDP socket simulator (packet loss, corruption, delay)
└── test.py           # Two-host test harness for bidirectional data transfer
```

---

## How It Works

### Sending
1. Data is split into chunks of up to 1,448 bytes (1,472 byte UDP max minus header overhead)
2. Each chunk is packed into a struct with sequence number, flags, and an MD5 hash
3. Packets are sent and tracked in a "packets in flight" set/dict
4. A background listener thread receives ACKs and removes acknowledged packets from the in-flight buffer
5. On a missed ACK, the sender retransmits the unacknowledged packet

### Receiving
1. The background listener thread receives all incoming packets
2. Corrupted packets (hash mismatch) are discarded, triggering a re-ACK
3. In-order packets are delivered immediately; out-of-order packets are buffered in a min-heap
4. The receiver sends a cumulative ACK indicating the next expected sequence number

### Connection Teardown
1. Sender waits until all in-flight packets are acknowledged
2. Sends a FIN packet
3. Waits up to 3 seconds for a FIN-ACK
4. Waits an additional 2 seconds after receiving FIN-ACK before fully closing (similar to TCP's TIME_WAIT)

---

## Running the Tests

The test script simulates two hosts exchanging data bidirectionally over a lossy network (10% loss, 10% corruption, 100ms max delay).

Open two terminals:

**Terminal 1:**
```bash
python3 test.py 4444 5555 1
```

**Terminal 2:**
```bash
python3 test.py 4444 5555 2
```

Host 2 sends 200 small messages to Host 1, then Host 1 sends 200 large chunks back. Both sides verify correct in-order delivery.

### Adjusting Network Conditions

In `test.py`, modify the simulation parameters:

```python
lossy_socket.sim = lossy_socket.SimulationParams(
    loss_rate=0.1,           # 10% packet loss
    corruption_rate=0.1,     # 10% bit corruption
    max_delivery_delay=0.1,  # Up to 100ms random delay
    become_reliable_after=100000.0  # Never becomes reliable (set lower to test transition)
)
```

---

## Requirements

- Python 3.6+
- No external dependencies (uses only the standard library: `socket`, `struct`, `hashlib`, `heapq`, `threading`, `time`)

---

## Authors

- **Anthony Milas**
- **Claire Paré**
