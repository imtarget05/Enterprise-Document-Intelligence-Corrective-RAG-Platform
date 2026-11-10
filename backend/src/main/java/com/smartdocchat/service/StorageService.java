package com.smartdocchat.service;

import com.azure.core.util.BinaryData;
import com.azure.core.util.Context;
import com.azure.identity.DefaultAzureCredentialBuilder;
import com.azure.storage.blob.BlobClient;
import com.azure.storage.blob.BlobContainerClient;
import com.azure.storage.blob.BlobServiceClientBuilder;
import com.azure.storage.blob.models.BlobHttpHeaders;
import com.azure.storage.blob.options.BlockBlobSimpleUploadOptions;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.core.ResponseBytes;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.*;

import java.io.*;
import java.net.URI;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.EnumSet;

/**
 * StorageService — abstraction over file storage backends.
 *
 * <p>Storage providers are selected by {@code STORAGE_PROVIDER}:
 * <ul>
 *   <li><b>local</b> — writes to {@code uploads/} on the local filesystem (dev/test)</li>
 *   <li><b>blob</b> — Azure Blob Storage using managed identity (production)</li>
 *   <li><b>r2</b> — uploads to Cloudflare R2 (S3-compatible, production, free 10 GB tier,
 *       no egress fees, no 7-day activity requirement)</li>
 *   <li><b>supabase</b> — legacy Supabase Storage via REST API (kept for compatibility)</li>
 * </ul>
 *
 * <p>Cloudflare R2 API docs:
 * <a href="https://developers.cloudflare.com/r2/api/s3/api/">S3 API</a>
 */
@Service
@Slf4j
public class StorageService {

    private final RestTemplate restTemplate;

    @Value("${storage.provider:local}")
    private String provider;

    // ── Supabase config (legacy) ─────────────────────────────────────────────
    @Value("${storage.supabase.url:}")
    private String supabaseUrl;

    @Value("${storage.supabase.bucket:documents}")
    private String supabaseBucket;

    @Value("${storage.supabase.service-key:}")
    private String supabaseServiceKey;

    // ── Cloudflare R2 config ─────────────────────────────────────────────────
    @Value("${storage.r2.account-id:}")
    private String r2AccountId;

    @Value("${storage.r2.access-key-id:}")
    private String r2AccessKeyId;

    @Value("${storage.r2.secret-access-key:}")
    private String r2SecretAccessKey;

    @Value("${storage.r2.bucket:smart-doc-documents}")
    private String r2Bucket;

    @Value("${storage.r2.endpoint:}")
    private String r2Endpoint;

    // ── Azure Blob config ────────────────────────────────────────────────────
    @Value("${storage.azure.account-url:}")
    private String azureStorageAccountUrl;

    @Value("${storage.azure.container:}")
    private String azureStorageContainer;

    @Value("${storage.azure.managed-identity-client-id:}")
    private String azureManagedIdentityClientId;

    // Lazy-initialized S3 client (package-private for test injection)
    S3Client r2Client;

    private volatile BlobContainerClient azureBlobContainerClient;

    // ── Local config ──────────────────────────────────────────────────────────
    @Value("${storage.local.upload-dir:uploads}")
    private String localUploadDir;

