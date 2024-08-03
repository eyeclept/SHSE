"""
Author: Richard Baldwin
Date:   2024
E-mail: eyeclept@pm.me
"""

# Imports
from ..src.genUrls import *
import configparser

# Constants
CONFIG_FILE = 'config.ini'

# Classes


# Functions
def function():
    """
    use: 
        This is a utility function that does nothing.

    input: 
        None

    output: 
        None

    details: 
        No details are available.
    """
    pass


def run_tests():
    """
    use:
        Run the various tests in this module.

    input: 
        None

    output: 
        None

    details: 
        See individual test functions for details.
    """
    get_config_data_test()
    get_ips_and_ports_test()
    get_ips_test()
    get_ports_test()
    check_config_test()
    cidr_to_list_test()
    port_scan_test()
    reverse_dns_lookup_test()


def get_config_data_test():
    """
    use:
        Get the configuration data from a file.

    input: 
        None

    output: 
        A boolean indicating whether the data was loaded successfully.

    details: 
        See the configparser module for details.
    """
    config_file = CONFIG_FILE
    config = configparser.ConfigParser()
    result = config.read(config_file)
    assert result == [True]


def get_ips_and_ports_test():
    """
    use:
        Get a list of IP addresses and ports from a configuration.

    input: 
        A dictionary with 'ip_ranges' and 'ports' keys.

    output: 
        A tuple containing the list of IP addresses and the list of ports.

    details: 
        See the get_ips_and_ports function for details.
    """
    config = {
        'ip_ranges': ['192.168.0.0', '172.16.0.0/12'],
        'ports': ['1-1024']
    }
    result = get_ips_and_ports(config)
    assert result == (['192.168.0.1/24', '10.0.0.1/16'], ['1-1024'])


def get_ips_test():
    """
    use:
        Get a list of IP addresses from a CIDR notation.

    input: 
        A string representing the CIDR notation.

    output: 
        A list of IP addresses.

    details: 
        See the get_ips function for details.
    """
    cidr_notation = "192.168.0.1/24"
    result = get_ips(cidr_notation)
    assert result == ['192.168.0.1', '192.168.0.2', '192.168.0.3']


def get_ports_test():
    """
    use:
        Get a list of ports from a port range.

    input: 
        A string representing the port range.

    output: 
        A list of ports.

    details: 
        See the get_ports function for details.
    """
    port_range = "1-1024"
    result = get_ports(port_range)
    assert result == [1, 2, 3]


def check_config_test():
    """
    use:
        Check if a configuration is valid.

    input: 
        A string representing the configuration file.

    output: 
        None

    details: 
        See the check_config function for details.
    """
    config_file = CONFIG_FILE
    config = configparser.ConfigParser()
    result = check_config(config_file)
    assert result is None


def cidr_to_list_test():
    """
    use:
        Convert a CIDR notation to a list of IP addresses.

    input: 
        A string representing the CIDR notation.

    output: 
        A list of IP addresses.

    details: 
        See the cidr_to_list function for details.
    """
    cidr_notation = "192.168.0.1/24"
    result = cidr_to_list(cidr_notation)
    assert result == ['192.168.0.1', '192.168.0.2', '192.168.0.3']


def port_scan_test():
    """
    use:
        Scan a port range on an IP address.

    input: 
        An IP address and a port range.

    output: 
        A tuple containing a boolean indicating whether the scan was successful and a dictionary with open ports.

    details: 
        See the port_scan function for details.
    """
    ip_address = "192.168.0.1"
    port_range = "1-1024"
    result = port_scan(ip_address, port_range)
    assert result == (True, {'open_ports': [80]})


def reverse_dns_lookup_test():
    """
    use:
        Perform a reverse DNS lookup on an IP address.

    input: 
        An IP address.

    output: 
        A string representing the domain name.

    details: 
        See the reverse_dns_lookup function for details.
    """
    ip_address = "8.8.8.8"
    result = reverse_dns_lookup(ip_address)
    assert result == 'dns.google'