<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/** Per-supplier quirks (category, colour, size, price, field overrides). Applied by the Phase 1 normalizer. */
class SupplierMappingRule extends Model
{
    protected $fillable = ['supplier_id', 'scope', 'rule', 'is_active'];

    protected function casts(): array
    {
        return ['rule' => 'array', 'is_active' => 'boolean'];
    }

    public function supplier(): BelongsTo
    {
        return $this->belongsTo(Supplier::class);
    }
}
