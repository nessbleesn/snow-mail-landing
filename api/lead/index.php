<?php
declare(strict_types=1);

require dirname(__DIR__) . '/_bootstrap.php';

$origin = rtrim((string) ($_SERVER['HTTP_ORIGIN'] ?? ''), '/');
if (!in_array($origin, ALLOWED_ORIGINS, true)) {
    safe_log('', 'origin_rejected', 403);
    json_response(403, ['ok' => false, 'error' => GENERIC_ERROR]);
}

header('Access-Control-Allow-Origin: ' . $origin);
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
header('Access-Control-Max-Age: 600');
header('Vary: Origin');

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') {
    json_response(204, []);
}
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    json_response(405, ['ok' => false, 'error' => GENERIC_ERROR]);
}

$contentType = strtolower(trim(explode(';', (string) ($_SERVER['CONTENT_TYPE'] ?? ''))[0]));
if ($contentType !== 'application/json') {
    safe_log('', 'validation_error', 400);
    json_response(400, ['ok' => false, 'error' => GENERIC_ERROR]);
}

$contentLength = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
if ($contentLength < 1 || $contentLength > 16384) {
    safe_log('', 'validation_error', 400);
    json_response(400, ['ok' => false, 'error' => GENERIC_ERROR]);
}

$raw = file_get_contents('php://input', false, null, 0, 16385);
if (!is_string($raw) || strlen($raw) > 16384) {
    safe_log('', 'validation_error', 400);
    json_response(400, ['ok' => false, 'error' => GENERIC_ERROR]);
}
$data = json_decode($raw, true);
if (!is_array($data)) {
    safe_log('', 'validation_error', 400);
    json_response(400, ['ok' => false, 'error' => GENERIC_ERROR]);
}

$requestId = clean_text($data['request_id'] ?? '');
if (preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i', $requestId) !== 1) {
    safe_log('', 'validation_error', 400);
    json_response(400, ['ok' => false, 'error' => GENERIC_ERROR]);
}

if (clean_text($data['website'] ?? '') !== '') {
    safe_log($requestId, 'spam_honeypot', 200);
    json_response(200, ['ok' => true]);
}

$elapsed = filter_var($data['elapsed_ms'] ?? null, FILTER_VALIDATE_INT, [
    'options' => ['min_range' => 700, 'max_range' => 86400000],
]);
if ($elapsed === false) {
    safe_log($requestId, 'validation_error', 400);
    json_response(400, ['ok' => false, 'error' => GENERIC_ERROR]);
}

$name = clean_text($data['name'] ?? '');
$phone = normalize_phone(clean_text($data['phone'] ?? ''));
$date = clean_text($data['date'] ?? '');
$children = filter_var($data['children'] ?? null, FILTER_VALIDATE_INT, [
    'options' => ['min_range' => 10, 'max_range' => 60],
]);
$age = clean_text($data['age'] ?? '');
$comment = clean_text($data['comment'] ?? '');
$consent = ($data['consent'] ?? null) === true;
$pageUrl = public_page_url(clean_text($data['page_url'] ?? ''));
$referrer = clean_text($data['referrer'] ?? '');

$utm = [];
foreach (['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'] as $key) {
    $value = clean_text($data[$key] ?? '');
    if (text_length($value) > 255) {
        safe_log($requestId, 'validation_error', 400);
        json_response(400, ['ok' => false, 'error' => GENERIC_ERROR]);
    }
    $utm[$key] = $value;
}

$valid = text_length($name) >= 2
    && text_length($name) <= 100
    && $phone !== ''
    && valid_event_date($date)
    && $children !== false
    && text_length($age) <= 80
    && text_length($comment) <= 1000
    && text_length($referrer) <= 1000
    && $consent;
if (!$valid) {
    safe_log($requestId, 'validation_error', 422);
    json_response(422, ['ok' => false, 'error' => GENERIC_ERROR]);
}

try {
    $storage = storage_dir();
} catch (Throwable $error) {
    safe_log($requestId, 'storage_error', 502);
    json_response(502, ['ok' => false, 'error' => GENERIC_ERROR]);
}

$ip = (string) ($_SERVER['REMOTE_ADDR'] ?? 'unknown');
$ratePath = $storage . DIRECTORY_SEPARATOR . 'rate-' . hash('sha256', $ip) . '.json';
$rateHandle = @fopen($ratePath, 'c+');
if ($rateHandle === false || !flock($rateHandle, LOCK_EX)) {
    if (is_resource($rateHandle)) {
        fclose($rateHandle);
    }
    safe_log($requestId, 'storage_error', 502);
    json_response(502, ['ok' => false, 'error' => GENERIC_ERROR]);
}
$rateRaw = stream_get_contents($rateHandle);
$timestamps = json_decode(is_string($rateRaw) ? $rateRaw : '[]', true);
$timestamps = is_array($timestamps)
    ? array_values(array_filter($timestamps, static fn ($value): bool => is_int($value) && $value > time() - 600))
    : [];
