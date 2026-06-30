DROP PROCEDURE IF EXISTS migrate_sentitrack_products_scent_category;

DELIMITER //

CREATE PROCEDURE migrate_sentitrack_products_scent_category()
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name = 'sentitrack_products'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'sentitrack_products'
          AND column_name = 'scent_category'
    ) THEN
        ALTER TABLE sentitrack_products
            ADD COLUMN scent_category VARCHAR(50) NOT NULL DEFAULT 'UNKNOWN';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'sentitrack_products'
          AND column_name = 'scent_category'
    ) THEN
        UPDATE sentitrack_products SET scent_category = 'WOODY' WHERE id = 1;
        UPDATE sentitrack_products SET scent_category = 'FLORAL' WHERE id = 2;
        UPDATE sentitrack_products SET scent_category = 'AQUATIC' WHERE id = 3;
        UPDATE sentitrack_products SET scent_category = 'ORIENTAL' WHERE id = 4;
        UPDATE sentitrack_products SET scent_category = 'WOODY' WHERE id = 5;
        UPDATE sentitrack_products SET scent_category = 'MUSKY' WHERE id = 6;
        UPDATE sentitrack_products SET scent_category = 'GREEN' WHERE id = 7;
        UPDATE sentitrack_products SET scent_category = 'AQUATIC' WHERE id = 8;
        UPDATE sentitrack_products SET scent_category = 'FLORAL' WHERE id = 9;
        UPDATE sentitrack_products SET scent_category = 'FRESH' WHERE id = 10;
    END IF;
END//

DELIMITER ;

CALL migrate_sentitrack_products_scent_category();
DROP PROCEDURE migrate_sentitrack_products_scent_category;
