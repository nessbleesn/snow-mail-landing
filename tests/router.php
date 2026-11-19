<?php
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
if ($path === '/api/lead' || $path === '/api/lead/') {
    require dirname(__DIR__) . '/api/lead/index.php';
    return true;
}
return false;

