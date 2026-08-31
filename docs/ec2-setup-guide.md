# AWS EC2 Setup Guide

This is the reusable setup for an EC2 Ubuntu instance, covering both a **private EICE-based setup** and a **direct Elastic-IP setup**.

The example values from the working setup are:

```text
Region:           eu-north-1
Instance name:    Tradeloop-VPS
Instance ID:      i-023c5944ea7f33c74
Private IP:       172.31.39.213
Elastic IP:       13.53.253.22

VPC:
vpc-04e776e5b4bcf40a1

Instance Security Group:
sg-09d7979fe75976837
launch-wizard-1

EICE name:
tradeloop-connect

EICE ID:
eice-0e104884fea225e22
```

For a future instance, replace these values with the new instance's IDs and addresses.

---

# 1. Architecture Choices

There are two main ways to SSH into the EC2 instance.

## Option A — Private EC2 + EICE

```text
Your Mac
   │
   │ AWS authentication
   ▼
EC2 Instance Connect Endpoint
   │
   │ Private VPC network
   ▼
EC2 Private IP
172.31.x.x
```

The instance does not require a public IP.

This is useful when you want the EC2 instance to remain private.

## Option B — Elastic IP

```text
Your Mac
   │
   │ Internet / SSH
   ▼
Elastic IP
13.53.253.22
   │
   ▼
EC2 Network Interface
   │
   ▼
Private IP
172.31.39.213
```

This is simpler for regular SSH and VS Code Remote SSH.

For a personal development VPS, this is usually the more convenient setup provided SSH access is restricted to your IP.

---

# 2. Create the EC2 Instance

In AWS:

```text
EC2
→ Instances
→ Launch instances
```

Choose Ubuntu and the required instance type.

Create or select a key pair.

For example:

```text
tradeloop.pem
```

Download this `.pem` file.

AWS only gives you the private key once, so keep it somewhere safe.

---

# 3. Store the PEM Key Correctly

A good location on macOS is:

```bash
mkdir -p ~/.ssh
mv ~/Downloads/tradeloop.pem ~/.ssh/
```

Then secure it:

```bash
chmod 400 ~/.ssh/tradeloop.pem
```

## What `chmod 400` means

The three digits represent:

```text
Owner | Group | Others
  4   |   0   |   0
```

`4` means read-only.

Therefore:

```text
Owner  → read
Group  → no access
Others → no access
```

Your private key becomes readable only by your user.

SSH generally rejects private keys that are accessible to other users.

Check permissions with:

```bash
ls -l ~/.ssh/tradeloop.pem
```

Expected approximately:

```text
-r-------- ... tradeloop.pem
```

## Non-standard PEM locations

The PEM file does not have to live in `~/.ssh/`.

In this setup the key was stored on an external drive:

```text
/Volumes/D-DRIVE/TB/p2.pem
```

SSH accepts any path in `IdentityFile`.
The `chmod 400` requirement still applies regardless of location.

If the external drive is not mounted when you try to SSH, the connection will fail with a key-not-found error.
Verify the drive is mounted before connecting.

---

# 4. Find the EC2 Username

For standard Ubuntu AWS images, use:

```text
ubuntu
```

Therefore SSH follows:

```bash
ssh -i KEY ubuntu@HOST
```

For example:

```bash
ssh -i ~/.ssh/tradeloop.pem ubuntu@13.53.253.22
```

---

# 5. Private EC2 Using EICE

If the instance has no public IP, you can use **EC2 Instance Connect Endpoint**.

Create one from:

```text
EC2
→ Network & Security
→ EC2 Instance Connect Endpoints
→ Create endpoint
```

The EICE and EC2 instance must be able to communicate through the VPC.

The working setup used:

```text
EICE:
tradeloop-connect
eice-0e104884fea225e22
```

The instance and endpoint were in the same VPC networking environment.

---

# 6. EICE Security Group Rules

The instance Security Group must allow SSH traffic originating from the EICE Security Group.

Go to:

```text
EC2
→ Security Groups
→ Instance Security Group
→ Inbound rules
```

Add:

```text
Type:      SSH
Protocol:  TCP
Port:      22
Source:    EICE Security Group
```

