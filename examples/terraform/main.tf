terraform {
  required_version = ">= 1.5.0"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.66"
    }
  }
}

provider "proxmox" {
  endpoint = var.endpoint
  api_token = var.api_token
  insecure  = var.insecure
}

variable "endpoint" {
  type        = string
  description = "Simulator HTTPS gateway, e.g. https://localhost:8006"
  default     = "https://localhost:8006"
}

variable "api_token" {
  type        = string
  description = "PVE API token USER@REALM!TOKENID=SECRET"
  default     = "root@pam!automation=automation-secret"
  sensitive   = true
}

variable "insecure" {
  type        = bool
  description = "Skip TLS verify for the local self-signed gateway certificate"
  default     = true
}

variable "node_name" {
  type    = string
  default = "pve01"
}

variable "vmid" {
  type    = number
  default = 117
}

# Provider resource schemas evolve — adjust attribute names to the provider
# version you pin. This file is a lab starting point against the simulator.
resource "proxmox_virtual_environment_vm" "cookbook" {
  name      = "tf-cookbook-${var.vmid}"
  node_name = var.node_name
  vm_id     = var.vmid

  cpu {
    cores = 1
  }

  memory {
    dedicated = 512
  }

  agent {
    enabled = false
  }
}
