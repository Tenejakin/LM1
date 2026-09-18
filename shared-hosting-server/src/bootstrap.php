<?php
declare(strict_types=1);

const APP_ROOT = __DIR__ . '/..';

function config(): array
{
    static $config;
    if ($config !== null) {
        return $config;
    }
    $path = APP_ROOT . '/config.php';
    if (!is_file($path)) {
        throw new RuntimeException('Server is not configured. Copy config.example.php to config.php.');
    }
    $config = require $path;
    if (!is_array($config)) {
        throw new RuntimeException('Invalid config.php.');
    }
    return $config;
}

function db(): PDO
{
    static $pdo;
    if ($pdo instanceof PDO) {
        return $pdo;
    }
    $db = config()['db'];
    $dsn = sprintf('mysql:host=%s;port=%d;dbname=%s;charset=%s', $db['host'], $db['port'], $db['name'], $db['charset']);
    $pdo = new PDO($dsn, $db['user'], $db['password'], [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);
    return $pdo;
}

function request_id(): string
{
    static $id;
    return $id ??= bin2hex(random_bytes(8));
}

function json_response(int $status, array $body): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('X-Request-Id: ' . request_id());
    $body['meta'] = array_merge($body['meta'] ?? [], ['requestId' => request_id()]);
    echo json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function fail(int $status, string $code, string $message): never
{
    json_response($status, ['error' => ['code' => $code, 'message' => $message]]);
}

function request_path(): string
{
    $path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
    $scriptDir = rtrim(str_replace('\\', '/', dirname($_SERVER['SCRIPT_NAME'] ?? '')), '/');
    if ($scriptDir !== '' && $scriptDir !== '/' && str_starts_with($path, $scriptDir)) {
        $path = substr($path, strlen($scriptDir));
    }
    if (str_starts_with($path, '/index.php')) {
        $path = substr($path, strlen('/index.php')) ?: '/';
    }
    return '/' . trim($path, '/');
}

function apply_cors(): void
{
    $origin = $_SERVER['HTTP_ORIGIN'] ?? '';
    $allowed = config()['allowed_origins'] ?? [];
    if (in_array('*', $allowed, true)) {
        header('Access-Control-Allow-Origin: *');
    } elseif ($origin !== '' && in_array($origin, $allowed, true)) {
        header('Access-Control-Allow-Origin: ' . $origin);
        header('Vary: Origin');
    }
    header('Access-Control-Allow-Headers: Content-Type, X-API-Key');
    header('Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS');
}

function require_api_key(): void
{
    $provided = trim($_SERVER['HTTP_X_API_KEY'] ?? '');
    $expected = (string) (config()['api_key'] ?? '');
    if ($expected === '' || str_starts_with($expected, 'REPLACE_') || !hash_equals($expected, $provided)) {
        fail(401, 'UNAUTHORIZED', 'A valid X-API-Key header is required.');
    }
}

function enforce_rate_limit(): void
{
    $limit = max(1, (int) (config()['rate_limit_per_minute'] ?? 120));
    $ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
    $bucket = gmdate('YmdHi');
    $path = APP_ROOT . '/storage/rate-' . hash('sha256', $ip . $bucket) . '.txt';
    $handle = fopen($path, 'c+');
    if ($handle === false) {
        return;
    }
    flock($handle, LOCK_EX);
    $count = (int) stream_get_contents($handle);
    if ($count >= $limit) {
        flock($handle, LOCK_UN);
        fclose($handle);
        header('Retry-After: 60');
        fail(429, 'RATE_LIMITED', 'Too many requests. Try again shortly.');
    }
    rewind($handle);
    ftruncate($handle, 0);
    fwrite($handle, (string) ($count + 1));
    fflush($handle);
    flock($handle, LOCK_UN);
    fclose($handle);
}

function uuid_v4(): string
{
    $bytes = random_bytes(16);
    $bytes[6] = chr((ord($bytes[6]) & 0x0f) | 0x40);
    $bytes[8] = chr((ord($bytes[8]) & 0x3f) | 0x80);
    return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($bytes), 4));
}