If the EC2 instance and EICE use the same Security Group, this is a **self-referencing Security Group rule**:

```text
SSH
TCP
22
sg-xxxxxxxxxxxxxxxxx  ← the same SG ID
```

In the working setup:

```text
sg-09d7979fe75976837
```

was used for both.

A separate SSH rule can also allow your home/public IP:

```text
SSH
TCP
22
YOUR_PUBLIC_IP/32
```

For example:

```text
78.101.31.166/32
```

Avoid:

```text
0.0.0.0/0
```

for SSH unless absolutely necessary.

## Outbound rule required for EICE

This is a common point of confusion.

When the EICE endpoint and the EC2 instance share the same Security Group, the Security Group is attached to two ENIs:

```text
EICE endpoint ENI     ← has launch-wizard-1 SG
EC2 instance ENI      ← has launch-wizard-1 SG
```

The EICE ENI needs to SEND a TCP 22 connection to the EC2.
The outbound rules of the Security Group control what traffic the EICE ENI can initiate.

Therefore, the Security Group also requires this outbound rule:

```text
Type:        SSH
Protocol:    TCP
Port:        22
Destination: sg-xxxxxxxxxxxxxxxxx  ← same SG ID (self-referencing)
```

Without this outbound rule, the EICE endpoint cannot reach the EC2 on port 22 even though the inbound rule permits it.
The result is:

```text
Websocket Closure Reason: Unable to connect to target
```

The two rules work together:

```text
Outbound SSH to self-SG
→ EICE is allowed to send TCP 22 to EC2

Inbound SSH from self-SG
→ EC2 is allowed to receive TCP 22 from EICE
```

Both are required when sharing a Security Group between EICE and the EC2 instance.

## Why changing outbound rules can break EICE

The default AWS Security Group outbound rule is:

```text
All traffic → 0.0.0.0/0
```

This implicitly allows the EICE to send TCP 22 to the EC2.

If you replace "All traffic" with a more restrictive rule such as "HTTPS 443 only", EICE immediately stops working because TCP 22 outbound is no longer permitted.

The safe approach is to always explicitly add back:

```text
SSH TCP 22 → self-SG
```

when tightening outbound rules on a Security Group used by EICE.

---

# 7. Install AWS CLI Locally

You need AWS CLI on the computer initiating the EICE connection.

Verify:

```bash
aws --version
```

If you intentionally keep AWS CLI inside a Conda environment:

```bash
conda activate tradingbot
```

Then:

```bash
which aws
```

The path should point inside the environment.

For example:

```text
.../envs/tradingbot/bin/aws
```

This keeps AWS tooling scoped to the Conda environment instead of installing it globally.

---

# 8. SSH Through EICE

Using AWS CLI, the connection is proxied through the EICE via a `ProxyCommand` in `~/.ssh/config`.

## Important: use the instance ID as HostName

When connecting through EICE, set `HostName` to the **instance ID**, not the private IP.
Use `%h` in the `ProxyCommand` so SSH passes it through automatically.

```text
Host tradeloop
    HostName i-023c5944ea7f33c74
    User ubuntu
    IdentityFile /path/to/your.pem
    ProxyCommand /absolute/path/to/aws ec2-instance-connect open-tunnel \
        --instance-id %h \
        --instance-connect-endpoint-id eice-0e104884fea225e22 \
        --region eu-north-1
```

## Why the absolute AWS CLI path matters

VS Code Remote SSH and plain `ssh` launched from a non-Conda terminal do not inherit the activated Conda environment.

If `ProxyCommand` uses just `aws`, it will pick up whichever AWS CLI is first on `$PATH` at the time SSH runs — which may be a different version or have different credentials.

Using the absolute path:

```text
/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/aws
```

guarantees the correct AWS CLI is always used regardless of how SSH was launched.

## The working SSH config entry

```text
Host tradeloop
    HostName i-023c5944ea7f33c74
    User ubuntu
    IdentityFile /Volumes/D-DRIVE/TB/p2.pem
    ProxyCommand /Users/dhyanpatel/anaconda3/envs/tradingbot/bin/aws \
        ec2-instance-connect open-tunnel \
        --instance-id %h \
        --instance-connect-endpoint-id eice-0e104884fea225e22 \
        --region eu-north-1
```

