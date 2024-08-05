"""
Author: Richard Baldwin
Date:   2024
E-mail: eyeclept@pm.me
Description:
    A script for scanning and checking network hosts using IP addresses and ports.

    TODO add checks to config things to ensure proper config file
    TODO ensure ip addresses are ipv4
"""

# imports
import configparser
import ipaddress
import socket

# constants are not used in this code, so I removed them

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


def get_config_data(config_file: str) -> configparser.ConfigParser:
    """
    use-----> Get configuration data from a file.
    input---> configFile is the config file to be pulled from
    output--> It returns the ConfigParser object.
    details->
    
    """
    config = configparser.ConfigParser()
    config.read(config_file)
    return config



def get_ips(config: configparser.ConfigParser) -> list:
    """
    use-----> Get a list of IP addresses from a configuration file.
    input---> config is the ConfigParser object to search
    output--> A list of IP addresses
    details-> 
    
    """
    ip_ranges = []
    try:
        ip_ranges = config["NETWORKS"]["ip_range"].split(",")
    except (configparser.NoSectionError, configparser.NoOptionError):
        raise ValueError("Config error: failed to split config on ','")

    output = []
    for ip_range in ip_ranges:
        ip_list = cidr_to_list(ip_range)
        output.extend(ip_list)

    return list(set(output))


def get_ports(config: configparser.ConfigParser) -> list:
    """
    use-----> Get a list of port ranges from a configuration file.
    input---> config is the ConfigParser object to search
    output--> A list of port ranges
    details-> 
    
    """
    try:
        ports = config["NETWORKS"]["ports"].split(",")
    except (configparser.NoSectionError, configparser.NoOptionError):
        raise ValueError("Config error: failed to split config on ','")

    output = []
    for port in ports:
        try:
            int(port)
            output.append(port)
        except ValueError as e:
            raise ValueError(f"Config error: Invalid port: {port}. Must be an integer")
        if not 0 <= int(port) <= 65535:
            raise ValueError(f"Config error: Invalid port: {port}. Must be within range 0-65535")

    return list(set(output))


def check_config(config: configparser.ConfigParser) -> None:
    """
    use-----> Check the configuration file for errors.
    input---> config is the ConfigParser object to check
    output--> None on success, raises errors
    details-> 
    
    """
    pass  # implement error checking here


def cidr_to_list(cidr_ip: str) -> list:
    """
    use-----> Convert a CIDR notation string into a list of IP addresses.
    input---> cidr_ip is the CIDR notation string to convert
    output--> A list of IP addresses
    details-> 
    
    """
    try:
        network = ipaddress.ip_network(cidr_ip)
    except ValueError as e:
        raise ValueError(f"Invalid CIDR notation: {cidr_ip}. Must be in format x.x.x.x/y or x.x.x.x")

    output = []
    for ip in network:
        output.append(str(ip))

    return output


def port_scan(ip: str, port_range: list = [80]) -> bool:
    """
    use-----> Perform a port scan on an IP address.
    input---> ip is the IP address to scan, port_range is the port range to scan (optional)
    output--> A tuple containing a boolean indicating if the host is up and the scan result
    details-> 
        TODO need to make it work with multiple ports and output results in a tuple
    """
    for port in port_range:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex((ip, port))
        if result == 0:
            return True
    return False



def reverse_dns_lookup(ip: str) -> str:
    """
    use-----> Perform a reverse DNS lookup on an IP address.
    input---> ip is the IP address to look up
    output--> The hostname associated with the IP address (or None if not found)
    details-> 
    
    """
    try:
        return socket.gethostbyaddr(ip)[0]
    except socket.herror:
        return ""