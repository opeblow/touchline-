// Touchline — Azure infrastructure (azd up).
targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('azd environment name, used to name resources')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

@description('Deploy a Microsoft Foundry account + project with model deployments')
param deployFoundry bool = true

@description('Fast model (explain, narrate, personalise)')
param fastModelName string = 'gpt-4.1-mini'
param fastModelVersion string = '2025-04-14'

@description('Reasoning model (tactics, recaps)')
param reasoningModelName string = 'gpt-4.1'
param reasoningModelVersion string = '2025-04-14'

@description('Optional Microsoft Teams incoming-webhook URL for full-time recaps (Logic App)')
@secure()
param teamsWebhookUrl string = ''

@description('Container image for the app (set by azd deploy)')
param appImage string = ''

var tags = { 'azd-env-name': environmentName, app: 'touchline' }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'touchline-resources'
  scope: rg
  params: {
    location: location
    tags: tags
    environmentName: environmentName
    deployFoundry: deployFoundry
    fastModelName: fastModelName
    fastModelVersion: fastModelVersion
    reasoningModelName: reasoningModelName
    reasoningModelVersion: reasoningModelVersion
    teamsWebhookUrl: teamsWebhookUrl
    appImage: appImage
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.registryLoginServer
output SERVICE_APP_URI string = resources.outputs.appUri
output SERVICE_APP_NAME string = resources.outputs.appName
output FOUNDRY_PROJECT_ENDPOINT string = resources.outputs.foundryProjectEndpoint
output EVENTHUB_FQDN string = resources.outputs.eventHubFqdn
output COSMOS_ENDPOINT string = resources.outputs.cosmosEndpoint
output MCP_URI string = resources.outputs.mcpUri
