"""
Author:  Richard Baldwin
Date:    /2024
E-mail:  eyeclept@pm.me
Description: 
    -
      
"""
# imports
import configparser
import ipaddress
import nmap
import socket
# constants

# classes

# functions
def function():
    """
    use-----> 
    input---> 
    output--> 
    details-> 
    
    """
    pass
def getConfigData(configFile):
    """
    use-----> 
    input---> configFile is the config file to be pulled from
    output--> it returns the config file
    details-> 
    
    """
    config = configparser.ConfigParser()
    return config.read(configFile)

def getIPsAndPorts(config):
    """
    use-----> gets IPs and ports
    input---> config to search (use get config data)
    output--> list of IPs and list of ports
    details-> 
    
    """
    return getIPs(config), getPorts(config)
    
def getIPs(config):
    """
    use-----> gets ips to scan
    input---> config to search (use get config data)
    output--> list of ips to scan
    details-> 
    
    """
    output = []
    try:
        ipRanges = config["NETWORKS"]["ip_range"].split(",")
    except:
        pass
        #TODO rais error if split fails. could be because config
    for ipRange in ipRanges:
        ipList = cidrToList(ipRange)
        output.extend(output+ipList)  
    return list(set(output))
def getPorts(config):
    """
    use-----> gets ports to scan
    input---> config to search (use get config data)
    output--> list of ports to scan
    details-> 
    
    """
    try:
        ports = config["NETWORKS"]["ports"].split(",")
    except:
        pass
        #TODO rais error if split fails
    for port in ports:
        try:
            int(port)
        except ValueError as e:
            raise ValueError(f"Config error: Invalid port: {port}. Must be an int")
        if not port <= 0 <= 65535:
            raise ValueError(f"Config error: Invalid port: {port}. Must be greater than or equal to 0 and less than or equal to 65535.")
    return ports


def checkConfig():
    """
    use-----> 
    input---> 
    output--> none on success, raises errors
    details-> 
    TODO: error handle config
    """
    pass

def cidrToList(ciderIP):
    """
    use-----> takes cidr ip and converts it into a list of ips
    input---> ip in cider notation
    output--> a list of ips within that range
    details-> 
    
    """
    output = []
    testIfIP = False
    try:
        network = ipaddress.ip_network(cidrIP)
    except ValueError as e:
        testIfIP = True
    if testIfIP:
        try:
            ip = ipaddress.ip_address(ciderIP)
        except ValueError as e:
            raise ValueError(f"Config error: Invalid CIDR notation: {ciderIP}. Must be in format x.x.x.x/y or x.x.x.x.")
        output.append(str(ip))
    else:
        for ip in network:
            output.append(str(ip))  
    return output

def portScan(ip, portRange = '1-1024'):
    """
    use-----> scans ip range
    input---> ip range is a string of the ip in cider notation, and the port range ("low-high")(optional). use nmap -p formatting
    output--> a bool of if it's up, and the scan result
    details-> 
    # Example usage:
    portScan("172.16.0.1", "1-10240")
    """
    nm = nmap.PortScanner()
    nm.scan(ip, portRange)
    return nm[ip].is_up(), nm

def reverseDnsLookup(ip):
    """
    use-----> 
    input---> 
    output--> 
    details-> 

        # Test the function
        print(reverseDnsLookup("8.8.8.8"))  # Output: dns.google
    
    """
    try:
        return socket.gethostbyaddr(ip)[0]
    except socket.herror:
        return None

