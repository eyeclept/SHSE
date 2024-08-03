"""
Author:  Richard Baldwin
Date:    /2024
E-mail:  eyeclept@pm.me
Description: 
    -
      
"""
# imports
from ..src.genUrls import *

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

def runTests():
    """
    use-----> 
    input---> 
    output--> 
    details-> 
    
    """
    getConfigDataTest()
    getIPsAndPortsTest()
    getIPsTest()
    getPortsTest()
    checkConfigTest()
    cidrToListTest()
    portScanTest()
    reverseDnsLookupTest()

def getConfigDataTest():
    """
    use-----> 
    input---> 
    output--> 
    details-> 
    
    """
    configFile = "config.ini"
    config = configparser.ConfigParser()
    result = config.read(configFile)
    assert result == [True]

def getIPsAndPortsTest():
    """
    use-----> 
    input---> 
    output--> 
    details-> 
    
    """
    config = {
        'ip_ranges': ['192.168.0.0', '172.16.0.0/12'],
        'ports': ['1-1024']
    }
    result = getIPsAndPorts(config)
    assert result == (['192.168.0.1/24', '10.0.0.1/16'], ['1-1024'])

def getIPsTest():
    """
    use-----> 
    input---> 
    output--> 
    details-> 
    
    """
    cidrNotation = "192.168.0.1/24"
    result = getIPs(cidrNotation)
    assert result == ['192.168.0.1', '192.168.0.2', '192.168.0.3']

def getPortsTest():
    """
    use-----> 
    input---> 
    output--> 
    details-> 
    
    """
    portRange = "1-1024"
    result = getPorts(portRange)
    assert result == [1, 2, 3]

def checkConfigTest():
    """
    use-----> 
    input---> 
    output--> 
    details-> 
    
    """
    configFile = "config.ini"
    config = configparser.ConfigParser()
    result = checkConfig(configFile)
    assert result is None

def cidrToListTest():
    """
    use-----> 
    input---> 
    output--> 
    details-> 
    
    """
    cidrNotation = "192.168.0.1/24"
    result = cidrToList(cidrNotation)
    assert result == ['192.168.0.1', '192.168.0.2', '192.168.0.3']

def portScanTest():
    """
    use-----> 
    input---> 
    output--> 
    details-> 
    
    """
    ipAddress = "192.168.0.1"
    portRange = "1-1024"
    result = portScan(ipAddress, portRange)
    assert result == (True, {'open_ports': [80]})

def reverseDnsLookupTest():
    """
    use-----> 
    input---> 
    output--> 
    details-> 
    
    """
    ipAddress = "8.8.8.8"
    result = reverseDnsLookup(ipAddress)
    assert result == 'dns.google'
