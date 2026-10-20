// Touchline resources. Keyless: every service is reached with the app's managed identity.
param location string
param tags object
param environmentName string
param deployFoundry bool
param fastModelName string
param fastModelVersion string
param reasoningModelName string
param reasoningModelVersion string
@secure()
param teamsWebhookUrl string
param appImage string

var token = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var name = 'touchline'
var image = empty(appImage) ? 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest' : appImage

// ---------------------------------------------------------------- identity & observability
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${name}-${token}'
  location: location
  tags: tags
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${name}-${token}'
  location: location
  tags: tags
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${name}-${token}'
  location: location
  tags: tags
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'cr${name}${token}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

// ---------------------------------------------------------------- data plane
resource eventHubs 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: 'evhns-${name}-${token}'
  location: location
  tags: tags
  sku: { name: 'Standard', tier: 'Standard', capacity: 1 }
  properties: { disableLocalAuth: true }
}

resource matchEvents 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: eventHubs
  name: 'match-events'
  properties: { partitionCount: 4, messageRetentionInDays: 1 }
}

resource fabricConsumer 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = {
  parent: matchEvents
  name: 'fabric'
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: 'cosmos-${name}-${token}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [ { locationName: location, failoverPriority: 0 } ]
    capabilities: [ { name: 'EnableServerless' } ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    disableLocalAuth: true
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmos
  name: 'touchline'
  properties: { resource: { id: 'touchline' } }
}

resource blackboard 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDb
  name: 'blackboard'
  properties: {
    resource: {
      id: 'blackboard'
      partitionKey: { paths: [ '/match_id' ], kind: 'Hash' }
      defaultTtl: 2592000
    }
  }
}

resource webPubSub 'Microsoft.SignalRService/webPubSub@2024-03-01' = {
  name: 'wps-${name}-${token}'
  location: location
  tags: tags
  sku: { name: 'Standard_S1', capacity: 1 }
  properties: { disableLocalAuth: true }
}

resource translator 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'trl-${name}-${token}'
  location: location
  tags: tags
  kind: 'TextTranslation'
  sku: { name: 'S1' }
  properties: { customSubDomainName: 'trl-${name}-${token}', disableLocalAuth: false }
}

resource contentSafety 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'cs-${name}-${token}'
  location: location
  tags: tags
  kind: 'ContentSafety'
  sku: { name: 'S0' }
  properties: { customSubDomainName: 'cs-${name}-${token}', disableLocalAuth: true }
}

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: 'srch-${name}-${token}'
  location: location
  tags: tags
  sku: { name: 'basic' }
  properties: { authOptions: { aadOrApiKey: { aadAuthFailureMode: 'http401WithBearerChallenge' } } }
}

// ---------------------------------------------------------------- Microsoft Foundry (AI Services + project)
resource foundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = if (deployFoundry) {
  name: 'aif-${name}-${token}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: 'aif-${name}-${token}'
    allowProjectManagement: true
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = if (deployFoundry) {
  parent: foundry
  name: 'touchline'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: { displayName: 'Touchline', description: 'Explainable match intelligence agents' }
}

resource fastDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (deployFoundry) {
  parent: foundry
  name: fastModelName
  sku: { name: 'GlobalStandard', capacity: 100 }
  properties: { model: { format: 'OpenAI', name: fastModelName, version: fastModelVersion } }
}

resource reasoningDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (deployFoundry) {
  parent: foundry
  name: reasoningModelName
  sku: { name: 'GlobalStandard', capacity: 50 }
  properties: { model: { format: 'OpenAI', name: reasoningModelName, version: reasoningModelVersion } }
  dependsOn: [ fastDeployment ]
}

// ---------------------------------------------------------------- role assignments (managed identity)
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  eventHubsDataOwner: 'f526a384-b230-433a-b45c-95f59c4a2dec'
  webPubSubOwner: '12cf5a90-567b-43ae-8102-96cf46c7d9b4'
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  azureAIUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, identity.id, roles.acrPull)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull) }
}

resource ehOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: eventHubs
  name: guid(eventHubs.id, identity.id, roles.eventHubsDataOwner)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.eventHubsDataOwner) }
}

resource wpsOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: webPubSub
  name: guid(webPubSub.id, identity.id, roles.webPubSubOwner)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.webPubSubOwner) }
}

resource csUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: contentSafety
  name: guid(contentSafety.id, identity.id, roles.cognitiveServicesUser)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesUser) }
}

resource foundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployFoundry) {
  scope: foundry
  name: guid(resourceGroup().id, identity.id, roles.azureAIUser)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.azureAIUser) }
}

resource foundryCsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployFoundry) {
  scope: foundry
  name: guid(resourceGroup().id, identity.id, roles.cognitiveServicesUser, 'foundry')
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesUser) }
}

resource searchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, identity.id, roles.searchIndexDataContributor)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor) }
}

resource searchSvc 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, identity.id, roles.searchServiceContributor)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor) }
}

// Cosmos DB data-plane RBAC (Built-in Data Contributor)
resource cosmosData 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, identity.id, 'data-contributor')
  properties: {
    principalId: identity.properties.principalId
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    scope: cosmos.id
  }
}