function decode_json_body(): array
{
    try {
        $value = json_decode(file_get_contents('php://input') ?: '{}', true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        fail(400, 'INVALID_JSON', 'The request body is not valid JSON.');
    }
    if (!is_array($value)) {
        fail(400, 'INVALID_JSON', 'The JSON body must be an object.');
    }
    return $value;
}

function store_image_bytes(string $bytes, ?string $claimedMime, ?string $originalName): array
{
    $max = (int) config()['max_upload_bytes'];
    if ($bytes === '' || strlen($bytes) > $max) {
        fail(413, 'INVALID_IMAGE_SIZE', 'Image is empty or exceeds the configured upload limit.');
    }
    $mime = (new finfo(FILEINFO_MIME_TYPE))->buffer($bytes);
    $extensions = ['image/jpeg' => 'jpg', 'image/png' => 'png', 'image/webp' => 'webp', 'image/gif' => 'gif'];
    if (!isset($extensions[$mime])) {
        fail(415, 'UNSUPPORTED_IMAGE', 'Only JPEG, PNG, WebP, and GIF images are accepted.');
    }
    if ($claimedMime !== null && $claimedMime !== '' && !str_starts_with($claimedMime, 'image/')) {
        fail(415, 'UNSUPPORTED_IMAGE', 'Invalid image content type.');
    }
    $now = new DateTimeImmutable('now', new DateTimeZone('UTC'));
    $relativeDir = $now->format('Y/m');
    $directory = APP_ROOT . '/uploads/' . $relativeDir;
    if (!is_dir($directory) && !mkdir($directory, 0750, true) && !is_dir($directory)) {
        throw new RuntimeException('Could not create upload directory.');
    }
    $relativePath = $relativeDir . '/' . bin2hex(random_bytes(20)) . '.' . $extensions[$mime];
    $fullPath = APP_ROOT . '/uploads/' . $relativePath;
    if (file_put_contents($fullPath, $bytes, LOCK_EX) === false) {
        throw new RuntimeException('Could not save uploaded image.');
    }
    return [$relativePath, $mime, strlen($bytes), $originalName];
}

function parse_create_request(): array
{
    $contentType = strtolower($_SERVER['CONTENT_TYPE'] ?? '');
    $data = [];
    $clientId = null;
    $image = [null, null, null, null];
    if (str_starts_with($contentType, 'multipart/form-data')) {
        $clientId = isset($_POST['client_id']) ? trim((string) $_POST['client_id']) : null;
        try {
            $data = json_decode((string) ($_POST['data'] ?? '{}'), true, 512, JSON_THROW_ON_ERROR);
        } catch (JsonException) {
            fail(400, 'INVALID_DATA', 'The multipart data field must contain valid JSON.');
        }
        if (isset($_FILES['image'])) {
            $file = $_FILES['image'];
            if ($file['error'] !== UPLOAD_ERR_OK) {
                fail(400, 'UPLOAD_FAILED', 'PHP rejected the image upload (code ' . (int) $file['error'] . ').');
            }
            $bytes = file_get_contents($file['tmp_name']);
            $image = store_image_bytes($bytes === false ? '' : $bytes, $file['type'] ?? null, $file['name'] ?? null);
        }
    } else {
        $body = decode_json_body();
        $clientId = isset($body['client_id']) ? trim((string) $body['client_id']) : null;
        $data = $body['data'] ?? [];
        if (isset($body['image_base64'])) {
            $encoded = (string) $body['image_base64'];
            if (str_contains($encoded, ',')) {
                [, $encoded] = explode(',', $encoded, 2);
            }
            $bytes = base64_decode($encoded, true);
            if ($bytes === false) {
                fail(400, 'INVALID_BASE64', 'image_base64 is not valid base64.');
            }
            $image = store_image_bytes($bytes, $body['image_mime'] ?? null, $body['image_name'] ?? null);
        }
    }
    if (!is_array($data)) {
        fail(400, 'INVALID_DATA', 'data must be a JSON object or array.');
    }
    if ($clientId !== null && strlen($clientId) > 191) {
        fail(400, 'INVALID_CLIENT_ID', 'client_id must be 191 characters or fewer.');
    }
    $json = json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
    if (strlen($json) > 1024 * 1024) {
        fail(413, 'DATA_TOO_LARGE', 'data JSON must be 1 MB or smaller.');
    }
    return [$clientId ?: null, $json, $image];
}
