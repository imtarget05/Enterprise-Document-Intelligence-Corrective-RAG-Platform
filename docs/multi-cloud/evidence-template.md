# Multi-Cloud Evidence — SmartDoc (Azure)

Mục tiêu: chứng minh khả năng triển khai workload lên Azure qua Terraform.

## 1. Thông tin Azure CLI

| Mục | Giá trị |
|-----|---------|
| Subscription | Azure subscription 1 (`a3deec78-7edb-41cd-9e94-ec1d4d9379f5`) |
| Tenant | `aa79a92c-ec09-4de1-baa9-151b8f9df886` (`binhtan5734gmail.onmicrosoft.com`) |
| User | `binhtan5734@gmail.com` |
| Azure CLI | 2.90.0 |

## 2. Infrastructure đã tạo trên Azure

| Resource | Tên | Vùng | Trạng thái |
|----------|-----|------|------------|
| Resource Group | `rg-smartdoc-prod` | eastus | Succeeded |
| Virtual Network | `smartdoc-vnet-l9quzq` | eastus | Succeeded |
| Subnet (container apps) | `container-apps` | eastus | Succeeded |
| Subnet (private endpoints) | `private-endpoints` | eastus | Succeeded |
| Log Analytics | `smartdoc-law-l9quzq` | eastus | Succeeded |
| Azure AI Search | `smartdoc-search-l9quzq` | eastus | Succeeded |
| Storage Account | `stsmartdocl9quzq` | eastus | Succeeded |
| Service Bus Namespace | `smartdoc-sb-l9quzq` | eastus | Succeeded |
| User Assigned Identity | `smartdoc-uai` | eastus | Succeeded |
| Private DNS Zone | `privatelink.blob.core.windows.net` | global | Succeeded |
| Private DNS Zone Link | `smartdoc-storage-blob` | global | Succeeded |

## 3. Các vấn đề gặp phải

| Vấn đề | Nguyên nhân | Hành động |
|--------|-------------|-----------|
| Container App Environment | `MaxNumberOfGlobalEnvironmentsInSubExceeded` - subscription chỉ cho phép tối đa 2 CAE | Không thể tạo CAE trên subscription này. Cần xóa CAE cũ hoặc đăng ký quota increase. |
| Storage Account key auth | `KeyBasedAuthenticationNotPermitted` - storage account không cho phép key-based auth | Cần dùng managed identity hoặc Azure AD auth thay vì access key |
| Service Bus Queue | Tạo bị hủy do Container App Environment lỗi | Sẽ tạo sau khi CAE vấn đề được giải quyết |

## 4. Evidence files

| File | Mô tả |
|------|-------|
| `docs/evidence/azure-resources-2026-11-14.json` | Danh sách tất cả resource trong RG `rg-smartdoc-prod` |

## 5. Cách lấy thêm evidence

```bash
# Resource group info
az group show --resource-group rg-smartdoc-prod

# All resources in RG
az resource list --resource-group rg-smartdoc-prod --output table

# Storage account info
az storage account show --resource-group rg-smartdoc-prod --name stsmartdocl9quzq

# Service Bus namespace
az servicebus namespace show --resource-group rg-smartdoc-prod --name smartdoc-sb-l9quzq

# Azure AI Search
az search service show --resource-group rg-smartdoc-prod --name smartdoc-search-l9quzq
```

## 6. Multi-cloud (AWS/GCP)

Cần cấu hình credentials AWS/GCP nếu muốn chứng minh multi-cloud. Hiện chỉ chạy trên Azure.