terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_key_pair" "this" {
  key_name   = var.label
  public_key = trimspace(var.ssh_pubkey)
}

# Allow all inbound — UFW on the host manages the actual port policy.
resource "aws_security_group" "this" {
  name        = var.label
  description = "honey-net ${var.label}: allow all inbound, UFW enforces port policy on-host"

  ingress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { for t in var.tags : t => "" }
}

resource "aws_instance" "this" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.type
  key_name               = aws_key_pair.this.key_name
  vpc_security_group_ids = [aws_security_group.this.id]

  # Ubuntu AMIs default to ubuntu@ access. Copy the key to root and enable
  # PermitRootLogin so the control plane can SSH as root consistently.
  user_data = base64encode(<<-EOF
    #!/bin/bash
    mkdir -p /root/.ssh
    echo '${trimspace(var.ssh_pubkey)}' >> /root/.ssh/authorized_keys
    chmod 700 /root/.ssh
    chmod 600 /root/.ssh/authorized_keys
    sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
    systemctl restart ssh
    EOF
  )

  tags = merge(
    { Name = var.label },
    { for t in var.tags : t => "" }
  )
}
