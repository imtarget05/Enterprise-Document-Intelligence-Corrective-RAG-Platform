# ADR-0021: Service Boundaries Across 5 Repos

**Date**: 2026-10-22
**Status**: Proposed
**Decision**: Document explicit service boundaries and data ownership across all 5 microservices

## Context

The system consists of 5 repositories that suggest a microservices architecture, but explicit service boundaries and data ownership documentation is lacking. This ADR documents the explicit boundaries to clarify responsibilities, prevent overlap, and enable independent evolution.

## Repo: OpsBridge

| Boundary | Description | Data Ownership |
|----------|-------------|----------------|
| **Inventory/Stock Management** | Stock reservation, concurrency control, oversell prevention | OpsBridge owns stock level and reservation state |
| **Order Management** | Order placement, saga coordination, inventory conservation | OpsBridge owns order state and saga orchestration |
| **Payment Processing** | Payment gate| **Payment Processing** | Payment gate| **Payment Processing** | Payment gaed in current implementation) |
| **Messaging Provider** | RabbitMQ/Azure Service Bus for order events | OpsBridge owns the messaging infrastructure and topic structure |
| **Saga Orchestration** | Checkout saga, status transitions, version token optimistic concurrency | OpsBridge owns saga state and version token management |

**Key ADRs**: ADR-001 through ADR-021 cover concurrency, migration lifecycle, Redis as gatekeeper, async fulfillment, container hardening, migration discipline, disaster recovery, immutable artifacts, RabbitMQ strategy, and more.

**Service Boundary**: OpsBridge is the central orchestrator for inventory and order flow. It owns the `inventory.reserved` -> `inventory.released` compensation pattern and the version token for optimistic concurrency on saga state.

---

## Repo: QuanLyKho

| Boundary | Description | Data Ownership |
|----------|-------------|----------------|
| **Inventory/Stock Management** | Stock tracking, low-stock alerts, inventory reconciliation | QuanLyKho owns stock level and low-stock thresholds |
| **AI/MLflow Components** | ML models, AI inference, analytics | AI components in `ai/` and `airflow/` directories; review needed (G11 gap) |
| **Employee Management** | Employee records, workflows, delivery/acceptance | Employee-app module owns employee data and workflows |
| **Database** | Primary PostgreSQL for transactional core | QuanLyKho owns the PostgreSQL schema and transactional data |

**Key ADRs**: ADR-0001 canonical API FastAPI + Worker proxy deprecation; security deploy checklist; Cloudflare deployment decisions.

**Service Boundary**: QuanLyKho owns inventory and employee management data. AI/MLflow components need review - G11 gap indicates some AI components may not be use-case justified. The repo transitioned from FastAPI sole business API to modular architecture.

---

## Repo: retail-finance-core-platform

| Boundary | Description | Data Ownership |
|----------|-------------|----------------|
| **Finance Core** | Core financial operations, transactions, reconciliation | retail-finance-core-platform owns financial transaction data |
| **Reconciliation Service** | Invoice reconciliation, goods receipt matching | Separate reconciliation-service module handles matching logic |
| **API Gateway** | External API entry point, authentication | API endpoints and gateway configuration |
| **Test Reconciliation Service** | Reconciliation test service for testing | Used for testing purposes |

**Key Issues**: G1-G10 CI gaps - Maven build directory, Testcontainers, Flyway validation, etc.

**Service Boundary**: retail-finance-core-platform owns the finance core domain and transaction data. Reconciliation service is a separate bounded context for invoice/goods receipt matching.

---

## Repo: AKS-SRE-Platform

| Boundary | Description | Data Ownership |
|----------|-------------|----------------|
| **AKS Cluster Management** | Kubernetes cluster, node pools, scaling | AKS-SRE-Platform owns the AKS infrastructure and cluster configuration |
| **GitOps & Overlays** | Kubernetes manifests, GitOps pipelines, ACR integration | AKS-SRE-Platform owns the GitOps pipeline and overlay configurations |
| **Terraform Infrastructure** | Cloud resources, secrets, ingress, external-secrets | Terraform defines AKS, ACR, Azure resources; G12 gap - no CI validate/lint gate |
| **SRE Runbooks** | Incident response, PDB drain, network policies, disaster recovery | AKS-SRE-Platform owns SRE runbooks and operational evidence |

**Key Evidence**: SLI/SLO baselines, PDB drain drills, network policy probes, disaster recovery runbooks.

**Service Boundary**: AKS-SRE-Platform owns the Kubernetes infrastructure, GitOps pipelines, and Terraform-managed cloud resources. Provides the deployment platform for all other repos.

---

## Repo: SmartDocumentChatbot

| Boundary | Description | Data Ownership |
|----------|-------------|----------------|
| **Document Chatbot** | AI-powered document query, RAG, LLM integration | SmartDocumentChatbot owns the chatbot Q&A logic and document indexing |
| **MLflow/AI Components** | MLflow tracking, AI model management | MLflow components present (G11 gap); need review for justification |
| **Langfuse** | Tracing, observability, secret management | LANGFUSE_SECRET_KEY in .env - G4 gap (uncommitted secrets); needs rotation |
| **Frontend UI** | User interface, API integration | Frontend owns the user-facing UI and API client layer |

**Key ADRs**: ADR-0001 security boundaries; ADR-0003 agent fallback strategy; ADR-0004 durable ingestion job queue; ADR-0005 Azure AI Search vs Qdrant; ADR-0006 blob vs R2 storage; ADR-0007 container apps not AKS; ADR-0008 why Service Bus not Kafka; ADR-0009 render preview environments; ADR-0010 SSO deferred.

**Service Boundary**: SmartDocumentChatbot owns the document chatbot domain - AI/QA, document storage integration, and Langfuse observability. Langfuse key rotation is P0 blocking security item.

---
