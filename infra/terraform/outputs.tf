output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.rg.name
}

output "container_app_environment_id" {
  description = "ID of the Container App Environment"
  value       = azurerm_container_app_environment.env.id
}

output "api_fqdn" {
  description = "Public FQDN of the SmartDocument API"
  value       = azurerm_container_app.api.latest_revision_fqdn
}

output "storage_account_name" {
  description = "Name of the Azure Storage Account"
  value       = azurerm_storage_account.storage.name
}

output "documents_container_name" {
  description = "Name of the documents container"
  value       = azurerm_storage_container.documents.name
}

output "search_service_name" {
  description = "Name of the Azure AI Search service"
  value       = azurerm_search_service.search.name
}

output "search_service_endpoint" {
  description = "Endpoint of the Azure AI Search service"
  value       = "https://${azurerm_search_service.search.name}.search.windows.net"
}

output "service_bus_namespace_name" {
  description = "Name of the Azure Service Bus namespace"
  value       = azurerm_servicebus_namespace.sb.name
}

output "identity_principal_id" {
  description = "Principal ID of the User Assigned Identity"
  value       = azurerm_user_assigned_identity.identity.principal_id
}
