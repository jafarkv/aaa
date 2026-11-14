<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class SyncError extends Model
{
    protected $fillable = ['sync_run_id', 'supplier_id', 'service', 'method', 'message', 'context'];

    protected function casts(): array
    {
        return ['context' => 'array'];
    }

    public function run(): BelongsTo
    {
        return $this->belongsTo(SyncRun::class, 'sync_run_id');
    }
}
