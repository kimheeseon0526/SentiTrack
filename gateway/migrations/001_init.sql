DROP TABLE IF EXISTS sentitrack_reviews;
DROP TABLE IF EXISTS sentitrack_products;

CREATE TABLE IF NOT EXISTS sentitrack_products (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    origin VARCHAR(100) NOT NULL,
    description VARCHAR(500) NOT NULL,
    price_won INT NOT NULL,
    image_url VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sentitrack_reviews (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id BIGINT NOT NULL,
    review_text VARCHAR(2000) NOT NULL,
    sentiment_label VARCHAR(20) NOT NULL,
    confidence_score DECIMAL(5, 4) NOT NULL,
    model_version VARCHAR(100) NOT NULL,
    latency_ms DECIMAL(10, 2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES sentitrack_products(id) ON DELETE CASCADE,
    INDEX idx_product_created (product_id, created_at),
    INDEX idx_sentiment_label (sentiment_label)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO sentitrack_products (name, origin, description, price_won, image_url) VALUES
('Velvet Amber', 'Woody Oriental', 'A warm embrace of amber, sandalwood, and soft musk.', 89000, NULL),
('Midnight Bloom', 'Floral', 'Night-blooming jasmine with a whisper of dark cherry.', 95000, NULL),
('Quiet Rain', 'Aquatic', 'The calm of falling rain on cedar and grey moss.', 78000, NULL),
('Golden Hour', 'Citrus Floral', 'Sun-warmed bergamot and neroli at dusk.', 82000, NULL),
('Smoked Vetiver', 'Woody', 'Earthy vetiver wrapped in a trail of soft smoke.', 99000, NULL),
('Paper & Ink', 'Woody Musk', 'The nostalgic scent of an old library, warm and dry.', 76000, NULL),
('Wild Fig Garden', 'Green Floral', 'Sun-ripened fig leaves and a touch of white tea.', 84000, NULL),
('Salt & Linen', 'Fresh Musk', 'Sea salt air and freshly pressed white linen.', 72000, NULL),
('Rose in the Dark', 'Floral Woody', 'A velvety rose deepened by patchouli and smoked wood.', 105000, NULL),
('First Snow', 'Powdery Musk', 'Cool iris and soft powder, like the quiet after snowfall.', 91000, NULL);