Then connect with:

```bash
ssh tradeloop
```

---

# 9. Connect Through VS Code

Install the VS Code extension:

```text
Remote - SSH
```

Then open the Command Palette:

```text
Cmd + Shift + P
```

Choose:

```text
Remote-SSH: Connect to Host...
```

Then select the host from:

```text
~/.ssh/config
```

For example:

```text
tradeloop
```

VS Code opens a remote window connected to EC2.

---

# 10. Add an Elastic IP

For simpler direct SSH, allocate an Elastic IP:

```text
EC2
→ Network & Security
→ Elastic IP addresses
→ Allocate Elastic IP address
```

The working Elastic IP was:

```text
13.53.253.22
```

An allocated Elastic IP is not automatically attached to the EC2 instance.

---

# 11. Associate the Elastic IP Correctly

Do this from:

```text
EC2
→ Network & Security
→ Elastic IP addresses
```

Select the Elastic IP.

Then:

```text
Actions
→ Associate Elastic IP address
```

Use:

```text
Resource type:
Instance

Instance:
i-023c5944ea7f33c74

Private IP:
172.31.39.213
```

`Allow this Elastic IP address to be reassociated` can normally remain unchecked.

Then click:

```text
Associate
```

The mapping becomes:

```text
13.53.253.22
      │
      ▼
EC2 instance
      │
      ▼
172.31.39.213
```

Important: the Elastic IP must be allocated in the **same AWS Region** as the EC2 instance.

For this setup:

```text
eu-north-1
Europe (Stockholm)
```

---

# 12. Direct SSH Using the Elastic IP

Once attached:

```bash
ssh -i ~/.ssh/tradeloop.pem ubuntu@13.53.253.22
```

You no longer need EICE for this connection.

---

# 13. Create a Short SSH Alias

Edit:

```bash
nano ~/.ssh/config
```

Add:

```text
Host tradeloop
    HostName 13.53.253.22
    User ubuntu
    IdentityFile /Volumes/D-DRIVE/TB/p2.pem
    IdentitiesOnly yes
```

Now instead of:

```bash
ssh -i /Volumes/D-DRIVE/TB/p2.pem ubuntu@13.53.253.22
```

you can simply use:

```bash
ssh tradeloop
```

VS Code Remote SSH can also use:

```text
tradeloop
```

## Transitioning from EICE to Elastic IP

If you previously had an EICE-based config entry and are switching to the Elastic IP:

Replace the entire `Host tradeloop` block in `~/.ssh/config`.
Remove the `ProxyCommand` line entirely.
Set `HostName` to the Elastic IP address instead of the instance ID.

Before:

```text
Host tradeloop
    HostName i-023c5944ea7f33c74
    User ubuntu
    IdentityFile /Volumes/D-DRIVE/TB/p2.pem
    ProxyCommand /Users/dhyanpatel/anaconda3/envs/tradingbot/bin/aws \
        ec2-instance-connect open-tunnel \
        --instance-id %h \
        --instance-connect-endpoint-id eice-0e104884fea225e22 \
        --region eu-north-1
```

After:

```text
Host tradeloop
    HostName 13.53.253.22
    User ubuntu
    IdentityFile /Volumes/D-DRIVE/TB/p2.pem
    IdentitiesOnly yes
```

You can keep both entries under different `Host` names if you want to retain EICE as a fallback:

```text
Host tradeloop
    HostName 13.53.253.22
    User ubuntu
    IdentityFile /Volumes/D-DRIVE/TB/p2.pem
    IdentitiesOnly yes

Host tradeloop-eice
    HostName i-023c5944ea7f33c74
    User ubuntu
    IdentityFile /Volumes/D-DRIVE/TB/p2.pem
    ProxyCommand /Users/dhyanpatel/anaconda3/envs/tradingbot/bin/aws \
        ec2-instance-connect open-tunnel \
        --instance-id %h \
        --instance-connect-endpoint-id eice-0e104884fea225e22 \
        --region eu-north-1
```

