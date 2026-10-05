@description('Azure region for SmartDocument resources')
param location string = resourceGroup().location

@description('Environment prefix')
param environment string = 'prod'

@description('ACR login server')
param acrServer string = 'smartdocacr.azurecr.io'

@description('Image tag for API')
param imageTagApi string = 'latest'

@description('Image tag for Worker')
param imageTagWorker string = 'latest'

var uniqueSuffix = substring(uniqueString(resourceGroup().id), 0, 6)
var lawName = 'smartdoc-law-${uniqueSuffix}'
var caeName = 'smartdoc-cae-${uniqueSuffix}'
var storageAccountName = 'stsmartdoc${uniqueSuffix}'
var searchServiceName = 'smartdoc-search-${uniqueSuffix}'
var sbNamespaceName = 'smartdoc-sb-${uniqueSuffix}'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: lawName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource managedEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: caeName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'smartdoc-uai-${uniqueSuffix}'
  location: location
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource documentsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'enterprise-documents'
  properties: {
    publicAccess: 'None'
  }
}

resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchServiceName
  location: location
  sku: {
    name: 'basic'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
  }
}

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: sbNamespaceName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
}

resource ingestionQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: serviceBusNamespace
  name: 'smartdoc-ingestion-jobs'
  properties: {
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: 'PT10M'
    deadLetteringOnMessageExpiration: true
    maxDeliveryCount: 5
  }
}

resource smartdocApi 'Microsoft.App/containerApps@2023-05-01' = {
  name: 'smartdoc-api'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: managedEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
      }
    }
    template: {
      containers: [
        {
          name: 'smartdoc-api'
          image: '${acrServer}/smartdoc-backend:${imageTagApi}'
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
          env: [
            {
              name: 'SPRING_PROFILES_ACTIVE'
              value: environment
            }
            {
              name: 'PORT'
              value: '8080'
            }
            {
              name: 'STORAGE_PROVIDER'
              value: 'blob'
            }
            {
              name: 'BLOB_CONTAINER_NAME'
              value: documentsContainer.name
            }
            {
              name: 'AZURE_SEARCH_ENDPOINT'
              value: 'https://${searchService.name}.search.windows.net'
            }
            {
              name: 'AZURE_SERVICE_BUS_QUEUE'
              value: ingestionQueue.name
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 5
        rules: [
          {
            name: 'http-rule'
            http: {
              metadata: {
                concurrentRequests: '30'
              }
            }
          }
        ]
      }
    }
  }
}

resource smartdocWorker 'Microsoft.App/containerApps@2023-05-01' = {
  name: 'smartdoc-ingestion-worker'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: managedEnv.id
    template: {
      containers: [
        {
          name: 'smartdoc-worker'
          image: '${acrServer}/smartdoc-worker:${imageTagWorker}'
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
          env: [
            {
              name: 'PYTHON_ENV'
              value: environment
            }
            {
              name: 'SERVICE_BUS_QUEUE'
              value: ingestionQueue.name
            }
            {
              name: 'AZURE_SEARCH_ENDPOINT'
              value: 'https://${searchService.name}.search.windows.net'
            }
            {
              name: 'STORAGE_CONTAINER_NAME'
              value: documentsContainer.name
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
        rules: [
          {
            name: 'service-bus-queue-rule'
            custom: {
              type: 'azure-servicebus'
              metadata: {
                queueName: ingestionQueue.name
                messageCount: '5'
                namespace: serviceBusNamespace.name
              }
            }
          }
        ]
      }
    }
  }
}

output apiFqdn string = smartdocApi.properties.configuration.ingress.fqdn
output storageAccountName string = storageAccount.name
output searchServiceName string = searchService.name
output serviceBusNamespaceName string = serviceBusNamespace.name
