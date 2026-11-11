terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
    key_vault {
      purge_soft_delete_on_destroy = true
    }
  }
}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "rg" {
  name     = var.resource_group_name
  location = var.location
  tags = {
    Environment = var.environment
    Project     = "SmartDocument"
    ManagedBy   = "Terraform"
  }
}

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "smartdoc-law-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = azurerm_resource_group.rg.tags
}

resource "azurerm_container_app_environment" "env" {
  name                       = "smartdoc-cae-env"
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = azurerm_resource_group.rg.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  tags                       = azurerm_resource_group.rg.tags
}

resource "azurerm_user_assigned_identity" "identity" {
  name                = "smartdoc-uai"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  tags                = azurerm_resource_group.rg.tags
}

# ── Key Vault (secrets: DB conn string, JWT, API keys) ────────────────────────
resource "azurerm_key_vault" "secrets" {
  name                        = "smartdoc-kv-${random_string.suffix.result}"
  location                    = azurerm_resource_group.rg.location
  resource_group_name         = azurerm_resource_group.rg.name
  enabled_for_disk_encryption = true
  purge_protection_enabled    = false
  soft_delete_retention_days  = 7
  sku_name                    = "standard"
  tenant_id                   = data.azurerm_client_config.current.tenant_id

  tags = azurerm_resource_group.rg.tags
}

# ── Key Vault access policy (UAI reads secrets) ───────────────────────────────
resource "azurerm_key_vault_access_policy" "secrets" {
  key_vault_id      = azurerm_key_vault.secrets.id
  tenant_id         = data.azurerm_client_config.current.tenant_id
  object_id         = azurerm_user_assigned_identity.identity.principal_id
  secret_permissions = ["Get", "List"]
}

# ── Monitor Action Group (deploy/runtime alerts) ──────────────────────────────
resource "azurerm_monitor_action_group" "alerts" {
  name                = "smartdoc-ag-alerts"
  resource_group_name = azurerm_resource_group.rg.name
  short_name          = "sdocalerts"

  email_receiver {
    name        = "platform-alerts"
    email_address = var.alert_email
  }

  tags = azurerm_resource_group.rg.tags
}

# ── Monitor Metric Alert: Container App HTTP 5xx ──────────────────────────────
resource "azurerm_monitor_metric_alert" "http_5xx" {
  name                = "smartdoc-api-http-5xx"
  resource_group_name = azurerm_resource_group.rg.name
  scopes              = [azurerm_container_app.api.id]
  description         = "Alert when SmartDocument API returns HTTP 5xx"
  frequency           = "PT1M"
  window_size         = "PT5M"
  auto_mitigate       = true
  severity            = 2

  criteria {
    metric_namespace = "Microsoft.Insights/containerApps"
    metric_name      = "requests/failed"
    aggregation      = "Count"
    operator         = "GreaterThan"
    threshold        = 0
  }

  action {
    action_group_id = azurerm_monitor_action_group.alerts.id
  }

  tags = azurerm_resource_group.rg.tags
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "key_vault_name" {
  description = "Name of the Key Vault holding platform secrets"
  value       = azurerm_key_vault.secrets.name
}

output "key_vault_uri" {
  description = "Key Vault DNS URI"
  value       = azurerm_key_vault.secrets.vault_uri
}

output "action_group_id" {
  description = "Monitor action group id"
  value       = azurerm_monitor_action_group.alerts.id
}
