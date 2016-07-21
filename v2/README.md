## Introduction
For a long time Amazon Web Services is one of the most often used platforms to deploy and run new projects.
For more complex project you usually start with mastering your network infrastructure, fortunately
amazon provides definitive guide on most often used network topologies. You can review some at
[http://docs.aws.amazon.com/AmazonVPC/latest/UserGuide/VPC_Scenarios.html](http://docs.aws.amazon.com/AmazonVPC/latest/UserGuide/VPC_Scenarios.html)


For some reason, in most of cases I've seen customer always configure setup manually, and than document steps with
screenshots in project wiki. Than, after some time, original knowledge gets lost and moving or deploying application
again leads to careful manual steps.

In this article I will demonstrate how I automate network creation with Ansible for the application according to project requirements,
and store network creation logic alongside the project. In this way, your project infrastructure evolves and releases
together with your application releases.

## Background

For the demo let's choose more complex setup, as described here
[VPC with Public and Private Subnets (NAT)](http://docs.aws.amazon.com/AmazonVPC/latest/UserGuide/VPC_Scenario2.html)

Let's take a look on definition, and network topology picture:

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/98-nat-gateway-diagram.png)

The configuration for this scenario includes a virtual private cloud (VPC) with a public subnet and a private subnet. We recommend this scenario if you want to run a public-facing web application, while maintaining back-end servers that aren't publicly accessible. A common example is a multi-tier website, with the web servers in a public subnet and the database servers in a private subnet. You can set up security and routing so that the web servers can communicate with the database servers.

The instances in the public subnet can receive inbound traffic directly from the Internet, whereas the instances in the private subnet can't. The instances in the public subnet can send outbound traffic directly to the Internet, whereas the instances in the private subnet can't. Instead, the instances in the private subnet can access the Internet by using a network address translation (NAT) gateway that resides in the public subnet. The database servers can connect to the Internet for software updates using the NAT gateway, but the Internet cannot initiate connections to the database servers.

Let's implement a bit more sophisticated example to described: make application highly available my placing app servers in multiple subnet.
Thus in public subnet we will have Elastic Load Balancer, that would be linked to several subnets we create.

In our scenario we will use both functions from Ansible AWS module, and direct awscli commands, where Ansible does not have support yet.

At the beginning, we would have no VPC on our account:

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/00-initial_state.png)

## Define VPC

### Presequities

As regions have difference in availablility zones sets, let's create two constants, to fix available AZ zones names for provisioning + provide some reasonable name for the environment.

<pre>

---
  vpc_availability_zone_t1: b
  vpc_availability_zone_t2: c

  readable_env_name: "app-{{env}}"  

</pre>

### Structure
Let's define VPC according to Scenario 2 picture. To be as close to Amazon example as possible, I would make 0.0 & 2.0 subnets public, and 1.0 and 3.0 private;
As you see in VPC configuration we already provide handy readable naming and tags. For two public networks, we specify default routing table.

<pre>
vpc_cidr_block: 10.0.0.0/16
vpc_subnets:
  - cidr: 10.0.0.0/24
    az: "{{aws_region}}{{vpc_availability_zone_t1}}"
    resource_tags: {"Name": "{{readable_env_name}}-sb-pub-{{aws_region}}-{{vpc_availability_zone_t1}}",  "Environment":"{{readable_env_name}}", "AZ" : "{{vpc_availability_zone_t1}}" }
  - cidr: 10.0.2.0/24
    az: "{{aws_region}}{{vpc_availability_zone_t2}}"
    resource_tags: { "Name": "{{readable_env_name}}-sb-pub-{{aws_region}}-{{vpc_availability_zone_t2}}", "Environment":"{{readable_env_name}}", "AZ" : "{{vpc_availability_zone_t2}}" }
  - cidr: 10.0.1.0/24
    az: "{{aws_region}}{{vpc_availability_zone_t1}}"
    resource_tags: {"Name": "{{readable_env_name}}-sb-priv-{{aws_region}}-{{vpc_availability_zone_t1}}",  "Environment":"{{readable_env_name}}", "AZ" : "{{vpc_availability_zone_t1}}" }
  - cidr: 10.0.3.0/24
    az: "{{aws_region}}{{vpc_availability_zone_t2}}"
    resource_tags: { "Name": "{{readable_env_name}}-sb-priv-{{aws_region}}-{{vpc_availability_zone_t2}}", "Environment":"{{readable_env_name}}", "AZ" : "{{vpc_availability_zone_t2}}" }

