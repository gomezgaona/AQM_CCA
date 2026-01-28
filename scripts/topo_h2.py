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
    net = Mininet(topo=None, build=False, ipBase='172.17.0.0/16')

    host_sw = 32 # Hosts per switches
    if num_hosts > host_sw:
        num_sw = int(num_hosts / host_sw)
    else:
        num_sw = 2

    # Creating switches
    s_right = []
    print("Creating right switches")
    for i in range(0, num_sw):
        s_right.append(net.addSwitch(f's_right{i+1}', cls=OVSKernelSwitch, failMode='standalone'))
    
    # Aggregator switches 
    print("Creating aggregator switches")
    s_agg2 = net.addSwitch('s_agg2', cls=OVSKernelSwitch, failMode='standalone')

    # Connecting all the switches to the aggregator
    print("Linking right switches to the aggregator switch")
    for i in range(0, num_sw):
        net.addLink(s_right[i], s_agg2)
 
    # Creating hosts on the right
    print("Creating right hosts")
    for i in range(num_hosts):
        third_octet = (i // 254) % 256
        fourth_octet = (i % 254) + 1
        
        ip_address = f'172.17.{third_octet}.{fourth_octet}/16'
        hr = net.addHost(f'hr{i+1}', ip=ip_address)

        net.addLink(hr, s_right[int(i/host_sw)])
        hr.cmd('sysctl -w net.ipv4.tcp_wmem="{} {} {}"'.format(buffer_size, buffer_size, buffer_size))
        hr.cmd('sysctl -w net.ipv4.tcp_rmem="{} {} {}"'.format(buffer_size, buffer_size, buffer_size))

    print(f"{RED}Range of IP addresses of right hosts 172.17.0.1-172.17.{third_octet}.{fourth_octet} {RESET}")
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
        print("No arguments passed. Specify the number of hosts e.g., sudo python3 topo_h2.py 1024")
        exit()

    TCP_buffer_size = "4096 1000000 200000000"
    start_mininet_hosts(num_hosts, TCP_buffer_size)

if __name__ == "__main__":
    main()