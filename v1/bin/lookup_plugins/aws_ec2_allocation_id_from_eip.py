"""
Description: This lookup takes an AWS region and an elastic ip address
and returns the allocation id.
Example Usage:
{{ lookup('aws_ec2_allocation_id_from_eip', ('eu-west-1', '54.54.54.54') }}
"""
from ansible import errors
try:
    import boto.ec2
except ImportError:
    raise AnsibleError("aws_ec2_allocation_id_from_eip lookup cannot be run without boto installed")

class LookupModule(object):
    def __init__(self, basedir=None, **kwargs):
        self.basedir = basedir

    def run(self, terms, variables=None, **kwargs):
        if isinstance(terms, basestring):
            terms = [terms]
        region = terms[0]
        public_ip = terms[1]
        conn = boto.ec2.connect_to_region(region)
        addresses = conn.get_all_addresses(addresses=[public_ip])
        if addresses and addresses[0].allocation_id:
            return [addresses[0].allocation_id.encode('utf-8')]
        return None