vpc_internet_gateway: "yes"
vpc_route_tables_public:
    - subnets:
       - 10.0.0.0/24
       - 10.0.2.0/24
      routes:
       - dest: 0.0.0.0/0
         gw: igw
</pre>

## Create VPC

To create VPC, we use already available Ansible module, ec2_vpc; On run we provide parameters to it using setup above.

<pre>

- name: NETWORK | Create the VPC
  ec2_vpc:
    state: present
    region: "{{ aws_region }}"
    resource_tags:
        Environment: "{{ readable_env_name }}"
        Name: "{{ readable_env_name }}-vpc-{{aws_region}}"
    cidr_block: "{{ vpc_cidr_block }}"
    subnets: "{{ vpc_subnets }}"
    dns_support: true
    dns_hostnames: true
    internet_gateway: "{{ vpc_internet_gateway|string }}"
    route_tables: "{{ vpc_route_tables_public }}"
    wait: yes
  register: vpc

</pre>

Upon this part execution we will have VPC created alongside with subnets:

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/02-vpc.png)

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/03-subnets.png)

Take a look on Nat gateways created - as you see, we have 1 Nat gateway per public subnet.

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/08-nat_gateways.png)

Take a look on route table created, as you see - public subnets have internet gateway set,

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/04-routetable_public.png)

while private subnet have route entry that forwards outgoing requests through NAT.

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/05-routetable-private.png)

## Nat instances magic.

Nowadays Amazon recommends to create Nat gatewates, rather then NAT instances.
To master NAT gateway, we need to

- allocate elastic IP
- create NAT gateway and associate NAT gateway with subnet
- wait for NAT gateway to be partially available, to create Route table for private subnet.
- create route table for private subnet & set NAT gateway for outgoing traffic

To allocate elastic IP we would use existing module from ansible:, ec2_eip.
Please note, that by default each account is limited to 5 elastic ips per region.

<pre>

  - name: NETWORK | allocate a new elastic IP without associating it to anything - 1
    ec2_eip: in_vpc=yes reuse_existing_ip_allowed=yes state=present region="{{aws_region}}"

</pre>

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/07-eip.png)

in order to create NAT gateway, in Ansible v1 we have to use awscli:

<pre>

  - name: NETWORK | Create NAT instance for subnet 1
    shell: "aws ec2 create-nat-gateway --region {{aws_region}} --subnet-id {{aws_vpc_pubsubnet1_runtime}} --allocation-id {{aws_vpc_privsubnet1_allocation}}"

</pre>

Here little hack: if you need immediately use Nat gateway, for example, to create custom routing table,-
give AWS time to partially initialize and register it:

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/99-misc-natinstances.png)

Now we can create custom route tables:

<pre>

  - name: NETWORK | Create new route table for the private subnet 1
    shell: "aws ec2 create-route-table --region {{aws_region}} --vpc-id {{aws_vpc_id_runtime}}"

  - name: NETWORK | Associate route table with private subnet 1
    shell: "aws ec2 associate-route-table --region {{aws_region}} --route-table-id {{routetable_private_1}} --subnet-id {{aws_vpc_privsubnet1_runtime}}"

  - name: NETWORK | Create NAT route record for  private subnet 1
    shell: "aws ec2 create-route --region {{aws_region}} --route-table-id {{routetable_private_1}} --destination-cidr-block '0.0.0.0/0' --nat-gateway-id {{nat_instance1}}"

</pre>

## Security groups

We can define requirements for security groups alongside with firewall rules.
Pay attention on examples below, how you can create rule both for CIDR block and for specific security group(s)

I want to have four security group.

First for load balancer, accepting http and https.

Second for jump box in public subnet, so I can ssh to that box, and ping, login, and troubleshoot my application instances.
Thus I need to open SSH and ICMP on app servers from that box.

