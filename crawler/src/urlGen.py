"""
Author:  Richard Baldwin
Date:    /2024
E-mail:  eyeclept@pm.me
Description: 
    -

    TODO
    may need a way to work with scrapy on non standard ports with a config file
      
"""
# imports
import nmap
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


