<?php

return [
    /*
     * Where the PromoStandards endpoint directory is fetched from. Left empty on purpose:
     * the sandbox this was built in could not reach promostandards.org, so the URL and the
     * response shape are NOT verified. Set PROMOSTANDARDS_DIRECTORY_URL once confirmed, or
     * pass --file=directory.json to hub:directory:import with an export of the directory.
     */
    'directory_url' => env('PROMOSTANDARDS_DIRECTORY_URL'),

    // Seconds before a supplier call is abandoned. Supplier SOAP services can be slow.
    'timeout' => (int) env('PROMOSTANDARDS_TIMEOUT', 30),

    // Disk (see config/filesystems.php) holding untouched supplier responses, gzip-compressed.
    // Use a dedicated disk or an S3-compatible bucket in production, not the web-served disk.
    'raw_disk' => env('HUB_RAW_DISK', 'local'),
];