Third - for Jump box itself, as I want to limit access to Jump box from my office IP only (assuming, gateway has public ip address 1.2.3.4)

Forth - for my database box, usually  RDS. Assuming, we use MySQL - I need to open 3306 port from APP servers.

<pre>
vpc_security_groups:
  - name: "{{readable_env_name}}-public-LOADBALANCER"
    desc: "security group for public access"
    rules:
      - proto: tcp
        from_port: 80
        to_port: 80
        cidr_ip: 0.0.0.0/0
      - proto: tcp
        from_port: 443
        to_port: 443
        cidr_ip: 0.0.0.0/0

  - name: "{{readable_env_name}}-public-JUMPBOX"
    desc: "security group that allows access from dedicated jump box in public network to internal resources"
    rules:
      - proto: tcp
        from_port: 22
        to_port: 22
        cidr_ip: "1.2.3.4/32" #Your office private ip

  - name: "{{readable_env_name}}-private-APP"
    desc: "Network for internal app servers"
    rules:
      - proto: tcp
        from_port: 22
        to_port: 22
        group_id: "{{readable_env_name}}-public-JUMPBOX"
      - proto: tcp
        from_port: 80
        to_port: 80
        group_id: "{{readable_env_name}}-public-LOADBALANCER"
      - proto: tcp
        from_port: 443
        to_port: 443
        group_id: "{{readable_env_name}}-public-LOADBALANCER"
      - proto: icmp
        from_port: -1 # icmp type, -1 = any type
        to_port:  -1 # icmp subtype, -1 = any subtype
        group_id: "{{readable_env_name}}-public-JUMPBOX"

  - name: "{{readable_env_name}}-private-DATABASE"
    desc: "resources that are private"
    rules:
      - proto: tcp
        from_port: 3306  # MYSQL
        to_port: 3306
        group_id: "{{readable_env_name}}-private-APP"

</pre>

Don't you find setup readable from definition?  I do.

Let's check setup created:

List of secutity groups created:

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/09-sg.png)

Public security group with inbound rules:

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/10-sg_public.png)

Private app servers group with inbound rules:

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/11_sg_app.png)

Database access security group with inbound rules:

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/12_sg_rds.png)

Jump box security group with inbound rules:

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/14_sg_jumpbox.png)


## Running the provisioning

Running ansible provisioning is as easy as executing shell file of the structure below:

As you see, we specify environment name (demo), desired region to create VPC in (us-east-1),
and set your secure AWS credentials as environment variables for provisioning.

<pre>

#!/bin/sh

# Static parameters
WORKSPACE=$PWD
BOX_PLAYBOOK=$WORKSPACE/bin/network_create.yml
BOX_NAME=awsnetwork

echo $BOX_NAME

prudentia local &lt;&lt;EOF
unregister $BOX_NAME
register
$BOX_PLAYBOOK
$BOX_NAME

verbose 4

set env demo
set aws_region us-east-1

envset AWS_ACCESS_KEY_ID THISISVERYSECUREKEYID
envset AWS_SECRET_ACCESS_KEY ANDTHISISTHISISVERYSECUREKEYACCESSKEY

provision $BOX_NAME

unregister $BOX_NAME
EOF

</pre>

Wondering how long it will take?  Less then 1 minute. Compare to manual setup ....

<pre>

PLAY RECAP ********************************************************************
127.0.0.1                  : ok=42   changed=12   unreachable=0    failed=0   

</pre>

At the end you will have all the information about network created, so you can store it,
or template to some configuration file:

![](https://raw.githubusercontent.com/Voronenko/ansible_vpc_ppsubnet_wnat/master/v1/images/01-provisioning.png)


## Points of Interest

I recommend to store and evolve deployment and provisioning recipes with your application code.
Believe me, when you know that you can put your environment up from scratch saying in 10-40 minutes,
your customer will be less nervous :)

If you would use that approach to implement different case of network setup, I would be grateful if you share your experience.
If you need to implement continuous integration on your project - you are welcome.

Mentioned samples for use with Ansible v1 (1.9.4) could be seen on or forked
from https://github.com/Voronenko/ansible_vpc_ppsubnet_wnat/tree/master/v1
