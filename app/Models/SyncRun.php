<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

class SyncRun extends Model
{
    protected $fillable = [
        'supplier_id', 'service', 'tier', 'status', 'started_at', 'finished_at',
        'items_seen', 'items_changed', 'error_count',
    ];

    protected function casts(): array
    {
        return ['started_at' => 'datetime', 'finished_at' => 'datetime'];
    }

    public function supplier(): BelongsTo
    {
        return $this->belongsTo(Supplier::class);
    }

    public function errors(): HasMany
    {
        return $this->hasMany(SyncError::class);
    }
}
