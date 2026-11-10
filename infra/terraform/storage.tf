resource "azurerm_storage_account" "storage" {
  name                     = "stsmartdoc${random_string.suffix.result}"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"

  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  public_network_access_enabled   = false
  shared_access_key_enabled       = false

  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
  }

  tags = azurerm_resource_group.rg.tags
}

resource "azapi_resource" "documents" {
  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01"
  name      = "enterprise-documents"
  parent_id = "${azurerm_storage_account.storage.id}/blobServices/default"

  body = {
    properties = {
      publicAccess = "None"
    }
  }

  schema_validation_enabled = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_role_assignment" "blob_contributor" {
  scope                = azapi_resource.documents.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.identity.principal_id
}

resource "azurerm_private_dns_zone" "storage_blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = azurerm_resource_group.rg.name
  tags                = azurerm_resource_group.rg.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "storage_blob" {
  name                  = "smartdoc-storage-blob"
  resource_group_name   = azurerm_resource_group.rg.name
  private_dns_zone_name = azurerm_private_dns_zone.storage_blob.name
  virtual_network_id    = azurerm_virtual_network.env.id
  registration_enabled  = false
  tags                  = azurerm_resource_group.rg.tags
}

resource "azurerm_private_endpoint" "storage_blob" {
  name                = "smartdoc-storage-blob-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = azurerm_resource_group.rg.tags

  private_service_connection {
    name                           = "smartdoc-storage-blob"
    private_connection_resource_id = azurerm_storage_account.storage.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "storage-blob"
    private_dns_zone_ids = [azurerm_private_dns_zone.storage_blob.id]
  }
}
