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
