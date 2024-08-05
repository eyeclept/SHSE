"""
Author: Richard Baldwin
Date:   2024
E-mail: eyeclept@pm.me

#
"""

# Imports
import pytest
import configparser
import ipaddress
import crawl.gen_urls as gen_urls

# Constants

# Classes


# Functions
def test_get_config_data():
    """
    Input: None
    Output: None
    Details:
        
    """
    #test good config
    result = gen_urls.get_config_data("test_config.ini")
    assert isinstance(result, configparser.ConfigParser)

def test_get_ips():
    """
    Input: None
    Output: None
    Details:
        
    """
    config =gen_urls.get_config_data("test_config.ini")
    result = gen_urls.get_ips(config)
    assert isinstance(result, list)
    assert "192.168.0.1" in result
    assert "172.16.0.1" in result
    assert "172.32.0.0" not in result
    with pytest.raises(ValueError):
        config = gen_urls.get_config_data("test_config_bad_option.ini")
        gen_urls.get_ips(config)
    pass

def test_get_ports():
    """
    Input: None
    Output: None
    Details:
        
    """
    config =gen_urls.get_config_data("test_config.ini")
    result = gen_urls.get_ports(config)
    assert "80" in result
    assert "443" in result
    assert "8080" not in result
    with pytest.raises(ValueError):
        config = gen_urls.get_config_data("test_config_bad_option.ini")
        gen_urls.get_ports(config)




def test_check_config():
    """
    Input: None
    Output: None
    Details:
        
    """
    pass



def test_cidr_to_list():
    """
    Input: None
    Output: None
    Details:
        
    """
    good_ip_list = ["172.16.0.0/12", "123.134.145.156", "10.0.0.0/8"]
    bad_ip_list = ["", "192.168.0.420", "172.26.0.0/42"]
    for check_ip in good_ip_list:
        output_list = gen_urls.cidr_to_list(check_ip)
        assert isinstance(output_list, list)
        assert len(output_list) > 0
    for check_ip in bad_ip_list:
        with pytest.raises(ValueError):
            gen_urls.cidr_to_list(check_ip)

def test_port_scan():
    """
    Input: None
    Output: None
    Details:
        
    """
    isup = gen_urls.port_scan("172.27.72.75")
    assert isup

    isup = gen_urls.port_scan("172.27.72.22")
    assert not isup

    isup = gen_urls.port_scan("172.27.72.22", [22])
    assert isup


def test_reverse_dns_lookup():
    """
    Input: None
    Output: None
    Details:
        
    """
    url = "ollama.epinisea.dmz"
    assert url == gen_urls.reverse_dns_lookup("172.27.72.75")
    assert not gen_urls.reverse_dns_lookup("172.27.72.128")