EICE remains useful as a fallback if the Elastic IP is ever released or reassigned.

---

# 14. Internet Gateway Requirement

An Elastic IP alone does not provide internet connectivity.

The subnet's route table must have a route similar to:

```text
Destination       Target
0.0.0.0/0         igw-xxxxxxxx
```

`igw-xxxxxxxx` is an Internet Gateway attached to the VPC.

Check:

```text
VPC
→ Route Tables
→ route table associated with EC2 subnet
→ Routes
```

Without this route, the instance cannot communicate directly with the public internet using the Elastic IP.

---

# 15. Test Public Internet Connectivity

From the EC2 instance:

```bash
curl https://api.ipify.org
```

For the working setup this returned:

```text
13.53.253.22
```

That proves:

```text
EC2
→ Internet Gateway
→ Internet
```

is functioning and outbound traffic is using the Elastic IP.

---

# 16. Test HTTPS

Run:

```bash
curl -I https://www.google.com
```

A successful result includes something such as:

```text
HTTP/2 200
```

This proves outbound TCP port `443` works.

---

# 17. Why `ping google.com` May Fail

You may see:

```text
44 packets transmitted
0 received
100% packet loss
```

while HTTPS still works.

This is possible because:

```text
ping
→ ICMP

curl https://...
→ TCP port 443
```

They are different protocols.

Therefore:

```text
ping fails
```

does not automatically mean:

```text
internet is unavailable
```

A better test for normal server internet access is:

```bash
curl -I https://www.google.com
```

---

# 18. Security Group Outbound Rules

The original outbound Security Group configuration allowed:

```text
HTTPS
TCP
443
0.0.0.0/0
```

but did not allow port `80`.

That meant:

```text
HTTPS :443    ✅
HTTP  :80     ❌
ICMP          ❌
```

This explained why:

```bash
curl https://www.google.com
```

worked while some other commands did not.

---

# 19. Why `apt update` Initially Failed

`sudo apt update` produced errors such as:

```text
Could not connect to security.ubuntu.com:80
```

The configured Ubuntu repositories were:

```text
http://eu-north-1.ec2.archive.ubuntu.com/ubuntu/
http://security.ubuntu.com/ubuntu
```

Since they started with:

```text
http://
```

APT tried to use:

```text
TCP port 80
```

But only outbound port `443` was allowed.

Therefore:

```text
APT → port 80 → Security Group → blocked
```

---

# 20. HTTP vs HTTPS

The important distinction is:

```text
HTTP
Port 80
Unencrypted

HTTPS
Port 443
Encrypted using TLS
```

For example:

```text
http://example.com
       ↓
     TCP 80
```

while:

```text
https://example.com
        ↓
      TCP 443
```

---

# 21. Make Ubuntu APT Use HTTPS Only

The Ubuntu configuration was stored at:

```text
/etc/apt/sources.list.d/ubuntu.sources
```

Inspect it:

```bash
cat /etc/apt/sources.list.d/ubuntu.sources
```

The original configuration included:

```text
URIs: http://eu-north-1.ec2.archive.ubuntu.com/ubuntu/
```

and:

```text
URIs: http://security.ubuntu.com/ubuntu
```

First create a backup:

```bash
sudo cp /etc/apt/sources.list.d/ubuntu.sources \
/etc/apt/sources.list.d/ubuntu.sources.backup
```

Then replace HTTP with HTTPS:

```bash
sudo sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources
```

Verify:

```bash
grep '^URIs:' /etc/apt/sources.list.d/ubuntu.sources
```

Expected:

```text
URIs: https://eu-north-1.ec2.archive.ubuntu.com/ubuntu/
URIs: https://security.ubuntu.com/ubuntu
```

Now APT uses:

```text
TCP 443
```

instead of port `80`.

Test:

```bash
sudo apt update
```

---

# 22. Important APT Detail

APT itself is not inherently HTTP or HTTPS.

APT follows whatever repository URL is configured.

```text
APT
 │
 ├── http://repository
 │       ↓
 │      :80
 │
 └── https://repository
         ↓
        :443
```

Therefore switching the repository URLs to HTTPS allows you to run APT without permitting outbound port 80.

