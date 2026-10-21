package com.smartdocchat.service;

import com.smartdocchat.cache.CacheNames;
import com.smartdocchat.cache.SearchResultCache;
import com.smartdocchat.entity.LegalChunk;
import com.smartdocchat.repository.LegalChunkRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Callable;

/**
 * Scored retrieval over the chunks stored in PostgreSQL.
 *
 * This is the equivalent of the agent-service Qdrant retrieval for the classic
 * Java Chat endpoints. Each chunk receives a deterministic lexical score in the
 * [0,1] range (word coverage + frequency saturation). The best score becomes the
 * CRAG "confidence" value; low confidence triggers query reformulation/fallback.
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class RetrievalService {

    /**
     * A retrieved chunk together with its normalised similarity score (0..1).
     * Legal citation metadata is present only for documents ingested with
     * detectable legal structure; it is null — never fabricated — otherwise.
     */
    public record RetrievalResult(String chunk, double score, Long chunkId,
                                  String article, String clause, String point) {
        /** Legacy-compatible constructor for unstructured chunks. */
        public RetrievalResult(String chunk, double score) {
            this(chunk, score, null, null, null, null);
        }
    }

    private final DocumentService documentService;
    private final LegalChunkRepository legalChunkRepository;
    private final com.smartdocchat.util.LegalQueryNormalizer normalizer;
    private final SearchResultCache searchResultCache;

    public RetrievalService(DocumentService documentService,
                            LegalChunkRepository legalChunkRepository,
                            com.smartdocchat.util.LegalQueryNormalizer normalizer) {
        this(documentService, legalChunkRepository, normalizer, null);
    }

    /**
     * Retrieves the top-{@code topK} chunks for a query, sorted by descending score.
     * Prefers addressable legal evidence units when the document was ingested
     * with legal structure; otherwise falls back to the legacy generic chunks.
     * Returns an empty list when there are no lexical matches at all.
     * Owner isolation is enforced before any chunk is read.
     *
     * Decision 15 additions (all deterministic, no new infrastructure):
     *  - diacritic-folded, abbreviation-expanded match terms
     *  - explicit "Điều N [khoản M [điểm K]]" references boost chunks whose
     *    STRUCTURED METADATA matches (never text guesses)
     *  - explicit document numbers must match the chunk text to count
     *
     * Results are cached using a write-through cache with a key derived from
     * ownerUsername, documentId, query, and topK. Cache is invalidated when
     * documents are ingested, classified, or purged.
     */
    public List<RetrievalResult> retrieve(String ownerUsername, Long documentId, String query, int topK) {
        if (documentId == null || topK <= 0) {
            return List.of();
        }

        if (searchResultCache == null) {
            return performRetrieval(ownerUsername, documentId, query, topK);
        }

        // Build cache key from all parameters affecting results
        String cacheKey = buildCacheKey(ownerUsername, documentId, query, topK);

        return searchResultCache.getOrCompute(CacheNames.SEARCH_RESULTS, cacheKey, () -> performRetrieval(ownerUsername, documentId, query, topK));
    }

    /**
     * Performs the actual retrieval logic without caching.
     * Extracted to allow write-through caching via SearchResultCache.
     */
    private List<RetrievalResult> performRetrieval(String ownerUsername, Long documentId, String query, int topK) {
        // Owner isolation check first: throws when the document does not belong
        // to ownerUsername, so private chunks are never exposed cross-user.
        // We deliberately PROPAGATE this exception so the controller can return
        // a 404 (with audit log) rather than silently treating a forbidden doc
        // as "no evidence" — these are different security signals.
        documentService.getDocumentById(documentId, ownerUsername);

        Set<String> terms;
        java.util.Optional<com.smartdocchat.util.LegalQueryNormalizer.ArticleRef> ref;
        java.util.Optional<String> docNumber;
        try {
            terms = normalizer.matchTerms(query);
            ref = normalizer.extractArticleRef(query);
            docNumber = normalizer.extractDocumentNumber(query);
        } catch (RuntimeException e) {
            log.warn("retrieval aborted: query normalisation failed for doc={}: {}",
                    documentId, e.getMessage());
            return List.of();
        }
        terms.removeIf(t -> t.length() < 2);

        List<LegalChunk> legalChunks;
        List<String> allChunks;
        try {
            legalChunks = legalChunkRepository.findByDocumentIdOrderByOrdinalAsc(documentId);
            if (legalChunks != null && !legalChunks.isEmpty()) {
                return scoreAndTopK(legalChunks.stream()
                        .map(c -> new Candidate(c.getContent(), c.getId(),
                                c.getArticleNumber(), c.getClauseNumber(), c.getPointLabel()))
                        .toList(), terms, query, ref, docNumber, topK);
            }
            allChunks = documentService.getDocumentChunks(documentId, ownerUsername);
        } catch (RuntimeException e) {
            log.warn("retrieval aborted: backend source failed for doc={} owner={}: {}",
                    documentId, ownerUsername, e.getMessage());
            return List.of();
        }
        if (allChunks.isEmpty()) {
            return List.of();
        }
        return scoreAndTopK(allChunks.stream()
                .filter(c -> c != null && !c.isBlank())
                .map(c -> new Candidate(c, null, null, null, null))
                .toList(), terms, query, ref, docNumber, topK);
    }

    /**
     * Builds a cache key from all parameters that affect retrieval results.
     */
    private String buildCacheKey(String ownerUsername, Long documentId, String query, int topK) {
        return ownerUsername + ":" + documentId + ":" + query + ":" + topK;
    }

    /**
     * Invalidates all search result cache entries.
     * Called when documents are ingested, classified, or purged.
     */
    public void invalidateSearchCache() {
        if (searchResultCache != null) {
            searchResultCache.invalidateAll(CacheNames.SEARCH_RESULTS);
        }
    }

    /**
     * Invalidates search cache entries for a specific document.
     * Called when a specific document is updated or deleted.
     */
    public void invalidateSearchCacheForDocument(Long documentId) {
        // Note: This is a simple implementation. For production, consider using
        // cache key patterns or tags for more efficient partial invalidation.
        if (searchResultCache != null) {
            searchResultCache.invalidateAll(CacheNames.SEARCH_RESULTS);
        }
    }

    /** Internal candidate: chunk text plus optional structured metadata. */
    private record Candidate(String chunk, Long chunkId, String article, String clause, String point) {
    }

    /**
     * Minimum lexical relevance for a chunk to count as evidence. Below this,
     * only incidental single-word overlaps exist — treated as no match so that
     * irrelevant queries produce an honest empty result instead of noise.
     * Benchmark-justified: eliminates irrelevant-query false positives while
     * keeping every legitimate query above the line.
     */
    private static final double MIN_SCORE = 0.3;

    private List<RetrievalResult> scoreAndTopK(List<Candidate> candidates,
                                               Set<String> terms,
                                               String query,
                                               java.util.Optional<com.smartdocchat.util.LegalQueryNormalizer.ArticleRef> ref,
                                               java.util.Optional<String> docNumber,
                                               int topK) {
        if (candidates == null || candidates.isEmpty() || (terms.isEmpty() && ref.isEmpty() && docNumber.isEmpty())) {
            return List.of();
        }
        boolean docHasNumber = docNumber.isPresent();
        String foldedDocNumber = docHasNumber ? normalizer.fold(docNumber.get()) : "";

        record Scored(RetrievalResult result, double score) {
        }
        List<Scored> scored = new ArrayList<>();
        for (Candidate c : candidates) {
            double score = scoreChunkFolded(c.chunk(), terms);
            String foldedChunk = normalizer.foldContent(c.chunk());
            double bonus = normalizer.phraseBonus(query, foldedChunk, 5, 0.15);
            score = Math.min(1.0, score + bonus);

            // Structured metadata match is authoritative evidence of relevance:
            // "Điều 35" in the query boosts chunks whose article_number == 35,
            // while still allowing lexical scoring to distinguish the best clause.
            if (ref.isPresent()) {
                var r = ref.get();
                boolean articleMatch = r.article() != null && r.article().equals(c.article());
                boolean clauseMatch = r.clause() == null || r.clause().equals(c.clause())
                        || (r.clause() != null && c.clause() == null);
                boolean pointMatch = r.point() == null || r.point().equals(c.point());
                if (articleMatch && clauseMatch && pointMatch) {
                    score = Math.max(score, 0.85);
                }
            }
            if (docHasNumber && foldedChunk.contains(foldedDocNumber)) {
                score = Math.max(score, 0.80);
            }
            if (score <= MIN_SCORE) {
                continue;
            }
            scored.add(new Scored(new RetrievalResult(c.chunk(), Math.min(1.0, score),
                    c.chunkId(), c.article(), c.clause(), c.point()), score));
        }
        scored.sort(java.util.Comparator.comparingDouble(Scored::score).reversed());

        List<RetrievalResult> top = new ArrayList<>();
        for (int i = 0; i < scored.size() && top.size() < topK; i++) {
            top.add(scored.get(i).result());
        }
        return top;
    }

    /**
     * Folded scoring (Decision 15): identical 0.7*coverage + 0.3*frequency
     * formula, but both query terms and chunk content are diacritic-folded
     * and abbreviation-expanded before matching.
     */
    private double scoreChunkFolded(String chunk, Set<String> terms) {
        if (terms.isEmpty()) {
            return 0.0;
        }
        String folded = normalizer.foldContent(chunk);
        Set<String> matched = new LinkedHashSet<>();
        int totalHits = 0;
        for (String term : terms) {
            int hits = 0;
            int idx = 0;
            while (idx >= 0 && hits < 3) {
                idx = indexOfWord(folded, term, idx);
                if (idx >= 0) {
                    hits++;
                    idx += term.length();
                }
            }
            if (hits > 0) {
                matched.add(term);
                totalHits += hits;
            }
        }

        double coverage = matched.size() / (double) terms.size();
        double frequency = Math.min(1.0, totalHits * 0.15);
        double score = 0.7 * coverage + 0.3 * frequency;
        return Math.max(0.0, Math.min(1.0, score));
    }

    /**
     * Word-boundary-aware indexOf: a term only matches when surrounded by
     * non-letter characters. Prevents short Vietnamese terms from matching
     * inside unrelated longer words ("an" in "ban hanh").
     */
    private static int indexOfWord(String text, String term, int from) {
        int idx = text.indexOf(term, from);
        while (idx >= 0) {
            boolean leftOk = idx == 0 || !Character.isLetter(text.charAt(idx - 1));
            int end = idx + term.length();
            boolean rightOk = end >= text.length() || !Character.isLetter(text.charAt(end));
            if (leftOk && rightOk) {
                return idx;
            }
            idx = text.indexOf(term, idx + 1);
        }
        return -1;
    }

}