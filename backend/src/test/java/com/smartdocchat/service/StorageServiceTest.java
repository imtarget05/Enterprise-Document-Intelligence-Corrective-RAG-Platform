package com.smartdocchat.service;

import com.azure.core.util.BinaryData;
import com.azure.storage.blob.BlobClient;
import com.azure.storage.blob.BlobContainerClient;
import com.azure.storage.blob.options.BlockBlobSimpleUploadOptions;
import com.azure.storage.blob.specialized.BlockBlobClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;
import software.amazon.awssdk.core.ResponseBytes;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.DeleteObjectRequest;
import software.amazon.awssdk.services.s3.model.DeleteObjectResponse;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectResponse;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.s3.model.PutObjectResponse;
import software.amazon.awssdk.services.s3.model.S3Exception;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class StorageServiceTest {

    @Mock private RestTemplate restTemplate;

    private StorageService storageService;

    @BeforeEach
    void setUp() {
        storageService = new StorageService(restTemplate);
        ReflectionTestUtils.setField(storageService, "provider", "local");
    }

    @Test
    void localUploadDownloadDeleteCycle(@org.junit.jupiter.api.io.TempDir Path tempDir) throws Exception {
        ReflectionTestUtils.setField(storageService, "localUploadDir", tempDir.toString());

        MockMultipartFile file = new MockMultipartFile(
                "file", "doc.txt", "text/plain", "content".getBytes(StandardCharsets.UTF_8));
        String path = storageService.upload("doc.txt", file);

        assertTrue(path.contains("doc.txt"));
        assertTrue(Files.exists(Path.of(path)));

        File downloaded = storageService.download(path);
        assertEquals("content", new String(Files.readAllBytes(downloaded.toPath()), StandardCharsets.UTF_8));

        storageService.delete(path);
        assertTrue(!Files.exists(Path.of(path)));
        storageService.delete(path);
    }

    @Test
    void supabaseUploadBuildsObjectPath() throws Exception {
        ReflectionTestUtils.setField(storageService, "provider", "supabase");
        ReflectionTestUtils.setField(storageService, "supabaseUrl", "https://xyz.supabase.co");
        ReflectionTestUtils.setField(storageService, "supabaseBucket", "documents");
        ReflectionTestUtils.setField(storageService, "supabaseServiceKey", "service-key");

        when(restTemplate.exchange(eq("https://xyz.supabase.co/storage/v1/object/documents/uuid.pdf"),
                eq(HttpMethod.POST), any(), eq(String.class)))
                .thenReturn(ResponseEntity.ok("{}"));

        MockMultipartFile file = new MockMultipartFile(
                "file", "doc.pdf", "application/pdf", "content".getBytes());
        assertEquals("documents/uuid.pdf", storageService.upload("uuid.pdf", file));
    }

    @Test
    void supabaseUploadThrowsOnFailureOrException() {
        ReflectionTestUtils.setField(storageService, "provider", "supabase");
        ReflectionTestUtils.setField(storageService, "supabaseUrl", "https://xyz.supabase.co");
        ReflectionTestUtils.setField(storageService, "supabaseBucket", "documents");

        when(restTemplate.exchange(any(String.class), eq(HttpMethod.POST), any(), eq(String.class)))
                .thenReturn(ResponseEntity.status(HttpStatus.BAD_REQUEST).body("{}"));
        MockMultipartFile file = new MockMultipartFile("file", "doc.pdf", "application/pdf", "c".getBytes());
        assertThrows(RuntimeException.class, () -> storageService.upload("uuid.pdf", file));
    }

    @Test
    void supabaseDownloadWritesTempFileWithOwnerOnlyPermissions() throws Exception {
        ReflectionTestUtils.setField(storageService, "provider", "supabase");
        ReflectionTestUtils.setField(storageService, "supabaseUrl", "https://xyz.supabase.co");
        ReflectionTestUtils.setField(storageService, "supabaseBucket", "documents");
        ReflectionTestUtils.setField(storageService, "supabaseServiceKey", "k");

        when(restTemplate.exchange(eq("https://xyz.supabase.co/storage/v1/object/documents/uuid.pdf"),
                eq(HttpMethod.GET), any(), eq(byte[].class)))
                .thenReturn(ResponseEntity.ok("bytes".getBytes(StandardCharsets.UTF_8)));

        File file = storageService.download("documents/uuid.pdf");

        assertTrue(file.getName().contains("sdc_download_"));
        assertEquals("bytes", new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8));
    }

    @Test
    void supabaseDownloadThrowsOnNon2xx() {
        ReflectionTestUtils.setField(storageService, "provider", "supabase");
        ReflectionTestUtils.setField(storageService, "supabaseUrl", "https://xyz.supabase.co");
        ReflectionTestUtils.setField(storageService, "supabaseBucket", "documents");

        when(restTemplate.exchange(any(String.class), eq(HttpMethod.GET), any(), eq(byte[].class)))
                .thenReturn(ResponseEntity.status(HttpStatus.NOT_FOUND).body(null));

        assertThrows(java.io.IOException.class, () -> storageService.download("documents/uuid.pdf"));
    }

    @Test
    void supabaseDeleteSendsPrefixedRequestAndSwallowsErrors() {
        ReflectionTestUtils.setField(storageService, "provider", "supabase");
        ReflectionTestUtils.setField(storageService, "supabaseUrl", "https://xyz.supabase.co");
        ReflectionTestUtils.setField(storageService, "supabaseBucket", "documents");

        doThrow(new RuntimeException("gone")).when(restTemplate)
                .exchange(any(String.class), eq(HttpMethod.DELETE), any(), eq(String.class));
        storageService.delete("documents2/uuid.pdf");

        verify(restTemplate).exchange(eq("https://xyz.supabase.co/storage/v1/object/documents?prefixes=uuid.pdf"),
                eq(HttpMethod.DELETE), any(), eq(String.class));
    }

    // -----------------------------------------------------------------------
    // Cloudflare R2 provider tests
    // -----------------------------------------------------------------------

    private void setUpR2Provider(S3Client client) {
        ReflectionTestUtils.setField(storageService, "provider", "r2");
        ReflectionTestUtils.setField(storageService, "r2AccountId", "acct1");
        ReflectionTestUtils.setField(storageService, "r2Bucket", "docs");
        storageService.r2Client = client;
    }

    @Test
    void r2UploadUsesGivenBucketAndKey() throws Exception {
        S3Client client = mock(S3Client.class);
        when(client.putObject(any(PutObjectRequest.class), any(RequestBody.class)))
                .thenReturn(PutObjectResponse.builder().build());
        setUpR2Provider(client);

        MockMultipartFile file = new MockMultipartFile(
                "file", "uuid.pdf", "application/pdf", "content".getBytes());
        assertEquals("uuid.pdf", storageService.upload("uuid.pdf", file));

        ArgumentCaptor<PutObjectRequest> captor = ArgumentCaptor.forClass(PutObjectRequest.class);
        verify(client).putObject(captor.capture(), any(RequestBody.class));
        assertEquals("docs", captor.getValue().bucket());
        assertEquals("uuid.pdf", captor.getValue().key());
        assertEquals("application/pdf", captor.getValue().contentType());
    }

    @Test
    void r2UploadWrapsClientFailureInRuntimeException() {
        S3Client client = mock(S3Client.class);
        when(client.putObject(any(PutObjectRequest.class), any(RequestBody.class)))
                .thenThrow(S3Exception.builder().message("boom").build());
        setUpR2Provider(client);
        storageService.r2Client = client;

        MockMultipartFile file = new MockMultipartFile("file", "a.pdf", "application/pdf", "c".getBytes());
        assertThrows(RuntimeException.class, () -> storageService.upload("a.pdf", file));
    }

    @Test
    void r2DownloadWritesTempFileWithOwnerOnlyPermissions() throws Exception {
        S3Client client = mock(S3Client.class);
        ResponseBytes<GetObjectResponse> bytes = ResponseBytes.fromByteArray(
                GetObjectResponse.builder().build(), "bytes".getBytes(StandardCharsets.UTF_8));
        when(client.getObjectAsBytes(any(GetObjectRequest.class))).thenReturn(bytes);
        setUpR2Provider(client);

        File file = storageService.download("uuid.pdf");

        assertTrue(file.getName().contains("sdc_download_"));
        assertEquals("bytes", new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8));
    }

    @Test
    void r2DownloadThrowsIOExceptionOnClientFailure() {
        S3Client client = mock(S3Client.class);
        when(client.getObjectAsBytes(any(GetObjectRequest.class)))
                .thenThrow(S3Exception.builder().message("not found").build());
        setUpR2Provider(client);

        assertThrows(IOException.class, () -> storageService.download("missing.pdf"));
    }

    @Test
    void r2DeleteSendsRequestAndSwallowsErrors() {
        S3Client client = mock(S3Client.class);
        when(client.deleteObject(any(DeleteObjectRequest.class)))
                .thenReturn(DeleteObjectResponse.builder().build());
        setUpR2Provider(client);

        storageService.delete("uuid.pdf");

        ArgumentCaptor<DeleteObjectRequest> captor = ArgumentCaptor.forClass(DeleteObjectRequest.class);
        verify(client).deleteObject(captor.capture());
        assertEquals("docs", captor.getValue().bucket());
        assertEquals("uuid.pdf", captor.getValue().key());
    }

    // -----------------------------------------------------------------------
    // Azure Blob provider tests
    // -----------------------------------------------------------------------

    private BlobClient setUpAzureBlobProvider() {
        BlobContainerClient containerClient = mock(BlobContainerClient.class);
        BlobClient blobClient = mock(BlobClient.class);
        when(containerClient.getBlobClient(any(String.class))).thenReturn(blobClient);
        ReflectionTestUtils.setField(storageService, "provider", "blob");
        ReflectionTestUtils.setField(storageService, "azureBlobContainerClient", containerClient);
        return blobClient;
    }

    @Test
    void azureBlobUploadUsesOpaqueKeyAndContentType() throws Exception {
        BlobClient blobClient = setUpAzureBlobProvider();
        BlockBlobClient blockBlobClient = mock(BlockBlobClient.class);
        when(blobClient.getBlockBlobClient()).thenReturn(blockBlobClient);
        MockMultipartFile file = new MockMultipartFile(
                "file", "uuid.pdf", "application/pdf", "content".getBytes(StandardCharsets.UTF_8));

        assertEquals("uuid.pdf", storageService.upload("uuid.pdf", file));

        ArgumentCaptor<BlockBlobSimpleUploadOptions> optionsCaptor =
                ArgumentCaptor.forClass(BlockBlobSimpleUploadOptions.class);
        verify(blockBlobClient).uploadWithResponse(optionsCaptor.capture(), eq(null), any());
        assertEquals("content",
                new String(optionsCaptor.getValue().getData().toBytes(), StandardCharsets.UTF_8));
        assertEquals("application/pdf", optionsCaptor.getValue().getHeaders().getContentType());
    }

    @Test
    void azureBlobDownloadWritesTempFile() throws Exception {
        BlobClient blobClient = setUpAzureBlobProvider();
        org.mockito.Mockito.doAnswer(invocation -> {
            Files.write(Path.of((String) invocation.getArgument(0)),
                    "bytes".getBytes(StandardCharsets.UTF_8));
            return null;
        }).when(blobClient).downloadToFile(any(String.class), eq(true));

        File file = storageService.download("uuid.pdf");
        try {
            assertTrue(file.getName().contains("sdc_download_"));
            assertEquals("bytes", new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8));
        } finally {
            Files.deleteIfExists(file.toPath());
        }
    }

    @Test
    void azureBlobDownloadSurfacesClientFailureAsIOException() {
        BlobClient blobClient = setUpAzureBlobProvider();
        doThrow(new RuntimeException("not found"))
                .when(blobClient).downloadToFile(any(String.class), eq(true));

        assertThrows(IOException.class, () -> storageService.download("missing.pdf"));
    }

    @Test
    void azureBlobDeleteUsesIdempotentDelete() {
        BlobClient blobClient = setUpAzureBlobProvider();

        storageService.delete("uuid.pdf");

        verify(blobClient).deleteIfExists();
    }

    @Test
    void azureBlobDeleteSurfacesClientFailure() {
        BlobClient blobClient = setUpAzureBlobProvider();
        doThrow(new RuntimeException("storage unavailable")).when(blobClient).deleteIfExists();

        assertThrows(RuntimeException.class, () -> storageService.delete("uuid.pdf"));
    }

    @Test
    void blobProviderWithMissingConfigurationDoesNotWriteToLocalStorage(@org.junit.jupiter.api.io.TempDir Path tempDir) {
        ReflectionTestUtils.setField(storageService, "provider", "blob");
        ReflectionTestUtils.setField(storageService, "localUploadDir", tempDir.toString());
        MockMultipartFile file = new MockMultipartFile(
                "file", "uuid.pdf", "application/pdf", "content".getBytes(StandardCharsets.UTF_8));

        assertThrows(RuntimeException.class, () -> storageService.upload("uuid.pdf", file));
        assertTrue(isDirectoryEmpty(tempDir));
    }

    @Test
    void unsupportedProviderFailsClosed() {
        ReflectionTestUtils.setField(storageService, "provider", "typo");
        MockMultipartFile file = new MockMultipartFile(
                "file", "uuid.pdf", "application/pdf", "content".getBytes(StandardCharsets.UTF_8));

        assertThrows(IllegalStateException.class, () -> storageService.upload("uuid.pdf", file));
    }

    private boolean isDirectoryEmpty(Path path) {
        try (var files = Files.list(path)) {
            return files.findAny().isEmpty();
        } catch (IOException e) {
            throw new IllegalStateException(e);
        }
    }
}