    public StorageService(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    // -----------------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------------

    /**
     * Store the given file and return an opaque storage path/key.
     * The returned value must be passed back to {@link #download} and {@link #delete}.
     *
     * @param fileName  final filename (UUID-based, already sanitized)
     * @param file      multipart file from HTTP request
     * @return storage key (local relative path OR R2/Supabase object path)
     */
    public String upload(String fileName, MultipartFile file) throws IOException {
        if ("r2".equalsIgnoreCase(provider)) {
            return uploadToR2(fileName, file.getBytes(), file.getContentType());
        }
        if ("supabase".equalsIgnoreCase(provider)) {
            return uploadToSupabase(fileName, file.getBytes(), file.getContentType());
        }
        if ("blob".equalsIgnoreCase(provider)) {
            return uploadToAzureBlob(fileName, file.getBytes(), file.getContentType());
        }
        if ("local".equalsIgnoreCase(provider)) {
            return uploadToLocal(fileName, file.getBytes());
        }
        throw unsupportedProvider();
    }

    /**
     * Download the file content as a {@link File} for in-process parsing.
     * Callers must delete the temp file when done.
     */
    public File download(String storagePath) throws IOException {
        if ("r2".equalsIgnoreCase(provider)) {
            return downloadFromR2(storagePath);
        }
        if ("supabase".equalsIgnoreCase(provider)) {
            return downloadFromSupabase(storagePath);
        }
        if ("blob".equalsIgnoreCase(provider)) {
            return downloadFromAzureBlob(storagePath);
        }
        if ("local".equalsIgnoreCase(provider)) {
            return downloadFromLocal(storagePath);
        }
        throw unsupportedProvider();
    }

    /**
     * Delete the stored file.
     */
    public void delete(String storagePath) {
        if ("r2".equalsIgnoreCase(provider)) {
            deleteFromR2(storagePath);
        } else if ("supabase".equalsIgnoreCase(provider)) {
            deleteFromSupabase(storagePath);
        } else if ("blob".equalsIgnoreCase(provider)) {
            deleteFromAzureBlob(storagePath);
        } else if ("local".equalsIgnoreCase(provider)) {
            deleteFromLocal(storagePath);
        } else {
            throw unsupportedProvider();
        }
    }

    private IllegalStateException unsupportedProvider() {
        return new IllegalStateException("Unsupported storage provider: " + provider);
    }

    private BlobContainerClient getAzureBlobContainerClient() {
        BlobContainerClient client = azureBlobContainerClient;
        if (client == null) {
            synchronized (this) {
                client = azureBlobContainerClient;
                if (client == null) {
                    if (azureStorageAccountUrl == null || azureStorageAccountUrl.isBlank()
                            || azureStorageContainer == null || azureStorageContainer.isBlank()) {
                        throw new IllegalStateException(
                                "Azure Blob account URL and container must be configured for STORAGE_PROVIDER=blob");
                    }
                    String endpoint = azureStorageAccountUrl.strip().replaceAll("/+$", "");
                    URI endpointUri = URI.create(endpoint);
                    if (!"https".equalsIgnoreCase(endpointUri.getScheme())
                            || endpointUri.getHost() == null
                            || endpointUri.getRawUserInfo() != null
                            || endpointUri.getQuery() != null
                            || endpointUri.getFragment() != null) {
                        throw new IllegalStateException("Azure Blob account URL must be a valid HTTPS endpoint");
                    }

                    DefaultAzureCredentialBuilder credentialBuilder = new DefaultAzureCredentialBuilder();
                    if (azureManagedIdentityClientId != null && !azureManagedIdentityClientId.isBlank()) {
                        credentialBuilder.managedIdentityClientId(azureManagedIdentityClientId);
                    }
                    client = new BlobServiceClientBuilder()
                            .endpoint(endpoint)
                            .credential(credentialBuilder.build())
                            .buildClient()
                            .getBlobContainerClient(azureStorageContainer);
                    azureBlobContainerClient = client;
                }
            }
        }
        return client;
    }

    // -----------------------------------------------------------------------
    // Local filesystem implementation
    // -----------------------------------------------------------------------

    private String uploadToLocal(String fileName, byte[] bytes) throws IOException {
        Path dir = Paths.get(localUploadDir);
        Files.createDirectories(dir);
        Path target = dir.resolve(fileName);
        Files.write(target, bytes);
        log.info("Saved file locally: {}", target);
        return target.toString();
    }

    private File downloadFromLocal(String storagePath) {
        return new File(storagePath);
    }

    private void deleteFromLocal(String storagePath) {
        try {
            Files.deleteIfExists(Paths.get(storagePath));
            log.info("Deleted local file: {}", storagePath);
        } catch (IOException e) {
            log.error("Failed to delete local file: {}", storagePath, e);
        }
    }

    // -----------------------------------------------------------------------
    // Cloudflare R2 (S3-compatible) implementation
    // -----------------------------------------------------------------------

    /**
     * Lazily build the S3 client pointed at Cloudflare R2. R2 is S3-compatible,
     * so the standard AWS SDK works with an endpoint override:
     * https://&lt;account_id&gt;.r2.cloudflarestorage.com
     */
    S3Client getR2Client() {
        if (r2Client == null) {
            String endpoint = r2Endpoint;
            if (endpoint == null || endpoint.isBlank()) {
                endpoint = "https://" + r2AccountId + ".r2.cloudflarestorage.com";
            }
            r2Client = S3Client.builder()
                    .region(Region.US_EAST_1)
                    .endpointOverride(URI.create(endpoint))
                    .credentialsProvider(StaticCredentialsProvider.create(
                            AwsBasicCredentials.create(r2AccessKeyId, r2SecretAccessKey)))
                    .build();
        }
        return r2Client;
    }

    /**
     * Upload object to Cloudflare R2.
     * PUT /{bucket}/{fileName}
     *
     * @return R2 object key (e.g. "uuid.pdf")
     */
    private String uploadToR2(String fileName, byte[] bytes, String contentType) {
        String objectKey = fileName;
        try {
            PutObjectRequest.Builder requestBuilder = PutObjectRequest.builder()
                    .bucket(r2Bucket)
                    .key(objectKey);
            if (contentType != null && !contentType.isBlank()) {
                requestBuilder = requestBuilder.contentType(contentType);
            }
            getR2Client().putObject(requestBuilder.build(), RequestBody.fromBytes(bytes));
            log.info("Uploaded to Cloudflare R2: {}", objectKey);
            return objectKey;
        } catch (Exception e) {
            log.error("Error uploading to Cloudflare R2: {}", e.getMessage(), e);
            throw new RuntimeException("Storage upload failed", e);
        }
    }

    private String uploadToAzureBlob(String fileName, byte[] bytes, String contentType) {
        try {
            BlobClient blobClient = getAzureBlobContainerClient().getBlobClient(fileName);
            if (contentType != null && !contentType.isBlank()) {
                BlockBlobSimpleUploadOptions options = new BlockBlobSimpleUploadOptions(BinaryData.fromBytes(bytes))
                        .setHeaders(new BlobHttpHeaders().setContentType(contentType));
                blobClient.getBlockBlobClient().uploadWithResponse(options, null, Context.NONE);
            } else {
                blobClient.getBlockBlobClient().upload(BinaryData.fromBytes(bytes), true);
            }
            log.info("Uploaded document to Azure Blob Storage");
            return fileName;
        } catch (RuntimeException e) {
            log.error("Azure Blob upload failed", e);
            throw new RuntimeException("Storage upload failed", e);
        }
    }

    private File downloadFromAzureBlob(String objectKey) throws IOException {
        String extension = objectKey.contains(".") ? objectKey.substring(objectKey.lastIndexOf('.')) : ".tmp";
        Path tempPath = Files.createTempFile(
                Path.of(System.getProperty("java.io.tmpdir")),
                "sdc_download_", extension,
                PosixFilePermissions.asFileAttribute(
                        EnumSet.of(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE)));
        try {
            getAzureBlobContainerClient().getBlobClient(objectKey).downloadToFile(tempPath.toString(), true);
            tempPath.toFile().deleteOnExit();
            return tempPath.toFile();
        } catch (RuntimeException e) {
            try {
                Files.deleteIfExists(tempPath);
            } catch (IOException cleanupException) {
                e.addSuppressed(cleanupException);
            }
            log.error("Azure Blob download failed", e);
            throw new IOException("Storage download failed", e);
        }
    }

    private void deleteFromAzureBlob(String objectKey) {
        try {
            getAzureBlobContainerClient().getBlobClient(objectKey).deleteIfExists();
            log.info("Deleted document from Azure Blob Storage");
        } catch (RuntimeException e) {
            log.error("Azure Blob delete failed", e);
            throw new RuntimeException("Storage delete failed", e);
        }
    }

    /**
     * Download object from Cloudflare R2 to a temp file.
     * GET /{bucket}/{key}
     */
    private File downloadFromR2(String objectKey) throws IOException {
        try {
            ResponseBytes<GetObjectResponse> objectBytes = getR2Client().getObjectAsBytes(
                    GetObjectRequest.builder()
                            .bucket(r2Bucket)
                            .key(objectKey)
                            .build());
            String extension = objectKey.contains(".") ? objectKey.substring(objectKey.lastIndexOf('.')) : ".tmp";
            Path tempPath = Files.createTempFile(
                    Path.of(System.getProperty("java.io.tmpdir")),
                    "sdc_download_", extension,
                    PosixFilePermissions.asFileAttribute(
                            EnumSet.of(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE)));
            File tempFile = tempPath.toFile();
            tempFile.deleteOnExit();
            Files.write(tempPath, objectBytes.asByteArray());
            log.info("Downloaded {} bytes from Cloudflare R2: {}", objectBytes.asByteArray().length, objectKey);
            return tempFile;
        } catch (IOException e) {
            log.error("Error downloading from Cloudflare R2: {}", e.getMessage(), e);
            throw e;
        } catch (Exception e) {
            log.error("Error downloading from Cloudflare R2: {}", e.getMessage(), e);
            throw new IOException("Storage download failed: " + e.getMessage(), e);
        }
    }

    /**
     * Delete object from Cloudflare R2.
     * DELETE /{bucket}/{key}
     */
    private void deleteFromR2(String objectKey) {
        try {
            getR2Client().deleteObject(DeleteObjectRequest.builder()
                    .bucket(r2Bucket)
                    .key(objectKey)
                    .build());
            log.info("Deleted from Cloudflare R2: {}", objectKey);
        } catch (Exception e) {
            log.error("Error deleting from Cloudflare R2: {}", e.getMessage(), e);
        }
    }

    // -----------------------------------------------------------------------
    // Supabase Storage REST API implementation (legacy)
    // -----------------------------------------------------------------------

    /**
     * Upload object to Supabase Storage.
     * POST /storage/v1/object/{bucket}/{fileName}
     *
     * @return Supabase object path (e.g. "documents/uuid.pdf")
     */
    private String uploadToSupabase(String fileName, byte[] bytes, String contentType) {
        String objectPath = supabaseBucket + "/" + fileName;
        String url = supabaseUrl + "/storage/v1/object/" + objectPath;

        HttpHeaders headers = buildSupabaseHeaders();
        headers.setContentType(
                contentType != null ? MediaType.parseMediaType(contentType) : MediaType.APPLICATION_OCTET_STREAM
        );

        HttpEntity<byte[]> entity = new HttpEntity<>(bytes, headers);

        try {
            ResponseEntity<String> response = restTemplate.exchange(url, HttpMethod.POST, entity, String.class);
            if (response.getStatusCode().is2xxSuccessful()) {
                log.info("Uploaded to Supabase Storage: {}", objectPath);
                return objectPath;
            }
            throw new IOException("Supabase upload failed: " + response.getStatusCode());
        } catch (Exception e) {
            log.error("Error uploading to Supabase: {}", e.getMessage(), e);
            throw new RuntimeException("Storage upload failed", e);
        }
    }

    /**
     * Download object from Supabase Storage to a temp file.
     * GET /storage/v1/object/{objectPath}
     */
    private File downloadFromSupabase(String objectPath) throws IOException {
        String url = supabaseUrl + "/storage/v1/object/" + objectPath;

        HttpHeaders headers = buildSupabaseHeaders();
        HttpEntity<Void> entity = new HttpEntity<>(headers);

        try {
            ResponseEntity<byte[]> response = restTemplate.exchange(url, HttpMethod.GET, entity, byte[].class);
            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                // Write to a temp file so existing parsers (PDFBox, POI) can read it
                String extension = objectPath.contains(".") ? objectPath.substring(objectPath.lastIndexOf('.')) : ".tmp";
                Path tempPath = Files.createTempFile(
                        Path.of(System.getProperty("java.io.tmpdir")),
                        "sdc_download_", extension,
                        PosixFilePermissions.asFileAttribute(
                                EnumSet.of(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE)));
                File tempFile = tempPath.toFile();
                tempFile.deleteOnExit();
                Files.write(tempPath, response.getBody());
                log.info("Downloaded {} bytes from Supabase: {}", response.getBody().length, objectPath);
                return tempFile;
            }
            throw new IOException("Supabase download returned: " + response.getStatusCode());
        } catch (Exception e) {
            log.error("Error downloading from Supabase: {}", e.getMessage(), e);
            throw new IOException("Storage download failed: " + e.getMessage(), e);
        }
    }

    /**
     * Delete object from Supabase Storage.
     * DELETE /storage/v1/object/{bucket}?prefixes={fileName}
     */
    private void deleteFromSupabase(String objectPath) {
        // objectPath = "documents/uuid.pdf" — extract just the filename part
        String fileName = objectPath.contains("/") ? objectPath.substring(objectPath.indexOf('/') + 1) : objectPath;
        String url = supabaseUrl + "/storage/v1/object/" + supabaseBucket + "?prefixes=" + fileName;

        HttpHeaders headers = buildSupabaseHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        // Supabase delete requires body with "prefixes" array
        String body = "{\"prefixes\":[\"" + fileName + "\"]}";
        HttpEntity<String> entity = new HttpEntity<>(body, headers);

        try {
            restTemplate.exchange(url, HttpMethod.DELETE, entity, String.class);
            log.info("Deleted from Supabase Storage: {}", objectPath);
        } catch (Exception e) {
            log.error("Error deleting from Supabase: {}", e.getMessage(), e);
        }
    }

    private HttpHeaders buildSupabaseHeaders() {
        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "Bearer " + supabaseServiceKey);
        headers.set("apikey", supabaseServiceKey);
        return headers;
    }
}