if (count($timestamps) >= 5) {
    flock($rateHandle, LOCK_UN);
    fclose($rateHandle);
    safe_log($requestId, 'rate_limited', 429);
    json_response(429, ['ok' => false, 'error' => GENERIC_ERROR]);
}
$timestamps[] = time();
ftruncate($rateHandle, 0);
rewind($rateHandle);
fwrite($rateHandle, json_encode($timestamps));
fflush($rateHandle);
flock($rateHandle, LOCK_UN);
fclose($rateHandle);

$idempotencyPath = $storage . DIRECTORY_SEPARATOR . 'request-' . hash('sha256', strtolower($requestId)) . '.lock';
$idempotencyHandle = @fopen($idempotencyPath, 'x');
if ($idempotencyHandle === false) {
    safe_log($requestId, 'duplicate', 409);
    json_response(409, ['ok' => false, 'error' => GENERIC_ERROR]);
}
fwrite($idempotencyHandle, gmdate('c'));
fclose($idempotencyHandle);

$consentAt = gmdate('c');
$ageText = $age !== '' ? $age : 'не указан';
$commentText = $comment !== '' ? $comment : 'нет';
$referrerText = $referrer !== '' ? $referrer : 'direct';
$fields = [
    'TITLE' => 'Снежная почта - ' . $name,
    'NAME' => $name,
    'PHONE' => [['VALUE' => $phone, 'VALUE_TYPE' => 'WORK']],
    'STATUS_ID' => 'NEW',
    'SOURCE_ID' => 'WEB_EVENTS',
    'SOURCE_DESCRIPTION' => 'Лендинг parkskazka.ru - Снежная почта',
    'UF_CRM_1786957436490' => 2594,
    'UF_CRM_1786957550526' => $pageUrl,
    'UF_CRM_1786958358509' => 'snow-mail',
    'COMMENTS' => "Желаемая дата: {$date}\nКоличество детей: {$children}\nВозраст детей: {$ageText}\nКомментарий: {$commentText}\nСогласие на обработку персональных данных: получено\nДата и время согласия: {$consentAt}\nСтраница: {$pageUrl}\nИсточник перехода: {$referrerText}",
    'UTM_SOURCE' => $utm['utm_source'],
    'UTM_MEDIUM' => $utm['utm_medium'],
    'UTM_CAMPAIGN' => $utm['utm_campaign'],
    'UTM_CONTENT' => $utm['utm_content'],
    'UTM_TERM' => $utm['utm_term'],
];

$mockMode = env_value('BITRIX_MOCK_MODE') === '1';
$baseUrl = $mockMode ? env_value('BITRIX_MOCK_URL') : env_value('BITRIX_WEBHOOK_URL');
if ((!$mockMode && !valid_bitrix_webhook($baseUrl)) || ($mockMode && !valid_mock_url($baseUrl))) {
    safe_log($requestId, 'configuration_error', 503);
    json_response(503, ['ok' => false, 'error' => GENERIC_ERROR]);
}

$request = curl_init(rtrim($baseUrl, '/') . '/crm.lead.add.json');
curl_setopt_array($request, [
    CURLOPT_POST => true,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => ['Accept: application/json', 'Content-Type: application/json'],
    CURLOPT_POSTFIELDS => json_encode(['fields' => $fields], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
    CURLOPT_CONNECTTIMEOUT => 3,
    CURLOPT_TIMEOUT => 10,
    CURLOPT_SSL_VERIFYPEER => true,
    CURLOPT_SSL_VERIFYHOST => 2,
]);

$responseBody = curl_exec($request);
$transportError = curl_errno($request);
$responseCode = (int) curl_getinfo($request, CURLINFO_RESPONSE_CODE);
curl_close($request);

if ($transportError === CURLE_OPERATION_TIMEDOUT) {
    safe_log($requestId, 'timeout', 504);
    json_response(504, ['ok' => false, 'error' => GENERIC_ERROR]);
}
if ($transportError !== 0 || $responseCode < 200 || $responseCode >= 300 || !is_string($responseBody)) {
    safe_log($requestId, 'bitrix_error', 502);
    json_response(502, ['ok' => false, 'error' => GENERIC_ERROR]);
}

$response = json_decode($responseBody, true);
$leadId = is_array($response) && is_int($response['result'] ?? null) ? $response['result'] : 0;
if ($leadId <= 0) {
    safe_log($requestId, 'bitrix_error', 502);
    json_response(502, ['ok' => false, 'error' => GENERIC_ERROR]);
}

safe_log($requestId, 'success', 200, $leadId);
json_response(200, ['ok' => true, 'leadId' => $leadId]);

