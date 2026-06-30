CREATE TABLE IF NOT EXISTS sentitrack_users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sentitrack_email_verifications (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    code VARCHAR(6) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_email_code (email, code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP PROCEDURE IF EXISTS migrate_sentitrack_reviews_user_id;

DELIMITER //

CREATE PROCEDURE migrate_sentitrack_reviews_user_id()
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name = 'sentitrack_reviews'
    ) THEN
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'sentitrack_reviews'
              AND column_name = 'user_id'
        ) THEN
            ALTER TABLE sentitrack_reviews
                ADD COLUMN user_id BIGINT NULL AFTER product_id;
        END IF;

        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'sentitrack_reviews'
              AND index_name = 'idx_user_created'
        ) THEN
            ALTER TABLE sentitrack_reviews
                ADD INDEX idx_user_created (user_id, created_at);
        END IF;

        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.referential_constraints
            WHERE constraint_schema = DATABASE()
              AND constraint_name = 'fk_reviews_user'
        ) AND NOT EXISTS (
            SELECT 1
            FROM sentitrack_reviews r
            LEFT JOIN sentitrack_users u ON r.user_id = u.id
            WHERE r.user_id IS NOT NULL
              AND u.id IS NULL
        ) THEN
            ALTER TABLE sentitrack_reviews
                ADD CONSTRAINT fk_reviews_user
                    FOREIGN KEY (user_id) REFERENCES sentitrack_users(id) ON DELETE CASCADE;
        END IF;
    END IF;
END//

DELIMITER ;

CALL migrate_sentitrack_reviews_user_id();
DROP PROCEDURE migrate_sentitrack_reviews_user_id;
