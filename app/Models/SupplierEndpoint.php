<?php

namespace App\Models;

use App\PromoStandards\Service;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class SupplierEndpoint extends Model
{
    public const SOURCE_DIRECTORY = 'directory';

    public const SOURCE_MANUAL = 'manual';

    protected $fillable = [
        'supplier_id', 'service', 'version', 'url', 'source', 'is_enabled',
        'last_tested_at', 'last_test_status', 'last_test_message',
    ];

    protected function casts(): array
    {
        return [
            'is_enabled' => 'boolean',
            'last_tested_at' => 'datetime',
        ];
    }

    public function supplier(): BelongsTo
    {
        return $this->belongsTo(Supplier::class);
    }

    public function serviceEnum(): ?Service
    {
        return Service::tryFrom($this->service);
    }
}
