package com.smartdocchat.integration;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.testcontainers.containers.PostgreSQLContainer;

import javax.sql.DataSource;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Real-database integration test (Testcontainers PostgreSQL with local fallback).
 *
 * Verifies the Flyway migration chain applies cleanly to an actual PostgreSQL
 * instance and that the schema produced is usable via JdbcTemplate — a genuinely
 * end-to-end database verification (no Mockito).
 *
 * Primary path: Testcontainers postgres:16-alpine.
 * Fallback path (macOS Docker Desktop socket detection quirk): local postgres
 * at localhost:5434/smartdoc (smartdoc-local-postgres) — creates ephemeral
 * database smartdoc_test so the shared dev DB is not wiped by flyway.clean().
 * When neither is available the test is skipped cleanly (disabledWithoutDocker).
 */
class FlywayPostgresIntegrationTest {

    static PostgreSQLContainer<?> postgres;
    static Flyway flyway;
    static JdbcTemplate jdbc;
    static boolean usingLocalFallback = false;

    @BeforeAll
    static void migrate() {
        DataSource ds = null;
        // Try Testcontainers first — this handles the macOS Docker Desktop socket detection quirk
        // by catching startup failures and falling back to local postgres.
        try {
            postgres = new PostgreSQLContainer<>("postgres:16-alpine")
                    .withDatabaseName("smartdoc_test")
                    .withUsername("postgres")
                    .withPassword("postgres");
            postgres.start();
            if (postgres.isRunning()) {
                ds = new org.springframework.jdbc.datasource.DriverManagerDataSource(
                        postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
                usingLocalFallback = false;
            }
        } catch (Exception e) {
            // Testcontainers failed (known macOS quirk) — fall through to local fallback
            if (postgres != null) {
                try { postgres.stop(); } catch (Exception ignore) {}
                postgres = null;
            }
        }
        if (ds == null) {
            // Fallback to local postgres (smartdoc-local-postgres on 5434)
            try {
                DataSource adminDs = new org.springframework.jdbc.datasource.DriverManagerDataSource(
                        "jdbc:postgresql://localhost:5434/postgres", "postgres", "postgres");
                JdbcTemplate adminJdbc = new JdbcTemplate(adminDs);
                // Create isolated test database if not exists
                Integer exists = null;
                try {
                    exists = adminJdbc.queryForObject(
                            "SELECT 1 FROM pg_database WHERE datname='smartdoc_test'", Integer.class);
                } catch (Exception ignore) {}
                if (exists == null) {
                    adminJdbc.execute("CREATE DATABASE smartdoc_test");
                }
                ds = new org.springframework.jdbc.datasource.DriverManagerDataSource(
                        "jdbc:postgresql://localhost:5434/smartdoc_test", "postgres", "postgres");
                usingLocalFallback = true;
                // Verify connectivity before proceeding
                new JdbcTemplate(ds).queryForObject("SELECT 1", Integer.class);
            } catch (Exception e) {
                org.junit.jupiter.api.Assumptions.assumeTrue(false,
                        "Neither Testcontainers nor local postgres (localhost:5434) available — skipping: " + e.getMessage());
            }
        }
        flyway = Flyway.configure()
                .dataSource(ds)
                .cleanDisabled(false)
                .load();
        flyway.migrate();
        jdbc = new JdbcTemplate(ds);
    }

    @AfterAll
    static void cleanup() {
        if (flyway != null) {
            flyway.clean();
        }
        if (postgres != null) {
            try { postgres.stop(); } catch (Exception ignore) {}
        }
    }

    @Test
    void allMigrationsApplyAndCoreTablesExist() {
        Integer migrationCount = jdbc.queryForObject(
                "SELECT count(*) FROM flyway_schema_history", Integer.class);
        assertTrue(migrationCount != null && migrationCount >= 10,
                "expected >=10 Flyway migrations to have run, got " + migrationCount);

        // Core tables from V1/V2/V4/V9/V14 that the app relies on, plus the
        // durable ingestion queue (V16 — ADR-004 pattern).
        for (String table : new String[]{"users", "documents", "legal_chunks",
                "audit_logs", "entities", "document_ingestion_jobs"}) {
            Integer n = jdbc.queryForObject(
                    "SELECT count(*) FROM information_schema.tables "
                    + "WHERE table_schema='public' AND table_name=?", Integer.class, table);
            assertEquals(1, n, "expected table to exist: " + table);
        }
    }

    @Test
    void realInsertAndSelectRoundTrip() {
        String uniqueUser = "it_user_" + System.nanoTime();
        jdbc.update("INSERT INTO users (username, password, role, enabled) VALUES (?,?,?,?)",
                uniqueUser, "encoded", "ROLE_USER", true);
        Integer n = jdbc.queryForObject(
                "SELECT count(*) FROM users WHERE username=?", Integer.class, uniqueUser);
        assertEquals(1, n, "inserted row should be selectable through real PG");
    }
}