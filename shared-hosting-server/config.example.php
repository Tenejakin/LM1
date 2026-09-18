<?php
declare(strict_types=1);

return [
    'app_version' => '1.0.0',
    'db' => [
        'host' => 'localhost',
        'port' => 3306,
        'name' => 'YOUR_DATABASE_NAME',
        'user' => 'YOUR_DATABASE_USER',
        'password' => 'YOUR_DATABASE_PASSWORD',
        'charset' => 'utf8mb4',
    ],
    // Generate one with: php -r "echo bin2hex(random_bytes(32)), PHP_EOL;"
    'api_key' => 'REPLACE_WITH_A_LONG_RANDOM_SECRET',
    'allowed_origins' => ['*'],
    'max_upload_bytes' => 15 * 1024 * 1024,
    'rate_limit_per_minute' => 120,
];