---

# 23. Install Git

Once APT works:

```bash
sudo apt update
sudo apt install git -y
```

Verify:

```bash
git --version
```

---

# 24. Clone a Public Git Repository

Because GitHub HTTPS uses port 443:

```bash
git clone https://github.com/USERNAME/REPOSITORY.git
```

Then:

```bash
cd REPOSITORY
```

This works with the HTTPS-only outbound configuration.

---

# 25. Clone a Private GitHub Repository

For private repositories, authentication is required.

The two common options are:

```text
GitHub HTTPS authentication
```

or:

```text
GitHub SSH key authentication
```

Do not place GitHub passwords or tokens directly inside shell commands that will remain in shell history.

---

# 26. Git Workflow Between Local Mac and VPS

The intended daily workflow is:

```text
Local Mac
   │
   │ git push origin main
   ▼
GitHub
   │
   │ git pull
   ▼
VPS (tradeloop)
```

## On the local Mac after making changes

```bash
git add .
git commit -m "your message"
git push origin main
```

## On the VPS to receive those changes

```bash
cd ~/tradeloop
git pull
```

This is a fast-forward pull with no conflicts provided you only edit code on the local Mac and only run code on the VPS.

Conflicts occur if the same file is edited on both the Mac and the VPS between syncs.
Avoid editing files directly on the VPS.
Use the VPS only for running scripts, not for development.

## Checking the VPS is up to date

```bash
git log --oneline -5
```

Compare the top commit hash with what GitHub shows.
If they match, the VPS is current.

---

# 27. Syncing Files Without GitHub Access (rsync)

If the VPS cannot reach GitHub (for example, before the Elastic IP was attached or before internet routing was confirmed), you can push files directly from the local Mac over the SSH tunnel.

Run this from the **local Mac terminal**:

```bash
rsync -avz -e "ssh" \
  --exclude '.env' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.git' \
  --exclude 'node_modules/' \
  --exclude 'tradeloop/runs/' \
  --exclude 'tradeloop/state/ledger.db' \
  /Volumes/D-DRIVE/TradingBot/ \
  tradeloop:~/tradeloop/
```

This copies all files from the local repo to the VPS over the existing SSH connection.
No internet access is required on the VPS for this to work.

This is useful as a one-time bootstrap before `git pull` is available.
After internet connectivity is confirmed on the VPS, switch to the `git pull` workflow.

---

# 28. Recommended Security Group Configuration

For the setup where the server mostly makes HTTPS requests:

## Inbound

```text
SSH
TCP
22
YOUR_PUBLIC_IP/32
```

Optionally, if using EICE:

```text
SSH
TCP
22
EICE_SECURITY_GROUP (or self-SG if shared)
```

Do not expose:

```text
SSH 22 → 0.0.0.0/0
```

unless necessary.

## Outbound

```text
HTTPS
TCP
443
0.0.0.0/0
```

If EICE shares the same Security Group:

```text
SSH
TCP
22
self-SG
```

If your applications also require HTTP traffic:

```text
HTTP
TCP
80
0.0.0.0/0
```

---

# 29. Inbound vs Outbound Rules

This distinction is important.

## Inbound

Controls traffic coming **into** EC2:

```text
Internet
   │
   ▼
EC2
```

Examples:

```text
SSH 22
HTTP 80
HTTPS 443
```

## Outbound

Controls connections initiated **by EC2**:

```text
EC2
 │
 ▼
Internet
```

Examples:

```text
apt update
git clone
pip install
API requests
curl
```

You do not need inbound port 443 simply because EC2 uses HTTPS to access the internet.

---

# 30. Elastic IP Does Not Exist Inside Ubuntu

Ubuntu continues to see its private interface address:

```text
172.31.39.213
```

For example, your terminal prompt might show:

```text
ubuntu@ip-172-31-39-213
```

This is normal.

AWS performs the mapping:

```text
Public Elastic IP
13.53.253.22
        │
        │ AWS networking
        ▼
Private EC2 IP
172.31.39.213
```

The operating system itself usually operates using the private IP.

---

# 31. Verify the Current Network

Useful commands:

```bash
ip addr
```

