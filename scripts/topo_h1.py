#!/usr/bin/python

import os
import subprocess
import sys
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch
from mininet.cli import CLI

def start_mininet_hosts(num_hosts, buffer_size):
    RED = "\033[31m"
    RESET = "\033[0m"
    net = Mininet(topo=None, build=False, ipBase='172.16.0.0/16')

    host_sw = 32 # Hosts per switches
    if num_hosts > host_sw:
        num_sw = int(num_hosts / host_sw)
    else:
        num_sw = 2

    # Creating switches
    s_left = []
    print("Creating left switches")
    for i in range(0, num_sw):
        s_left.append(net.addSwitch(f's_left{i+1}', cls=OVSKernelSwitch, failMode='standalone'))
    
    # Aggregator switches 
    print("Creating aggregator switches")
    s_agg1 = net.addSwitch('s_agg1', cls=OVSKernelSwitch, failMode='standalone')
    
    # Connecting all the switches to the aggregator
    print("Linking left switches to the aggregator switch")
    for i in range(0, num_sw):
        net.addLink(s_left[i], s_agg1)
 
    # Creating hosts on the left
    print("Creating left hosts")
    for i in range(num_hosts):
        third_octet = (i // 254) % 256
        fourth_octet = (i % 254) + 1

        ip_address = f'172.16.{third_octet}.{fourth_octet}/16'
        hs = net.addHost(f'hs{i+1}', ip=ip_address)

        net.addLink(hs, s_left[int(i/host_sw)])
        hs.cmd('sysctl -w net.ipv4.tcp_wmem="{} {} {}"'.format(buffer_size, buffer_size, buffer_size))
        hs.cmd('sysctl -w net.ipv4.tcp_rmem="{} {} {}"'.format(buffer_size, buffer_size, buffer_size))

    print(f"{RED}Range of IP addresses of left hosts 172.16.0.1-172.16.{third_octet}.{fourth_octet} {RESET}")
    print(f"Setting TCP send and receive buffers to {buffer_size} Mbytes")
    
    # Start the network
    net.start()
    print("Starting the network")
    
    # Open the Mininet CLI
    net.interact()
    
    # Clean up after the network has been stopped
    net.stop()
    

def main():
    if len(sys.argv) > 1:
        num_hosts = int(sys.argv[1])
        if num_hosts > 1024:
            print("The maximum number of hosts allowed is 1024")
            exit()
    else:
        print("No arguments passed. Specify the number of hosts e.g., sudo python3 topo_h1.py 1024")
        exit()

    TCP_buffer_size = "4096 1000000 200000000"
    start_mininet_hosts(num_hosts, TCP_buffer_size)

if __name__ == "__main__":
    main()