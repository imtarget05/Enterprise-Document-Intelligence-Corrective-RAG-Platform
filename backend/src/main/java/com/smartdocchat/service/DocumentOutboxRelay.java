package com.smartdocchat.service;

import com.smartdocchat.repository.DocumentOutboxRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import java.time.LocalDateTime;

@Service @RequiredArgsConstructor
@ConditionalOnProperty(name="ingestion.mode", havingValue="kafka", matchIfMissing=true)
public class DocumentOutboxRelay {
    private final DocumentOutboxRepository repository;
    private final com.smartdocchat.repository.DocumentRepository documents;
    private final DocumentIngestionOutbox outbox;
    @Scheduled(fixedDelayString="${ingestion.outbox.poll-ms:5000}")
    public void relay() {
        for (Long id : documents.findMissingIngestionEvents(PageRequest.of(0,10))) outbox.reconcileOne(id);
        for (String id : repository.findDueIds(LocalDateTime.now(), PageRequest.of(0, 10))) outbox.publishOne(id);
    }
}