Show routing:

```bash
ip route
```

Check DNS:

```bash
getent hosts google.com
```

Check outbound public IP:

```bash
curl https://api.ipify.org
```

Check HTTPS:

```bash
curl -I https://www.google.com
```

Check HTTP:

```bash
curl -4 -I --connect-timeout 5 http://example.com
```

---

# 32. Useful Troubleshooting Logic

If this works:

```bash
curl https://api.ipify.org
```

then outbound HTTPS works.

If:

```bash
curl https://...
```

works but:

```bash
curl http://...
```

fails, inspect outbound TCP port `80`.

If:

```bash
curl https://...
```

works but:

```bash
ping google.com
```

fails, investigate ICMP only if you actually need ping.

If:

```bash
ping 8.8.8.8
```

works but:

```bash
ping google.com
```

does not, investigate DNS.

If EICE connects successfully from local but shows:

```text
Websocket Closure Reason: Unable to connect to target
```

check in this order:

```text
1. Is the EC2 instance in Running state?
2. Does the Security Group inbound allow SSH from the EICE SG?
3. Does the Security Group outbound allow SSH to the EICE SG (self)?
4. Did a recent outbound rule change remove All-traffic and forget to add SSH back?
```

If **everything** fails, investigate:

```text
EC2 Security Group
↓
Network ACL
↓
Subnet Route Table
↓
Internet Gateway / NAT
```

---

# 33. Recommended Final Architecture

For this development EC2 setup:

```text
                    Internet
                       │
                       │
                  AWS Internet
                    Gateway
                       │
                       ▼
                Elastic IP
               13.53.253.22
                       │
                       ▼
                  EC2 Instance
                 Tradeloop-VPS
                       │
              172.31.39.213
                       │
              ┌────────┴────────┐
              │                 │
           TCP 443           SSH TCP 22
              │                 │
              ▼                 ▼
      GitHub / APIs / APT    Your computer
```

SSH should be restricted to your public IP.

Normal package/API/Git traffic can use HTTPS port `443`.

---

# 34. Recommended `~/.ssh/config`

Once the Elastic IP is configured:

```text
Host tradeloop
    HostName 13.53.253.22
    User ubuntu
    IdentityFile /Volumes/D-DRIVE/TB/p2.pem
    IdentitiesOnly yes
```

Then Terminal becomes:

```bash
ssh tradeloop
```

And VS Code:

```text
Cmd + Shift + P
→ Remote-SSH: Connect to Host
→ tradeloop
```

---

# 35. Future Setup Checklist

When creating another EC2 VPS, follow this order:

- [ ] Launch Ubuntu EC2 instance.
- [ ] Download and securely store the PEM key.
- [ ] Run `chmod 400` on the PEM key.
- [ ] Note the PEM file full path — use it consistently in `~/.ssh/config`.
- [ ] Create or select the correct Security Group.
- [ ] Allow SSH `22` from your own IP.
- [ ] Decide between EICE/private access and Elastic-IP/direct access.
- [ ] If using EICE, create an EC2 Instance Connect Endpoint in the same VPC.
- [ ] Allow EICE Security Group → instance TCP `22` (inbound).
- [ ] If EICE and EC2 share the same Security Group, also add outbound SSH TCP `22` to self-SG.
- [ ] If using an Elastic IP, allocate it in the same region.
- [ ] Associate the Elastic IP with the EC2 instance's primary private IP.
- [ ] Confirm subnet route `0.0.0.0/0 → Internet Gateway`.
- [ ] Test `curl https://api.ipify.org` — confirm it returns the Elastic IP.
- [ ] Test `curl -I https://www.google.com` — confirm `HTTP/2 200`.
- [ ] Configure outbound Security Group rules (HTTPS 443, and SSH 22 to self if EICE).
- [ ] Convert Ubuntu APT repository URLs from HTTP to HTTPS.
- [ ] Run `sudo apt update`.
- [ ] Install Git: `sudo apt install git -y`.
- [ ] Add SSH alias in `~/.ssh/config` using the absolute PEM path.
- [ ] Test `ssh HOST_ALIAS` from local terminal.
- [ ] Configure VS Code Remote SSH using the same alias.
- [ ] Clone or sync the repository: `git clone https://github.com/...` or rsync from local.
- [ ] Confirm `git pull` works from the VPS.
- [ ] Establish the ongoing workflow: edit on Mac → `git push` → `git pull` on VPS.

