variable "resource_group_name" {
  type        = string
  description = "Resource Group Name for SmartDocument"
  default     = "rg-smartdoc-prod"
}

variable "location" {
  type        = string
  description = "Azure Region"
  default     = "eastus"
}

variable "vnet_address_space" {
  type        = list(string)
  description = "Address space for the Container Apps and private endpoint VNet"
  default     = ["10.80.0.0/16"]
}

variable "container_apps_subnet_address_prefix" {
  type        = string
  description = "Dedicated /23 subnet for the Container Apps environment"
  default     = "10.80.0.0/23"
}

variable "private_endpoints_subnet_address_prefix" {
  type        = string
  description = "Subnet for private endpoints"
  default     = "10.80.2.0/24"
}

variable "environment" {
  type        = string
  description = "Deployment environment"
  default     = "production"
}

variable "acr_server" {
  type        = string
  description = "Azure Container Registry login server"
  default     = "smartdocacr.azurecr.io"
}

variable "image_tag_api" {
  type        = string
  description = "Container image tag for SmartDoc API"
  default     = "latest"
}

variable "image_tag_worker" {
  type        = string
  description = "Container image tag for Ingestion Worker"
  default     = "latest"
}
