resource "azurerm_servicebus_namespace" "sb" {
  name                = "smartdoc-sb-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Standard"
  tags                = azurerm_resource_group.rg.tags
}

resource "azurerm_servicebus_queue" "ingestion_jobs" {
  name                                    = "smartdoc-ingestion-jobs"
  namespace_id                            = azurerm_servicebus_namespace.sb.id
  partitioning_enabled                    = false
  requires_duplicate_detection            = true
  duplicate_detection_history_time_window = "PT10M"
  dead_lettering_on_message_expiration    = true
  max_delivery_count                      = 5
}

resource "azurerm_role_assignment" "sb_data_owner" {
  scope                = azurerm_servicebus_namespace.sb.id
  role_definition_name = "Azure Service Bus Data Owner"
  principal_id         = azurerm_user_assigned_identity.identity.principal_id
}
