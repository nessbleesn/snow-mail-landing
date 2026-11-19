<?php
declare(strict_types=1);

const ALLOWED_ORIGINS = [
    'https://parkskazka.ru',
    'https://www.parkskazka.ru',
    'https://nessbleesn.github.io',
];
const PUBLIC_PAGE_URL = 'https://parkskazka.ru/snow-mail/';
const GENERIC_ERROR = 'Не удалось отправить заявку. Попробуйте ещё раз.';

function env_value(string $name): string
{
    $value = getenv($name);
    return is_string($value) ? trim($value) : '';
}

function valid_bitrix_webhook(string $url): bool
{
    $parts = parse_url($url);
    return filter_var($url, FILTER_VALIDATE_URL) !== false
        && is_array($parts)
        && ($parts['scheme'] ?? '') === 'https'
        && strtolower($parts['host'] ?? '') === 'portal.parkskazka.com'
        && preg_match('#^/rest/[0-9]+/[^/\s]+/?$#', $parts['path'] ?? '') === 1
        && !isset($parts['port'])
        && !isset($parts['user'])
        && !isset($parts['pass'])
        && !isset($parts['query'])
        && !isset($parts['fragment']);
}

function valid_mock_url(string $url): bool
{
    $parts = parse_url($url);
    return is_array($parts)
        && ($parts['scheme'] ?? '') === 'http'
        && ($parts['host'] ?? '') === '127.0.0.1'
        && !isset($parts['user'])
        && !isset($parts['pass'])
        && !isset($parts['query'])
        && !isset($parts['fragment']);
}

function json_response(int $status, array $body): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    if ($status !== 204) {
        echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    }
    exit;
}

function safe_log(string $requestId, string $status, int $httpCode, ?int $leadId = null): void
{
    $path = env_value('LEAD_LOG_PATH');
    if ($path === '') {
        $path = rtrim(sys_get_temp_dir(), DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . 'snow-mail-leads.log';
    }
    $event = [
        'timestamp' => gmdate('c'),
        'request_id' => $requestId,
        'status' => $status,
        'http_code' => $httpCode,
    ];
    if ($leadId !== null) {
        $event['lead_id'] = $leadId;
    }
    @file_put_contents($path, json_encode($event, JSON_UNESCAPED_UNICODE) . PHP_EOL, FILE_APPEND | LOCK_EX);
}

function storage_dir(): string
{
    $directory = env_value('LEAD_STORAGE_DIR');
    if ($directory === '') {
        $directory = rtrim(sys_get_temp_dir(), DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . 'snow-mail';
    }
    if (!is_dir($directory) && !@mkdir($directory, 0700, true) && !is_dir($directory)) {
        throw new RuntimeException('Storage is unavailable');
    }
    return $directory;
}

function text_length(string $value): int
{
    return function_exists('mb_strlen') ? mb_strlen($value, 'UTF-8') : strlen($value);
}

function clean_text(mixed $value): string
{
    if (!is_string($value)) {
        return '';
    }
    $value = trim($value);
    return preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/u', '', $value) ?? '';
}

function normalize_phone(string $phone): string
{
    $digits = preg_replace('/\D+/', '', $phone) ?? '';
    if (strlen($digits) === 11 && $digits[0] === '8') {
        $digits = '7' . substr($digits, 1);
    } elseif (strlen($digits) === 10) {
        $digits = '7' . $digits;
    }
    return preg_match('/^7\d{10}$/', $digits) === 1 ? '+' . $digits : '';
}

function valid_event_date(string $date): bool
{
    $parsed = DateTimeImmutable::createFromFormat('!Y-m-d', $date);
    return $parsed !== false
        && $parsed->format('Y-m-d') === $date
        && $date >= '2026-12-14'
        && $date <= '2026-12-30';
}

function public_page_url(string $candidate): string
{
    $parts = parse_url($candidate);
    if (filter_var($candidate, FILTER_VALIDATE_URL) === false || !is_array($parts)) {
        return PUBLIC_PAGE_URL;
    }
    $host = strtolower($parts['host'] ?? '');
    if (($parts['scheme'] ?? '') !== 'https'
        || !in_array($host, ['parkskazka.ru', 'www.parkskazka.ru', 'nessbleesn.github.io'], true)
        || isset($parts['user'])
        || isset($parts['pass'])) {
        return PUBLIC_PAGE_URL;
    }
    return $candidate;
}

