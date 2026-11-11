package com.smartdocchat.repository;

import com.smartdocchat.entity.DocumentOutbox;
import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.*;
import org.springframework.data.repository.query.Param;
import org.springframework.data.domain.Pageable;
import java.time.LocalDateTime;
import java.util.*;

public interface DocumentOutboxRepository extends JpaRepository<DocumentOutbox, String> {
    boolean existsByDocumentIdAndDocumentVersion(Long documentId, Integer documentVersion);
    @Query("select o.id from DocumentOutbox o where o.status = 'PENDING' and o.nextAttemptAt <= :now order by o.nextAttemptAt")
    List<String> findDueIds(@Param("now") LocalDateTime now, Pageable page);
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select o from DocumentOutbox o where o.id = :id")
    Optional<DocumentOutbox> lockById(@Param("id") String id);
}