---

# 36. Minimal Command Reference

## Secure key

```bash
chmod 400 /path/to/key.pem
```

## Direct SSH

```bash
ssh -i /Volumes/D-DRIVE/TB/p2.pem ubuntu@13.53.253.22
```

## Short SSH

```bash
ssh tradeloop
```

## Dashboard SSH forwarding

Use a different dashboard port on EC2 so it does not collide with the local Mac dashboard.

```bash
ssh -L 8771:127.0.0.1:8771 tradeloop
```

On the EC2 shell, start the dashboard on the forwarded port:

```bash
python -m tradeloop.dashboard --port 8771
```

On the Mac, open:

```text
http://127.0.0.1:8771
```

Keep the local Mac dashboard on the default port:

```bash
python -m tradeloop.dashboard
```

```text
http://127.0.0.1:8770
```

## Check public IP

```bash
curl https://api.ipify.org
```

## Test internet

```bash
curl -I https://www.google.com
```

## Inspect APT URLs

```bash
grep '^URIs:' /etc/apt/sources.list.d/ubuntu.sources
```

## Back up APT configuration

```bash
sudo cp /etc/apt/sources.list.d/ubuntu.sources \
/etc/apt/sources.list.d/ubuntu.sources.backup
```

## Convert APT to HTTPS

```bash
sudo sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources
```

## Update packages

```bash
sudo apt update
```

## Install Git

```bash
sudo apt install git -y
```

## Clone repository

```bash
git clone https://github.com/USERNAME/REPOSITORY.git
```

## Sync from local Mac when GitHub is unreachable

```bash
rsync -avz -e "ssh" \
  --exclude '.env' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.git' \
  --exclude 'node_modules/' \
  --exclude 'tradeloop/runs/' \
  --exclude 'tradeloop/state/ledger.db' \
  /Volumes/D-DRIVE/TradingBot/ \
  tradeloop:~/tradeloop/
```

## Pull latest changes on VPS

```bash
cd ~/tradeloop && git pull
```

---

# 37. The Key Concepts to Remember

**Private IP**

```text
172.31.x.x
```

Exists inside the AWS VPC.

**Elastic IP**

```text
13.x.x.x
```

Static public IPv4 address mapped by AWS to your EC2 instance.

**EICE**

Provides SSH access to a private EC2 instance without giving the instance a public IP.
The EICE endpoint has a network interface inside the VPC and requires both inbound and outbound Security Group rules when sharing an SG with the EC2.

**Internet Gateway**

Allows a public-subnet EC2 instance with a public/Elastic IP to communicate with the internet.

**Security Group**

Stateful firewall attached to the EC2 instance/network interface.
Stateful means return traffic for established connections is automatically allowed — you do not need an explicit outbound rule for SSH responses to inbound SSH connections.
However, the EICE ENI needs an explicit outbound SSH rule because it is the initiator of the connection.

**Port 22**

SSH.

**Port 80**

HTTP.

**Port 443**

HTTPS.

**`chmod 400`**

Makes the SSH private key readable only by its owner.

**`curl https://api.ipify.org`**

One of the quickest ways to verify internet access and determine which public IPv4 address the EC2 instance is using.

**`HTTP/2 200` from Google**

Confirms real outbound HTTPS connectivity.

**Failed ping alone**

Does not prove that internet access is broken.

**Websocket Closure Reason: Unable to connect to target**

EICE reached AWS successfully but could not establish TCP 22 to the EC2.
Most common causes: instance stopped, missing inbound SSH rule from EICE SG, or missing outbound SSH rule to self-SG.

---

With the final Elastic-IP setup, the normal daily workflow becomes only:

```bash
ssh tradeloop
```

and for VS Code:

```text
Remote-SSH → tradeloop
```

Everything underneath — the PEM path, username, IP address, and SSH parameters — is handled by `~/.ssh/config`.
