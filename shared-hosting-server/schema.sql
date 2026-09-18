CREATE TABLE IF NOT EXISTS `records` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `public_id` CHAR(36) NOT NULL,
  `client_id` VARCHAR(191) NULL,
  `data_json` JSON NOT NULL,
  `image_path` VARCHAR(255) NULL,
  `image_mime` VARCHAR(50) NULL,
  `image_size` INT UNSIGNED NULL,
  `original_name` VARCHAR(255) NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_records_public_id` (`public_id`),
  KEY `idx_records_client_created` (`client_id`, `created_at`),
  KEY `idx_records_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
