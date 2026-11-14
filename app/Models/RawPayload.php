<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/** Pointer to an untouched supplier response stored on the raw disk. */
class RawPayload extends Model
{
    protected $fillable = [
        'supplier_id', 'service', 'method', 'request_hash', 'response_hash',
        'storage_path', 'bytes', 'http_status', 'fetched_at',
    ];

    protected function casts(): array
    {
        return ['fetched_at' => 'datetime'];
    }

    public function supplier(): BelongsTo
    {
        return $this->belongsTo(Supplier::class);
    }
}
