# LM1 Shared Hosting API

Version 1.0.0. A dependency-free PHP 8.1+ and MySQL/MariaDB API for saving arbitrary JSON data and optional images.

## Upload and install

1. In cPanel/Plesk, create a MySQL database and database user, then grant the user all permissions on that database.
2. Open phpMyAdmin, select the new database, choose **Import**, and import `schema.sql`.
3. Edit `config.php`. Enter the database values and replace `api_key` with a long random secret. `config.example.php` is a clean backup template.
4. Upload the contents of this folder to a folder such as `public_html/lm1-api/`, including `.htaccess` files.
5. Ensure `uploads/` and `storage/` are writable by PHP. On most hosts, permissions `755` work; use `775` only if your host requires it.
6. Visit `https://your-domain.example/lm1-api/api/v1/health`. A successful response contains `"status":"ok"`.

Keep `config.php` out of source control and never place the API key in a public web page. HTTPS is required in production. If the health URL returns a 404, enable Apache `mod_rewrite`/AllowOverride with your host, or use `index.php/api/v1/health` and include `index.php` in all paths.

Your PHP limits must allow the configured upload size. In the hosting PHP settings, set `upload_max_filesize` and `post_max_size` to at least `16M` for the default 15 MB API limit.

## Send an image and JSON data

Multipart form upload:

```bash
curl -X POST "https://your-domain.example/lm1-api/api/v1/records" \
  -H "X-API-Key: YOUR_SECRET" \
  -F 'client_id=device-001' \
  -F 'data={"ballSpeed":62.4,"club":"driver","notes":"practice"}' \
  -F 'image=@capture.jpg'
```

JSON/base64 upload:

```json
{
  "client_id": "device-001",
  "data": { "ballSpeed": 62.4, "club": "driver" },
  "image_mime": "image/jpeg",
  "image_name": "capture.jpg",
  "image_base64": "/9j/4AAQSkZJRg..."
}
```

POST this JSON to `/api/v1/records` with headers `Content-Type: application/json` and `X-API-Key: YOUR_SECRET`. The image is optional; `data` may contain any JSON object or array.

## Read and delete

All calls except health require `X-API-Key`.

```text
GET    /api/v1/health
POST   /api/v1/records
GET    /api/v1/records?limit=25&before=CURSOR
GET    /api/v1/records/RECORD_UUID
GET    /api/v1/records/RECORD_UUID/image
DELETE /api/v1/records/RECORD_UUID
```

List results contain a `cursor`. Pass the last result's cursor as `before` for the next page. The server accepts JPEG, PNG, WebP, and GIF files, verifies their real content type, randomizes stored filenames, uses prepared SQL queries, protects image storage from direct web access, and applies a simple per-IP rate limit.

## JavaScript example

```js
const form = new FormData();
form.append('client_id', 'device-001');
form.append('data', JSON.stringify({ ballSpeed: 62.4, club: 'driver' }));
form.append('image', imageFile);

const response = await fetch('https://your-domain.example/lm1-api/api/v1/records', {
  method: 'POST',
  headers: { 'X-API-Key': 'YOUR_SECRET' },
  body: form,
});

if (!response.ok) throw new Error(await response.text());
console.log(await response.json());
```

## Backup and operations

Back up both the MySQL database and `uploads/`; either one alone is incomplete. The default operating target is p95 under 1 second, p99 under 2 seconds, 99.5% availability, RPO 24 hours, and RTO 4 hours. Actual results depend on the shared host. Configure daily backups in the hosting panel and test a restore.

For production, replace `allowed_origins: ['*']` with the exact browser origins that may call the API. Native mobile apps are controlled by the API key and do not rely on browser CORS.
