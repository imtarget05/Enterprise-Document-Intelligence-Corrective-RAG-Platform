resource "azurerm_search_service" "search" {
  name                = "smartdoc-search-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "basic"
  replica_count       = 1
  partition_count     = 1

  tags = azurerm_resource_group.rg.tags
}

resource "azurerm_role_assignment" "search_service_contributor" {
  scope                = azurerm_search_service.search.id
  role_definition_name = "Search Index Data Contributor"
  principal_id         = azurerm_user_assigned_identity.identity.principal_id
}
