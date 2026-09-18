<?php
declare(strict_types=1);

require __DIR__ . '/src/bootstrap.php';

try {
    apply_cors();
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'OPTIONS') {
        http_response_code(204);
        exit;
    }

    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    $path = request_path();

    if ($method === 'GET' && $path === '/api/v1/health') {
        db()->query('SELECT 1');
        json_response(200, ['data' => ['status' => 'ok', 'version' => config()['app_version'] ?? 'unknown']]);
    }

    require_api_key();
    enforce_rate_limit();

    if ($method === 'POST' && $path === '/api/v1/records') {
        [$clientId, $dataJson, $image] = parse_create_request();
        [$imagePath, $imageMime, $imageSize, $originalName] = $image;
        $publicId = uuid_v4();
        try {
            $stmt = db()->prepare('INSERT INTO records (public_id, client_id, data_json, image_path, image_mime, image_size, original_name) VALUES (?, ?, ?, ?, ?, ?, ?)');
            $stmt->execute([$publicId, $clientId, $dataJson, $imagePath, $imageMime, $imageSize, $originalName]);
        } catch (Throwable $error) {
            if ($imagePath !== null) {
                @unlink(APP_ROOT . '/uploads/' . $imagePath);
            }
            throw $error;
        }
        json_response(201, ['data' => ['id' => $publicId, 'client_id' => $clientId, 'has_image' => $imagePath !== null]]);
    }

    if ($method === 'GET' && $path === '/api/v1/records') {
        $limit = min(100, max(1, (int) ($_GET['limit'] ?? 25)));
        $before = isset($_GET['before']) ? (int) $_GET['before'] : PHP_INT_MAX;
        $stmt = db()->prepare('SELECT id, public_id, client_id, data_json, image_mime, image_size, created_at FROM records WHERE id < ? ORDER BY id DESC LIMIT ' . $limit);
        $stmt->execute([$before]);
        $rows = array_map(static function (array $row): array {
            $row['cursor'] = (int) $row['id'];
            unset($row['id']);
            $row['data'] = json_decode($row['data_json'], true);
            unset($row['data_json']);
            $row['has_image'] = $row['image_mime'] !== null;
            return $row;
        }, $stmt->fetchAll());
        $next = $rows === [] ? null : end($rows)['cursor'];
        json_response(200, ['data' => $rows, 'meta' => ['nextCursor' => $next]]);
    }

    if (preg_match('#^/api/v1/records/([0-9a-f-]{36})(/image)?$#i', $path, $matches)) {
        $id = strtolower($matches[1]);
        $stmt = db()->prepare('SELECT * FROM records WHERE public_id = ? LIMIT 1');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        if (!$row) {
            fail(404, 'NOT_FOUND', 'Record not found.');
        }
        if ($method === 'GET' && isset($matches[2])) {
            if ($row['image_path'] === null) {
                fail(404, 'IMAGE_NOT_FOUND', 'This record has no image.');
            }
            $file = APP_ROOT . '/uploads/' . $row['image_path'];
            if (!is_file($file)) {
                fail(404, 'IMAGE_NOT_FOUND', 'The image file is missing.');
            }
            header('Content-Type: ' . $row['image_mime']);
            header('Content-Length: ' . filesize($file));
            header('Content-Disposition: inline; filename="' . basename($row['image_path']) . '"');
            header('Cache-Control: private, max-age=3600');
            readfile($file);
            exit;
        }
        if ($method === 'GET' && !isset($matches[2])) {
            json_response(200, ['data' => [
                'id' => $row['public_id'],
                'client_id' => $row['client_id'],
                'data' => json_decode($row['data_json'], true),
                'image_mime' => $row['image_mime'],
                'image_size' => $row['image_size'] === null ? null : (int) $row['image_size'],
                'has_image' => $row['image_path'] !== null,
                'created_at' => $row['created_at'],
            ]]);
        }
        if ($method === 'DELETE' && !isset($matches[2])) {
            db()->beginTransaction();
            try {
                $delete = db()->prepare('DELETE FROM records WHERE public_id = ?');
                $delete->execute([$id]);
                db()->commit();
                if ($row['image_path'] !== null) {
                    @unlink(APP_ROOT . '/uploads/' . $row['image_path']);
                }
                http_response_code(204);
                exit;
            } catch (Throwable $error) {
                if (db()->inTransaction()) {
                    db()->rollBack();
                }
                throw $error;
            }
        }
    }

    fail(404, 'NOT_FOUND', 'Endpoint not found.');
} catch (Throwable $error) {
    error_log('[' . request_id() . '] ' . $error);
    fail(500, 'SERVER_ERROR', 'The server could not complete the request. Check the PHP error log with request ID ' . request_id() . '.');
}
