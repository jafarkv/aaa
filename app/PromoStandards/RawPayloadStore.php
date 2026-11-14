<?php

namespace App\PromoStandards;

use App\Models\RawPayload;
use App\Models\Supplier;
use Illuminate\Support\Facades\Storage;

/**
 * Keeps every supplier response untouched. Normalization (Phase 1) reads from here, so
 * improving the mapping logic never means calling suppliers again. Identical responses
 * share one file; every fetch still gets its own row so history is complete.
 */
class RawPayloadStore
{
    public function store(
        Supplier $supplier,
        Service $service,
        string $method,
        string $requestHash,
        string $responseBody,
        ?int $httpStatus,
    ): RawPayload {
        $hash = hash('sha256', $responseBody);
        $path = sprintf('raw/%d/%s/%s/%s.xml.gz', $supplier->id, $service->value, now()->format('Y-m-d'), $hash);
        $disk = Storage::disk(config('promostandards.raw_disk'));

        if (! $disk->exists($path)) {
            $disk->put($path, gzencode($responseBody, 6));
        }

        return RawPayload::create([
            'supplier_id' => $supplier->id,
            'service' => $service->value,
            'method' => $method,
            'request_hash' => $requestHash,
            'response_hash' => $hash,
            'storage_path' => $path,
            'bytes' => strlen($responseBody),
            'http_status' => $httpStatus,
            'fetched_at' => now(),
        ]);
    }
}
