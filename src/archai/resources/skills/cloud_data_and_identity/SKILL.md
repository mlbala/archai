---
name: cloud-data-and-identity
version: 2.1.0
---
Choose services from access patterns and preserve trust, region, tenant, and identity boundaries.

- Profiles: azure-aca = APIM + Container Apps + Service Bus + PostgreSQL/Cosmos DB + one vector
  store + Blob + Key Vault + managed identities + Azure Monitor; azure-aks = the same with AKS,
  KEDA, and workload identity; aws-eks = API Gateway/ALB + EKS + SQS + RDS PostgreSQL + OpenSearch
  Serverless or another managed vector store + S3 + Secrets Manager + Pod Identity + CloudWatch;
  agnostic = portable logical design without vendor-specific resources.
- Data stores: pick by access pattern. The budget ledger needs serializable transactions
  (PostgreSQL); conversation/job state can share that server in a separate database. Object
  storage holds documents; queues carry references, never documents or secrets. Use exactly one
  managed vector store per workload and record embedding dimensions and index versioning.
- For every store specify owner service, partition key (usually tenant), consistency, retention,
  encryption, and backup/recovery.
- Networking: only the enterprise gateway is public; private endpoints for data services; an
  allowlisted egress path to managed AI endpoints; no cross-cloud private link without a design.
- Identity: users via OIDC authorization code + PKCE; services via managed/workload identity and
  client-credentials tokens; on-behalf-of for user-delegated tool calls; no stored secrets.
