package com.smartdocchat.repository;

import com.smartdocchat.entity.DocumentIngestionJob;
import com.smartdocchat.entity.DocumentIngestionJob.JobStatus;
import jakarta.persistence.LockModeType;
import jakarta.persistence.QueryHint;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.QueryHints;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.util.Collection;
import java.util.List;

@Repository
public interface DocumentIngestionJobRepository extends JpaRepository<DocumentIngestionJob, Long> {

    /**
     * Claimable jobs (PENDING and due), row-locked with SKIP LOCKED
     * (Hibernate maps lock timeout -2 to SKIP LOCKED) so two workers can never
     * claim the same row when the backend scales horizontally. The lock is held
     * only for the short claim transaction — processing happens outside it.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @QueryHints(@QueryHint(name = "jakarta.persistence.lock.timeout", value = "-2"))
    @Query("SELECT j FROM DocumentIngestionJob j " +
            "WHERE j.status = 'PENDING' AND j.nextRunAt <= CURRENT_TIMESTAMP ORDER BY j.id")
    List<DocumentIngestionJob> findClaimable(Pageable pageable);

    /** True when the document already has an active (PENDING/RUNNING) job of this type. */
    boolean existsByDocumentIdAndJobTypeAndStatusIn(Long documentId, String jobType, Collection<JobStatus> statuses);

    Page<DocumentIngestionJob> findByStatus(JobStatus status, Pageable pageable);

    java.util.Optional<DocumentIngestionJob> findFirstByDocumentIdOrderByIdDesc(Long documentId);

    /**
     * Crash recovery (lease timeout): RUNNING rows that were claimed but whose
     * worker died before completing are handed back to the queue. The poller
     * runs this every tick so no job is ever stuck in RUNNING forever.
     *
     * Owns its own short transaction so the @Scheduled poller stays
     * non-transactional and never holds a pooled connection idle while the
     * batch executor runs long workflow jobs.
     */
    @Transactional
    @Modifying(clearAutomatically = true)
    @Query(value = "UPDATE document_ingestion_jobs SET status = 'PENDING', updated_at = now() " +
            "WHERE status = 'RUNNING' AND updated_at < now() - (:staleMinutes * interval '1 minute')",
            nativeQuery = true)
    int requeueStaleRunningJobs(@Param("staleMinutes") long staleMinutes);
}
