---
name: cloud-data-and-identity
version: 2.2.0
---
Choose services from access patterns and preserve trust, region, tenant, and identity boundaries.

Profiles, use these managed building blocks and no others unless the requirements name one:

- `azure-aca`: API Management, Container Apps, Service Bus, PostgreSQL or Cosmos DB for the
  transactional workload, one vector store when retrieval exists, Blob, Key Vault, managed
  identities, Azure Monitor.
- `azure-aks`: the same data and identity plane, with AKS, KEDA, and workload identity
  instead of Container Apps scale rules.
- `aws-eks`: API Gateway or ALB, EKS, SQS, RDS PostgreSQL, OpenSearch Serverless or another
  managed vector store, S3, Secrets Manager, Pod Identity, CloudWatch.
- `agnostic`: portable roles (public gateway, private compute, relational store, object
  store, queue, secret store, vector index, identity provider) and no vendor SKU.

Data stores follow the access pattern:

- Budget ledger and any entitlement or approval record: relational, serializable. Redis or
  an in-memory counter is rate limiting, not the ledger.
- Conversation and job state: the same relational server is acceptable in a separate database
  when the access is read-your-writes by job or conversation id.
- Documents and artifacts: object storage. Queue messages hold a tenant id, a job id, and an
  object reference. They do not hold document bytes, prompts, or secrets.
- Vectors: exactly one managed index per workload. Record embedding dimensions, similarity,
  and that a model or dimension change creates a new index version and a reindex. Do not
  point two embedding models at one index.
- Partition by tenant when isolation is `multi`. Still store the organization key when
  isolation is `single`, so a later split does not rewrite the schema. Add a finer key only
  when one tenant's hot partition would dominate.
- Encryption at rest with the platform key store, backups that can meet the stated RPO, and
  retention that follows classification and the named compliance regimes. Region must be
  inside `data_residency`.

Networking: only the enterprise gateway is public. Data services use private endpoints.
Egress to managed model endpoints is an allowlisted path. No cross-cloud private link
unless the topology and the requirements describe one.

Identity, when you are designing it: users via OIDC authorization code and PKCE; services
via managed or workload identity and client-credentials tokens; on-behalf-of for
user-delegated tool calls; no stored client secrets on the hot path. Tenant comes from
the token, not the body.

Lessons from design reviews:

- Every `depends_on` edge needs a matching grant on the caller's identity. ArchAI adds a
  baseline grant per edge; write the specific permission when the call needs more than that.
- The identity type fits the platform: managed API gateways use their own resource policies or
  managed identities, not the identity type of the container workloads behind them.
- Permission to read a document comes from the system that owns its access list; a related
  record in another system is not that permission.