// ---------------------------------------------------------------- Logic App: distribute full-time recaps
resource recapLogicApp 'Microsoft.Logic/workflows@2019-05-01' = {
  name: 'logic-${name}-recap-${token}'
  location: location
  tags: tags
  properties: {
    state: 'Enabled'
    parameters: { teamsWebhook: { value: teamsWebhookUrl } }
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      parameters: { teamsWebhook: { type: 'securestring', defaultValue: '' } }
      triggers: {
        recap: {
          type: 'Request'
          kind: 'Http'
          inputs: { schema: { type: 'object', properties: { headline: { type: 'string' }, standfirst: { type: 'string' }, body_md: { type: 'string' }, match_id: { type: 'string' } } } }
        }
      }
      actions: {
        Post_to_Teams: {
          type: 'If'
          expression: { and: [ { not: { equals: [ '@parameters(\'teamsWebhook\')', '' ] } } ] }
          actions: {
            Send: {
              type: 'Http'
              inputs: {
                method: 'POST'
                uri: '@parameters(\'teamsWebhook\')'
                body: { text: '**@{triggerBody()?[\'headline\']}**\n\n@{triggerBody()?[\'standfirst\']}\n\n@{triggerBody()?[\'body_md\']}' }
              }
            }
          }
          runAfter: {}
        }
        Response: {
          type: 'Response'
          kind: 'Http'
          inputs: { statusCode: 202, body: { received: '@triggerBody()?[\'match_id\']' } }
          runAfter: { Post_to_Teams: [ 'Succeeded', 'Skipped', 'Failed' ] }
        }
      }
    }
  }
}

// ---------------------------------------------------------------- Container Apps
resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${name}-${token}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey }
    }
  }
}

var foundryEndpoint = deployFoundry ? 'https://aif-${name}-${token}.services.ai.azure.com/api/projects/touchline' : ''

var commonEnv = [
  { name: 'TOUCHLINE_MODE', value: 'azure' }
  { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
  { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryEndpoint }
  { name: 'FOUNDRY_MODEL_FAST', value: fastModelName }
  { name: 'FOUNDRY_MODEL_REASONING', value: reasoningModelName }
  { name: 'EVENTHUB_FQDN', value: '${eventHubs.name}.servicebus.windows.net' }
  { name: 'EVENTHUB_NAME', value: matchEvents.name }
  { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
  { name: 'WEBPUBSUB_ENDPOINT', value: 'https://${webPubSub.properties.hostName}' }
  { name: 'CONTENT_SAFETY_ENDPOINT', value: 'https://${contentSafety.properties.customSubDomainName}.cognitiveservices.azure.com' }
  { name: 'TRANSLATOR_REGION', value: location }
  { name: 'TRANSLATOR_KEY', secretRef: 'translator-key' }
  { name: 'SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
  { name: 'LOGIC_APP_RECAP_URL', secretRef: 'logic-app-url' }
]

var secrets = [
  { name: 'translator-key', value: translator.listKeys().key1 }
  { name: 'logic-app-url', value: listCallbackUrl('${recapLogicApp.id}/triggers/recap', '2019-05-01').value }
]

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-${name}-${token}'
  location: location
  tags: union(tags, { 'azd-service-name': 'app' })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 8000, transport: 'auto', allowInsecure: false }
      registries: [ { server: registry.properties.loginServer, identity: identity.id } ]
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'app'
          image: image
          resources: { cpu: json('2.0'), memory: '4Gi' }
          env: commonEnv
          probes: [
            { type: 'Liveness', httpGet: { path: '/api/health', port: 8000 }, initialDelaySeconds: 20, periodSeconds: 20 }
            { type: 'Readiness', httpGet: { path: '/api/health', port: 8000 }, initialDelaySeconds: 5, periodSeconds: 10 }
          ]
        }
      ]
      // Live sessions are stateful per replica; Web PubSub fans out to all viewers.
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
  dependsOn: [ acrPull ]
}

resource mcp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-${name}-mcp-${token}'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 8765, transport: 'auto' }
      registries: [ { server: registry.properties.loginServer, identity: identity.id } ]
    }
    template: {
      containers: [
        {
          name: 'mcp'
          image: image
          command: [ 'python', '-m', 'touchline.mcp_server', '--http' ]
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [ { name: 'TOUCHLINE_API', value: 'https://${app.properties.configuration.ingress.fqdn}' } ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 3, rules: [ { name: 'http', http: { metadata: { concurrentRequests: '20' } } } ] }
    }
  }
  dependsOn: [ acrPull ]
}

// Container Apps Job: regenerate the 380-match synthetic season on demand.
resource seasonJob 'Microsoft.App/jobs@2024-03-01' = {
  name: 'caj-${name}-season-${token}'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 3600
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [ { server: registry.properties.loginServer, identity: identity.id } ]
    }
    template: {
      containers: [
        {
          name: 'season'
          image: image
          command: [ 'touchline', 'season', '--matchdays', '38' ]
          resources: { cpu: json('4.0'), memory: '8Gi' }
          env: commonEnv
        }
      ]
    }
  }
  dependsOn: [ acrPull ]
}

output registryLoginServer string = registry.properties.loginServer
output appUri string = 'https://${app.properties.configuration.ingress.fqdn}'
output appName string = app.name
output mcpUri string = 'https://${mcp.properties.configuration.ingress.fqdn}/mcp'
output foundryProjectEndpoint string = foundryEndpoint
output eventHubFqdn string = '${eventHubs.name}.servicebus.windows.net'
output cosmosEndpoint string = cosmos.properties.documentEndpoint
