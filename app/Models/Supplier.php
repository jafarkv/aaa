<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Database\Eloquent\Relations\HasOne;

/**
 * A supplier profile. Suppliers are configuration, not code: adding one is a row here
 * plus credentials and endpoints, never a deploy.
 */
class Supplier extends Model
{
    public const STATUS_DRAFT = 'draft';

    public const STATUS_TESTING = 'testing';

    public const STATUS_READY = 'ready';   // set by the Catalog lead only, after the quality report passes

    public const STATUS_PAUSED = 'paused';

    protected $fillable = [
        'name', 'slug', 'promostandards_code', 'type', 'status', 'account_number',
        'sample_product_id', 'concurrency_limit', 'request_delay_ms', 'is_active', 'deactivated_at',
    ];

    protected function casts(): array
    {
        return [
            'is_active' => 'boolean',
            'deactivated_at' => 'datetime',
            'concurrency_limit' => 'integer',
            'request_delay_ms' => 'integer',
        ];
    }

    public function credentials(): HasOne
    {
        return $this->hasOne(SupplierCredential::class);
    }

    public function endpoints(): HasMany
    {
        return $this->hasMany(SupplierEndpoint::class);
    }

    public function mappingRules(): HasMany
    {
        return $this->hasMany(SupplierMappingRule::class);
    }

    public function scopeActive(Builder $query): Builder
    {
        return $query->where('is_active', true);
    }

    /** Suppliers are never deleted: deactivate to keep every historical row traceable. */
    public function deactivate(): void
    {
        $this->update(['is_active' => false, 'deactivated_at' => now(), 'status' => self::STATUS_PAUSED]);
    }
}
