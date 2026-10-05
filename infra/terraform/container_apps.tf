resource "azurerm_container_app" "api" {
  name                         = "smartdoc-api"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"
  tags                         = azurerm_resource_group.rg.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.identity.id]
  }

  template {
    min_replicas = 0
    max_replicas = 5

    container {
      name   = "smartdoc-api"
      image  = "${var.acr_server}/smartdoc-backend:${var.image_tag_api}"
      cpu    = 0.5
      memory = "1.0Gi"

      env {
        name  = "SPRING_PROFILES_ACTIVE"
        value = "production"
      }
      env {
        name  = "PORT"
        value = "8080"
      }
      env {
        name  = "STORAGE_PROVIDER"
        value = "blob"
      }
      env {
        name  = "BLOB_CONTAINER_NAME"
        value = azurerm_storage_container.documents.name
      }
      env {
        name  = "AZURE_SEARCH_ENDPOINT"
        value = "https://${azurerm_search_service.search.name}.search.windows.net"
      }
      env {
        name  = "AZURE_SERVICE_BUS_QUEUE"
        value = azurerm_servicebus_queue.ingestion_jobs.name
      }
    }

    http_scale_rule {
      name                = "http-rule"
      concurrent_requests = 30
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}

resource "azurerm_container_app" "ingestion_worker" {
  name                         = "smartdoc-ingestion-worker"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"
  tags                         = azurerm_resource_group.rg.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.identity.id]
  }

  template {
    min_replicas = 0
    max_replicas = 3

    container {
      name   = "smartdoc-worker"
      image  = "${var.acr_server}/smartdoc-worker:${var.image_tag_worker}"
      cpu    = 0.5
      memory = "1.0Gi"

      env {
        name  = "PYTHON_ENV"
        value = "production"
      }
      env {
        name  = "SERVICE_BUS_QUEUE"
        value = azurerm_servicebus_queue.ingestion_jobs.name
      }
      env {
        name  = "AZURE_SEARCH_ENDPOINT"
        value = "https://${azurerm_search_service.search.name}.search.windows.net"
      }
      env {
        name  = "STORAGE_CONTAINER_NAME"
        value = azurerm_storage_container.documents.name
      }
    }

    custom_scale_rule {
      name             = "service-bus-queue-rule"
      custom_rule_type = "azure-servicebus"
      metadata = {
        queueName    = azurerm_servicebus_queue.ingestion_jobs.name
        messageCount = "5"
        namespace    = azurerm_servicebus_namespace.sb.name
      }
    }
  }
}
